"""Tests for the read-only PK/PD FastAPI service."""

from datetime import datetime, timezone
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from agents.schemas import (
    AnalysisSummary,
    CovariateEffect,
    DiagnosticsSummary,
    DosingRecommendation,
    ParameterEstimate,
    PKCandidateResult,
    PKModelComparison,
)
from api.main import app, set_analysis_summary


def _synthetic_summary() -> AnalysisSummary:
    return AnalysisSummary(
        run_id="api-test-run",
        generated_at=datetime.now(timezone.utc),
        input_files=[],
        pk_model=PKModelComparison(
            candidates=[
                PKCandidateResult(
                    model_type="1-compartment",
                    converged=True,
                    parameters={
                        "CL": ParameterEstimate(estimate=0.4, unit="L/h"),
                        "V": ParameterEstimate(estimate=5.0, unit="L"),
                    },
                )
            ],
            selected_model="1-compartment",
            selection_rationale="Synthetic API fixture.",
        ),
        covariate_effects=[
            CovariateEffect(
                covariate="weight_kg",
                parameter_affected="CL",
                effect_form="allometric_exponent",
                effect_estimate=0.8,
                reference_value=60.0,
                comparison_value=85.0,
                confidence_interval=(0.5, 1.1),
                p_value=0.001,
                clinically_material=True,
                interpretation="Weight was materially associated with CL.",
            )
        ],
        exposure_response=[],
        diagnostics=DiagnosticsSummary(
            pk_model_converged=True,
            parameter_covariance_valid=True,
            predictive_check_passed=True,
            major_residual_bias=False,
            summary="The selected model passed the simplified predictive check.",
        ),
        dosing_recommendations=[
            DosingRecommendation(
                subgroup="overall population",
                action="maintain_current_dose",
                recommended_dose_mg=100.0,
                evidence_basis="observed",
                rationale="Maintain the studied dose for the overall population.",
                confidence="moderate",
            ),
            DosingRecommendation(
                subgroup="patients in the upper weight quartile",
                action="insufficient_evidence",
                recommended_dose_mg=None,
                evidence_basis="observed",
                rationale=(
                    "A material weight effect was observed, but exposure-matching "
                    "simulation was not performed."
                ),
                confidence="low",
            ),
        ],
        limitations=[],
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    set_analysis_summary(_synthetic_summary())
    with TestClient(app) as test_client:
        yield test_client
    set_analysis_summary(None)


def test_model_summary_returns_expected_top_level_keys(client: TestClient) -> None:
    response = client.get("/model-summary")

    assert response.status_code == 200
    assert set(response.json()) == {
        "selected_pk_model",
        "pk_parameters",
        "covariate_effects_summary",
        "key_findings",
        "last_analysis_run_id",
        "last_analysis_generated_at",
    }
    assert response.json()["selected_pk_model"] == "1-compartment"
    assert response.json()["pk_parameters"] == {"CL": 0.4, "V": 5.0}


def test_valid_recommendation_request_returns_response_model(
    client: TestClient,
) -> None:
    response = client.post(
        "/recommend",
        json={
            "weight_kg": 70.0,
            "creatinine_clearance_ml_min": 95.0,
            "genotype": "WT/MUT",
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "maintain_current_dose"
    assert response.json()["recommended_dose_mg"] == 100.0
    assert response.json()["uncertainty_note"].endswith("not a live simulation.")


def test_invalid_genotype_returns_422(client: TestClient) -> None:
    response = client.post(
        "/recommend",
        json={
            "weight_kg": 70.0,
            "creatinine_clearance_ml_min": 95.0,
            "genotype": "UNKNOWN",
        },
    )

    assert response.status_code == 422


def test_upper_weight_range_returns_weight_subgroup_recommendation(
    client: TestClient,
) -> None:
    response = client.post(
        "/recommend",
        json={
            "weight_kg": 85.0,
            "creatinine_clearance_ml_min": 95.0,
            "genotype": "MUT/MUT",
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "insufficient_evidence"
    assert response.json()["confidence"] == "low"
    assert response.json()["recommended_dose_mg"] is None
    assert "upper-quartile boundary" in response.json()["rationale"]

