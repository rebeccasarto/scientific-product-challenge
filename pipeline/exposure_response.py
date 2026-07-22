"""Fit exploratory efficacy and safety exposure-response models."""

import sys
import warnings
from math import exp
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import minimize
from scipy.special import expit
from statsmodels.tools.sm_exceptions import (
    ConvergenceWarning,
    PerfectSeparationError,
    PerfectSeparationWarning,
)


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.schemas import ExposureResponseResult
from pipeline.data_loading import LoadedData, load_all
from pipeline.endpoints import derive_endpoints
from pipeline.pk import fit_population_pk


def compute_exposure(
    per_patient_pk: pd.DataFrame,
    selected_model: str,
) -> pd.DataFrame:
    """Compute individual AUC from metadata-derived dose and selected-model CL."""
    selected_fits = per_patient_pk.loc[
        (per_patient_pk["model_type"] == selected_model)
        & per_patient_pk["converged"]
    ].copy()
    if "dose_mg" in selected_fits.columns:
        dose_values = selected_fits["dose_mg"].dropna().unique()
        if len(dose_values) != 1:
            raise ValueError(
                "Per-patient PK results must contain one metadata-derived dose_mg value"
            )
        dose_mg = float(dose_values[0])
    elif "dose_mg" in per_patient_pk.attrs:
        dose_mg = float(per_patient_pk.attrs["dose_mg"])
    else:
        raise ValueError(
            "Per-patient PK results are missing metadata-derived dose_mg provenance"
        )

    clearance = pd.to_numeric(selected_fits["CL"], errors="coerce")
    if clearance.isna().any() or (clearance <= 0).any():
        raise ValueError("AUC computation requires positive finite CL estimates")
    return pd.DataFrame(
        {
            "patient_id": selected_fits["patient_id"].astype("string"),
            "auc_mg_h_per_l": dose_mg / clearance,
        }
    ).reset_index(drop=True)


def _ridge_logistic_fallback(
    design_matrix: np.ndarray,
    outcome: np.ndarray,
    penalty: float = 0.1,
) -> Tuple[np.ndarray, np.ndarray, bool]:
    """Fit weak ridge logistic regression and return approximate covariance."""
    penalty_weights = np.ones(design_matrix.shape[1], dtype=float)
    penalty_weights[0] = 0.0

    def objective(coefficients: np.ndarray) -> float:
        linear_predictor = design_matrix @ coefficients
        log_likelihood = np.sum(
            outcome * np.logaddexp(0.0, -linear_predictor)
            + (1.0 - outcome) * np.logaddexp(0.0, linear_predictor)
        )
        return float(
            log_likelihood
            + 0.5
            * penalty
            * np.sum(penalty_weights * np.square(coefficients))
        )

    def gradient(coefficients: np.ndarray) -> np.ndarray:
        probabilities = expit(design_matrix @ coefficients)
        return (
            design_matrix.T @ (probabilities - outcome)
            + penalty * penalty_weights * coefficients
        )

    fit = minimize(
        objective,
        x0=np.zeros(design_matrix.shape[1], dtype=float),
        jac=gradient,
        method="BFGS",
    )
    probabilities = expit(design_matrix @ fit.x)
    information = design_matrix.T @ (
        design_matrix * (probabilities * (1.0 - probabilities))[:, None]
    )
    information += penalty * np.diag(penalty_weights)
    covariance = np.linalg.pinv(information)
    return fit.x, covariance, bool(fit.success)


def _safe_exp(value: float) -> float:
    return float(exp(float(np.clip(value, -700.0, 700.0))))


def _fit_logistic_result(
    analysis_data: pd.DataFrame,
    endpoint: str,
    endpoint_type: str,
    weight_adjusted: bool,
) -> ExposureResponseResult:
    required_columns = [endpoint, "auc_mg_h_per_l"]
    if weight_adjusted:
        required_columns.append("weight_kg")
    model_data = analysis_data[required_columns].dropna().copy()
    outcome = model_data[endpoint].to_numpy(dtype=float)
    auc_values = model_data["auc_mg_h_per_l"].to_numpy(dtype=float)
    auc_sd = float(np.std(auc_values, ddof=1))
    if len(model_data) < 3 or not np.isfinite(auc_sd) or auc_sd <= 0:
        return ExposureResponseResult(
            endpoint=endpoint,
            endpoint_type=endpoint_type,
            model_form=(
                "logistic_weight_adjusted"
                if weight_adjusted
                else "logistic_univariate"
            ),
            exposure_metric="AUC_0_inf",
            converged=False,
            n_patients=len(model_data),
            n_events=int(outcome.sum()),
            diagnostic_flags=["Insufficient AUC variation for logistic regression"],
            key_finding="Exposure-response association could not be estimated reliably.",
        )

    design_columns = [
        np.ones(len(model_data), dtype=float),
        (auc_values - float(np.mean(auc_values))) / auc_sd,
    ]
    if weight_adjusted:
        weight_values = model_data["weight_kg"].to_numpy(dtype=float)
        weight_sd = float(np.std(weight_values, ddof=1))
        design_columns.append(
            (weight_values - float(np.mean(weight_values))) / weight_sd
        )
    design_matrix = np.column_stack(design_columns)

    diagnostic_flags: List[str] = []
    coefficients: Optional[np.ndarray] = None
    covariance: Optional[np.ndarray] = None
    converged = False
    try:
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            fit = sm.Logit(outcome, design_matrix).fit(disp=False, maxiter=200)
        coefficients = np.asarray(fit.params, dtype=float)
        covariance = np.asarray(fit.cov_params(), dtype=float)
        converged = bool(fit.mle_retvals.get("converged", False))
        convergence_warning_detected = any(
            issubclass(warning.category, ConvergenceWarning)
            for warning in caught_warnings
        )
        separation_warning_detected = any(
            issubclass(warning.category, PerfectSeparationWarning)
            for warning in caught_warnings
        )
        if not converged or convergence_warning_detected:
            diagnostic_flags.append(
                "Logistic convergence warning; possible perfect/quasi-separation"
            )
        if separation_warning_detected:
            diagnostic_flags.append(
                "Perfect/quasi-separation detected; weak ridge-penalized fallback used"
            )
            converged = False
    except (PerfectSeparationError, np.linalg.LinAlgError, ValueError) as exc:
        diagnostic_flags.append(
            "Perfect/quasi-separation detected; weak ridge-penalized fallback "
            f"used ({exc})"
        )

    if coefficients is None or covariance is None or not converged:
        coefficients, covariance, converged = _ridge_logistic_fallback(
            design_matrix,
            outcome,
        )
        if not any("separation" in flag for flag in diagnostic_flags):
            diagnostic_flags.append(
                "Weak ridge-penalized fallback used after logistic non-convergence"
            )

    coefficient_per_sd = float(coefficients[1])
    standard_error_per_sd = float(np.sqrt(max(covariance[1, 1], 0.0)))
    lower_per_sd = coefficient_per_sd - (1.96 * standard_error_per_sd)
    upper_per_sd = coefficient_per_sd + (1.96 * standard_error_per_sd)
    if standard_error_per_sd > 10 or not np.isfinite(standard_error_per_sd):
        diagnostic_flags.append(
            "Extreme AUC coefficient standard error; possible quasi-separation"
        )

    effect_estimate = coefficient_per_sd / auc_sd
    ci_lower = lower_per_sd / auc_sd
    ci_upper = upper_per_sd / auc_sd
    odds_ratio = _safe_exp(coefficient_per_sd)
    odds_ratio_lower = _safe_exp(lower_per_sd)
    odds_ratio_upper = _safe_exp(upper_per_sd)
    direction = "higher" if coefficient_per_sd >= 0 else "lower"
    endpoint_label = (
        "clinical response"
        if endpoint == "clinical_response"
        else "grade>=2 adverse events"
    )
    key_finding = (
        f"Higher exposure is associated with {direction} odds of {endpoint_label} "
        f"(OR={odds_ratio:.2f} per SD increase in AUC, 95% CI "
        f"[{odds_ratio_lower:.2f}, {odds_ratio_upper:.2f}]); this is an "
        "exploratory association, not a causal or dose-adjustment-ready "
        "conclusion on its own."
    )
    return ExposureResponseResult(
        endpoint=endpoint,
        endpoint_type=endpoint_type,
        model_form=(
            "logistic_weight_adjusted"
            if weight_adjusted
            else "logistic_univariate"
        ),
        exposure_metric="AUC_0_inf",
        converged=converged,
        n_patients=len(model_data),
        n_events=int(outcome.sum()),
        effect_estimate=effect_estimate,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        diagnostic_flags=diagnostic_flags,
        key_finding=key_finding,
    )


def fit_exposure_response(
    loaded: LoadedData,
    per_patient_pk: pd.DataFrame,
    selected_model: str,
) -> List[ExposureResponseResult]:
    """Fit four prespecified exploratory logistic exposure-response models."""
    exposure = compute_exposure(per_patient_pk, selected_model)
    endpoints = derive_endpoints(loaded)
    analysis_data = endpoints.merge(
        exposure,
        on="patient_id",
        how="inner",
        validate="one_to_one",
    )
    return [
        _fit_logistic_result(
            analysis_data,
            "clinical_response",
            "efficacy",
            weight_adjusted=False,
        ),
        _fit_logistic_result(
            analysis_data,
            "clinical_response",
            "efficacy",
            weight_adjusted=True,
        ),
        _fit_logistic_result(
            analysis_data,
            "grade2plus_adverse_event",
            "safety",
            weight_adjusted=False,
        ),
        _fit_logistic_result(
            analysis_data,
            "grade2plus_adverse_event",
            "safety",
            weight_adjusted=True,
        ),
    ]


if __name__ == "__main__":
    loaded_data = load_all()
    comparison, patient_pk = fit_population_pk(loaded_data)
    if comparison.selected_model is None:
        raise RuntimeError("PK model selection did not produce a structural model")
    results = fit_exposure_response(
        loaded_data,
        patient_pk,
        comparison.selected_model,
    )
    for result in results:
        print(result)
