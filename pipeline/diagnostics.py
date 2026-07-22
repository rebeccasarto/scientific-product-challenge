"""Aggregate minimal diagnostics from existing PK and exposure-response results."""

import sys
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.schemas import (
    CovariateEffect,
    DiagnosticsSummary,
    ExposureResponseResult,
    PKCandidateResult,
    PKModelComparison,
)
from pipeline.covariates import screen_covariates
from pipeline.data_loading import load_all
from pipeline.exposure_response import fit_exposure_response
from pipeline.pk import (
    fit_population_pk,
    micro_to_hybrid_constants,
    one_compartment_concentration,
    two_compartment_concentration,
)


def _selected_candidate(
    pk_comparison: PKModelComparison,
) -> Optional[PKCandidateResult]:
    return next(
        (
            candidate
            for candidate in pk_comparison.candidates
            if candidate.model_type == pk_comparison.selected_model
        ),
        None,
    )


def _parameter_bounds_valid(candidate: Optional[PKCandidateResult]) -> bool:
    if candidate is None or not candidate.parameters:
        return False
    return all(
        parameter.ci_lower is not None
        and parameter.ci_upper is not None
        and np.isfinite(parameter.ci_lower)
        and np.isfinite(parameter.ci_upper)
        for parameter in candidate.parameters.values()
    )


def _patient_level_aggregate_predictive_check(
    pk_comparison: PKModelComparison,
    per_patient_pk: pd.DataFrame,
    observed_concentrations: pd.DataFrame,
) -> bool:
    """Run a simplified in-sample check using fitted individual PK parameters.

    This is not a simulated VPC and does not incorporate residual variability.
    Each converged patient's model is explicitly re-evaluated at the nominal
    schedule before patient-level predictions are aggregated by their median.
    """
    nominal_times = np.asarray([0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0])
    for patient_id, patient_rows in observed_concentrations.groupby("patient_id"):
        patient_times = np.sort(
            patient_rows["time_hours"].to_numpy(dtype=float)
        )
        if not np.array_equal(patient_times, nominal_times):
            raise ValueError(
                "Observed PK schedule is not aligned to the nominal timepoints "
                f"for patient_id {patient_id}: observed={patient_times.tolist()}, "
                f"expected={nominal_times.tolist()}"
            )

    observed_medians = (
        observed_concentrations.groupby("time_hours", as_index=False)[
            "concentration_mg_l"
        ]
        .median()
        .sort_values("time_hours")
    )
    median_times = observed_medians["time_hours"].to_numpy(dtype=float)
    if not np.array_equal(median_times, nominal_times):
        raise ValueError(
            "Observed median concentration timepoints do not match the nominal schedule: "
            f"observed={median_times.tolist()}, expected={nominal_times.tolist()}"
        )
    observed = observed_medians["concentration_mg_l"].to_numpy(dtype=float)

    selected_rows = per_patient_pk.loc[
        (per_patient_pk["model_type"] == pk_comparison.selected_model)
        & per_patient_pk["converged"]
    ]
    if selected_rows.empty:
        return False

    patient_predictions: List[np.ndarray] = []
    for _, patient_fit in selected_rows.iterrows():
        dose_mg = float(patient_fit["dose_mg"])
        if pk_comparison.selected_model == "1-compartment":
            predicted = one_compartment_concentration(
                nominal_times,
                float(patient_fit["CL"]),
                float(patient_fit["V"]),
                dose_mg,
            )
        elif pk_comparison.selected_model == "2-compartment":
            hybrid = micro_to_hybrid_constants(
                dose_mg,
                float(patient_fit["CL"]),
                float(patient_fit["V1"]),
                float(patient_fit["Q"]),
                float(patient_fit["V2"]),
            )
            predicted = two_compartment_concentration(
                nominal_times,
                hybrid["A"],
                hybrid["B"],
                hybrid["alpha"],
                hybrid["beta"],
            )
        else:
            return False
        if not np.all(np.isfinite(predicted)) or np.any(predicted <= 0):
            return False
        patient_predictions.append(predicted)

    median_predicted = np.median(np.vstack(patient_predictions), axis=0)
    if not np.all(np.isfinite(observed)) or np.any(observed <= 0):
        return False
    predicted_to_observed_ratios = median_predicted / observed
    return bool(
        np.all(
            (predicted_to_observed_ratios >= 0.80)
            & (predicted_to_observed_ratios <= 1.20)
        )
    )


def summarize_diagnostics(
    pk_comparison: PKModelComparison,
    per_patient_pk: pd.DataFrame,
    covariate_effects: List[CovariateEffect],
    exposure_response_results: List[ExposureResponseResult],
    observed_concentrations: pd.DataFrame,
) -> DiagnosticsSummary:
    """Summarize existing convergence, interval, and median-profile evidence."""
    selected_candidate = _selected_candidate(pk_comparison)
    pk_model_converged = bool(
        selected_candidate is not None and selected_candidate.converged
    )
    parameter_covariance_valid = _parameter_bounds_valid(selected_candidate)
    predictive_check_passed = _patient_level_aggregate_predictive_check(
        pk_comparison,
        per_patient_pk,
        observed_concentrations,
    )
    major_residual_bias = not predictive_check_passed

    critical_flags: List[str] = []
    if not pk_model_converged:
        critical_flags.append("Selected PK model did not meet the 80% convergence threshold")
    if not predictive_check_passed:
        critical_flags.append(
            "Patient-level aggregate median predictions were not within 20% of "
            "observed medians at every scheduled timepoint"
        )
    for result in exposure_response_results:
        if not result.converged:
            critical_flags.append(
                f"Exposure-response model did not converge: "
                f"{result.endpoint} ({result.model_form})"
            )

    diagnostic_warnings: List[str] = []
    for effect in covariate_effects:
        if not effect.clinically_material:
            continue
        confidence_interval = effect.confidence_interval
        if confidence_interval is None:
            diagnostic_warnings.append(
                f"Clinically material covariate effect lacks a confidence interval: "
                f"{effect.covariate} on {effect.parameter_affected}"
            )
            continue
        interval_width = confidence_interval[1] - confidence_interval[0]
        instability_scale = 3.0 * abs(effect.effect_estimate)
        if not np.isfinite(interval_width) or interval_width > instability_scale:
            diagnostic_warnings.append(
                f"Clinically material covariate effect has a wide/unstable interval: "
                f"{effect.covariate} on {effect.parameter_affected}"
            )
    for result in exposure_response_results:
        for flag in result.diagnostic_flags:
            diagnostic_warnings.append(
                f"Exposure-response diagnostic for {result.endpoint} "
                f"({result.model_form}): {flag}"
            )

    selected_rows = per_patient_pk.loc[
        per_patient_pk["model_type"] == pk_comparison.selected_model
    ]
    convergence_percent = (
        100.0 * float(selected_rows["converged"].mean())
        if not selected_rows.empty
        else 0.0
    )
    material_count = sum(effect.clinically_material for effect in covariate_effects)
    exposure_all_converged = all(
        result.converged for result in exposure_response_results
    )
    exposure_status = (
        "converged for all fitted models"
        if exposure_all_converged
        else "showed convergence issues in one or more fitted models"
    )
    predictive_status = "passed" if predictive_check_passed else "failed"
    summary = (
        f"The selected {pk_comparison.selected_model} model converged for "
        f"{convergence_percent:.1f}% of patients and {predictive_status} the "
        "simplified in-sample patient-level aggregate predictive check based on "
        "fitted individual parameters (not a simulated VPC). "
        f"{material_count} of {len(covariate_effects)} tested covariate effects "
        f"were clinically material. Exposure-response models {exposure_status}."
    )
    return DiagnosticsSummary(
        pk_model_converged=pk_model_converged,
        parameter_covariance_valid=parameter_covariance_valid,
        predictive_check_passed=predictive_check_passed,
        major_residual_bias=major_residual_bias,
        critical_flags=critical_flags,
        warnings=diagnostic_warnings,
        summary=summary,
    )


if __name__ == "__main__":
    loaded_data = load_all()
    comparison, patient_pk = fit_population_pk(loaded_data)
    if comparison.selected_model is None:
        raise RuntimeError("PK model selection did not produce a structural model")
    effects = screen_covariates(
        patient_pk,
        loaded_data["patients"],
        comparison.selected_model,
    )
    exposure_results = fit_exposure_response(
        loaded_data,
        patient_pk,
        comparison.selected_model,
    )
    diagnostics = summarize_diagnostics(
        comparison,
        patient_pk,
        effects,
        exposure_results,
        loaded_data["pk_concentrations"],
    )
    print(diagnostics)
