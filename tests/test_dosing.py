"""Tests for conservative rule-based dosing recommendations."""

from typing import List

from agents.schemas import (
    CovariateEffect,
    DiagnosticsSummary,
    ExposureResponseResult,
)
from pipeline.dosing import generate_dosing_recommendations


def _exposure_results() -> List[ExposureResponseResult]:
    return [
        ExposureResponseResult(
            endpoint="clinical_response",
            endpoint_type="efficacy",
            model_form="logistic_univariate",
            exposure_metric="AUC_0_inf",
            converged=True,
            n_patients=100,
            n_events=60,
            effect_estimate=0.02,
            ci_lower=0.01,
            ci_upper=0.03,
            key_finding="Synthetic efficacy result.",
        ),
        ExposureResponseResult(
            endpoint="grade2plus_adverse_event",
            endpoint_type="safety",
            model_form="logistic_univariate",
            exposure_metric="AUC_0_inf",
            converged=True,
            n_patients=100,
            n_events=20,
            effect_estimate=0.002,
            ci_lower=-0.01,
            ci_upper=0.02,
            key_finding="Synthetic safety result.",
        ),
    ]


def _diagnostics() -> DiagnosticsSummary:
    return DiagnosticsSummary(
        pk_model_converged=True,
        parameter_covariance_valid=True,
        predictive_check_passed=True,
        major_residual_bias=False,
        summary="Synthetic diagnostics.",
    )


def test_supported_efficacy_and_nonsignificant_safety_maintains_dose() -> None:
    recommendations = generate_dosing_recommendations(
        [],
        _exposure_results(),
        _diagnostics(),
    )

    overall = recommendations[0]
    assert overall.subgroup == "overall population"
    assert overall.action == "maintain_current_dose"
    assert overall.recommended_dose_mg == 100.0


def test_material_clearance_covariate_requires_simulation_not_new_dose() -> None:
    material_effect = CovariateEffect(
        covariate="weight_kg",
        parameter_affected="CL",
        effect_form="allometric_exponent",
        effect_estimate=0.8,
        reference_value=60.0,
        comparison_value=90.0,
        confidence_interval=(0.5, 1.1),
        clinically_material=True,
        interpretation="Synthetic material effect.",
    )

    recommendations = generate_dosing_recommendations(
        [material_effect],
        _exposure_results(),
        _diagnostics(),
    )
    subgroup = recommendations[1]

    assert subgroup.action == "insufficient_evidence"
    assert subgroup.recommended_dose_mg is None
    assert "exposure-matching simulation" in subgroup.rationale


def test_nonmaterial_covariate_has_no_adjustment_or_alternative_dose() -> None:
    nonmaterial_effect = CovariateEffect(
        covariate="genotype",
        parameter_affected="CL",
        effect_form="log_scale_per_mutant_allele",
        effect_estimate=0.03,
        reference_value=0.0,
        comparison_value=2.0,
        confidence_interval=(-0.02, 0.08),
        clinically_material=False,
        interpretation="Synthetic non-material effect.",
    )

    recommendations = generate_dosing_recommendations(
        [nonmaterial_effect],
        _exposure_results(),
        _diagnostics(),
    )
    subgroup = recommendations[1]

    assert subgroup.action == "no_subgroup_adjustment"
    assert subgroup.recommended_dose_mg == 100.0
    assert all(
        recommendation.recommended_dose_mg in (None, 100.0)
        for recommendation in recommendations
    )
