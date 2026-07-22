"""Tests for aggregation of existing diagnostic evidence."""

from typing import List

import numpy as np
import pandas as pd
import pytest

from agents.schemas import (
    CovariateEffect,
    ExposureResponseResult,
    ParameterEstimate,
    PKCandidateResult,
    PKModelComparison,
)
from pipeline.diagnostics import summarize_diagnostics
from pipeline.pk import one_compartment_concentration


def _comparison(converged: bool) -> PKModelComparison:
    return PKModelComparison(
        candidates=[
            PKCandidateResult(
                model_type="1-compartment",
                converged=converged,
                parameters={
                    "CL": ParameterEstimate(
                        estimate=5.0,
                        ci_lower=4.0,
                        ci_upper=6.0,
                    ),
                    "V": ParameterEstimate(
                        estimate=20.0,
                        ci_lower=18.0,
                        ci_upper=22.0,
                    ),
                },
            )
        ],
        selected_model="1-compartment",
        selection_rationale="Synthetic test model.",
    )


def _observed_concentrations(scale: float = 1.0) -> pd.DataFrame:
    times = np.asarray([0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0])
    concentrations = one_compartment_concentration(times, 5.0, 20.0, 100.0)
    return pd.DataFrame(
        {
            "patient_id": ["P1"] * 8,
            "time_hours": times,
            "dose_mg": [100.0] * 8,
            "concentration_mg_l": concentrations * scale,
        }
    )


def _patient_pk(converged: bool) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "patient_id": ["P1"],
            "model_type": ["1-compartment"],
            "converged": [converged],
            "CL": [5.0],
            "V": [20.0],
            "dose_mg": [100.0],
        }
    )


def test_good_inputs_produce_no_critical_flags() -> None:
    exposure_results: List[ExposureResponseResult] = [
        ExposureResponseResult(
            endpoint="clinical_response",
            endpoint_type="efficacy",
            model_form="logistic_univariate",
            exposure_metric="AUC_0_inf",
            converged=True,
            n_patients=20,
            n_events=10,
            key_finding="Synthetic converged result.",
        )
    ]

    report = summarize_diagnostics(
        _comparison(converged=True),
        _patient_pk(converged=True),
        [],
        exposure_results,
        _observed_concentrations(),
    )

    assert report.pk_model_converged is True
    assert report.parameter_covariance_valid is True
    assert report.predictive_check_passed is True
    assert report.major_residual_bias is False
    assert report.critical_flags == []
    assert report.warnings == []


def test_bad_inputs_populate_critical_flags_and_warnings() -> None:
    unstable_effect = CovariateEffect(
        covariate="weight_kg",
        parameter_affected="CL",
        effect_form="allometric_exponent",
        effect_estimate=0.10,
        confidence_interval=(0.05, 0.50),
        clinically_material=True,
        interpretation="Synthetic unstable effect.",
    )
    failed_exposure = ExposureResponseResult(
        endpoint="grade2plus_adverse_event",
        endpoint_type="safety",
        model_form="logistic_univariate",
        exposure_metric="AUC_0_inf",
        converged=False,
        n_patients=20,
        n_events=5,
        diagnostic_flags=["Synthetic separation warning"],
        key_finding="Synthetic failed result.",
    )

    report = summarize_diagnostics(
        _comparison(converged=False),
        _patient_pk(converged=False),
        [unstable_effect],
        [failed_exposure],
        _observed_concentrations(scale=2.0),
    )

    assert report.pk_model_converged is False
    assert report.predictive_check_passed is False
    assert report.major_residual_bias is True
    assert len(report.critical_flags) == 3
    assert any("wide/unstable" in warning for warning in report.warnings)
    assert any("separation" in warning for warning in report.warnings)


def test_misaligned_observed_schedule_raises_clear_error() -> None:
    misaligned_observations = _observed_concentrations()
    misaligned_observations.loc[0, "time_hours"] = 0.3

    with pytest.raises(ValueError, match="nominal timepoints"):
        summarize_diagnostics(
            _comparison(converged=True),
            _patient_pk(converged=True),
            [],
            [],
            misaligned_observations,
        )
