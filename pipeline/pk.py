"""Fit and compare cohort-wide one- and two-compartment PK structures."""

import sys
from math import log, sqrt
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import least_squares


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.schemas import ParameterEstimate, PKCandidateResult, PKModelComparison
from pipeline.data_loading import LoadedData, load_all


ArrayModel = Callable[..., np.ndarray]


def one_compartment_concentration(
    time_hours: np.ndarray,
    cl: float,
    volume: float,
    dose_mg: float,
) -> np.ndarray:
    """Evaluate the IV-bolus one-compartment concentration model."""
    return (dose_mg / volume) * np.exp(-(cl / volume) * time_hours)


def two_compartment_concentration(
    time_hours: np.ndarray,
    a_coefficient: float,
    b_coefficient: float,
    alpha: float,
    beta: float,
) -> np.ndarray:
    """Evaluate a biexponential IV-bolus concentration model."""
    return a_coefficient * np.exp(-alpha * time_hours) + b_coefficient * np.exp(
        -beta * time_hours
    )


def calculate_aicc(n_observations: int, n_parameters: int, rss: float) -> float:
    """Calculate Gaussian least-squares AICc from residual sum of squares."""
    if n_observations <= n_parameters + 1:
        raise ValueError(
            "AICc requires n_observations > n_parameters + 1; "
            f"received n={n_observations}, k={n_parameters}"
        )
    if not np.isfinite(rss) or rss < 0:
        raise ValueError(f"RSS must be finite and non-negative; received {rss}")

    stable_rss = max(float(rss), np.finfo(float).tiny)
    aic = n_observations * log(stable_rss / n_observations) + 2 * n_parameters
    correction = (2 * n_parameters * (n_parameters + 1)) / (
        n_observations - n_parameters - 1
    )
    return float(aic + correction)


def hybrid_to_micro_constants(
    dose_mg: float,
    a_coefficient: float,
    b_coefficient: float,
    alpha: float,
    beta: float,
) -> Dict[str, float]:
    """Convert biexponential hybrid constants to CL, V1, Q, and V2."""
    values = np.asarray(
        [dose_mg, a_coefficient, b_coefficient, alpha, beta], dtype=float
    )
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("Dose and biexponential parameters must be positive and finite")

    if alpha < beta:
        a_coefficient, b_coefficient = b_coefficient, a_coefficient
        alpha, beta = beta, alpha

    coefficient_sum = a_coefficient + b_coefficient
    volume_1 = dose_mg / coefficient_sum
    # Standard IV-bolus two-compartment hybrid-to-micro constant conversions.
    k21 = (
        (a_coefficient / coefficient_sum) * beta
        + (b_coefficient / coefficient_sum) * alpha
    )
    k10 = (alpha * beta) / k21
    k12 = alpha + beta - k10 - k21
    clearance = k10 * volume_1
    intercompartmental_clearance = k12 * volume_1
    volume_2 = intercompartmental_clearance / k21

    converted = {
        "CL": clearance,
        "V1": volume_1,
        "Q": intercompartmental_clearance,
        "V2": volume_2,
        "k10": k10,
        "k12": k12,
        "k21": k21,
    }
    if not np.all(np.isfinite(list(converted.values()))) or any(
        value <= 0 for value in converted.values()
    ):
        raise ValueError(
            "Biexponential parameters imply non-positive or non-finite "
            "two-compartment micro-parameters"
        )
    return converted


def micro_to_hybrid_constants(
    dose_mg: float,
    clearance: float,
    volume_1: float,
    intercompartmental_clearance: float,
    volume_2: float,
) -> Dict[str, float]:
    """Convert CL, V1, Q, and V2 to biexponential hybrid constants."""
    k10 = clearance / volume_1
    k12 = intercompartmental_clearance / volume_1
    k21 = intercompartmental_clearance / volume_2
    hybrid_sum = k10 + k12 + k21
    discriminant = hybrid_sum**2 - (4 * k10 * k21)
    if discriminant <= 0:
        raise ValueError("Micro-parameters do not produce two distinct hybrid rates")
    alpha = 0.5 * (hybrid_sum + sqrt(discriminant))
    beta = 0.5 * (hybrid_sum - sqrt(discriminant))
    initial_concentration = dose_mg / volume_1
    a_coefficient = initial_concentration * (alpha - k21) / (alpha - beta)
    b_coefficient = initial_concentration - a_coefficient
    return {
        "A": a_coefficient,
        "B": b_coefficient,
        "alpha": alpha,
        "beta": beta,
    }


def are_hybrid_rates_separable(alpha: float, beta: float) -> bool:
    """Return whether alpha and beta differ by more than 5% of the larger rate."""
    if not np.isfinite(alpha) or not np.isfinite(beta) or alpha <= 0 or beta <= 0:
        return False
    return abs(alpha - beta) / max(alpha, beta) > 0.05


def _log_residual_fit(
    model: ArrayModel,
    times: np.ndarray,
    concentrations: np.ndarray,
    initial_values: Sequence[float],
) -> Tuple[np.ndarray, float, np.ndarray]:
    if not np.all(np.isfinite(concentrations)) or np.any(concentrations <= 0):
        raise ValueError("Log-residual fitting requires positive finite concentrations")

    lower_bounds = np.full(len(initial_values), 1e-10, dtype=float)
    upper_bounds = np.full(len(initial_values), np.inf, dtype=float)
    log_observed = np.log(concentrations)

    def residuals(parameters: np.ndarray) -> np.ndarray:
        predictions = model(times, *parameters)
        stable_predictions = np.maximum(predictions, np.finfo(float).tiny)
        return log_observed - np.log(stable_predictions)

    fit = least_squares(
        residuals,
        x0=np.asarray(initial_values, dtype=float),
        bounds=(lower_bounds, upper_bounds),
        max_nfev=50000,
    )
    if not fit.success:
        raise RuntimeError(f"Log-residual fit failed to converge: {fit.message}")
    predictions = model(times, *fit.x)
    if not np.all(np.isfinite(predictions)) or np.any(predictions <= 0):
        raise ValueError("Fit produced non-positive or non-finite predictions")
    log_rss = float(np.sum(np.square(residuals(fit.x))))
    return fit.x, log_rss, predictions


def fit_one_compartment_patient(
    times: np.ndarray,
    concentrations: np.ndarray,
    dose_mg: float,
) -> Dict[str, Any]:
    """Fit a one-compartment model for one patient."""
    result: Dict[str, Any] = {
        "model_type": "1-compartment",
        "converged": False,
        "CL": np.nan,
        "V": np.nan,
        "V1": np.nan,
        "Q": np.nan,
        "V2": np.nan,
        "aicc": np.nan,
        "diagnostic_flags": [],
        "failure_reason": None,
        "predicted_concentrations": [],
    }
    try:
        positive = concentrations > 0
        if int(positive.sum()) < 2:
            raise ValueError("At least two positive concentrations are required")
        slope, intercept = np.polyfit(
            times[positive], np.log(concentrations[positive]), deg=1
        )
        elimination_rate = max(float(-slope), 1e-3)
        initial_volume = max(float(dose_mg / np.exp(intercept)), 1e-3)
        initial_clearance = max(elimination_rate * initial_volume, 1e-3)
        model = lambda time, cl, volume: one_compartment_concentration(
            time, cl, volume, dose_mg
        )
        parameters, log_rss, predictions = _log_residual_fit(
            model,
            times,
            concentrations,
            (initial_clearance, initial_volume),
        )
        clearance, volume = (float(value) for value in parameters)
        if not np.all(np.isfinite(parameters)) or np.any(parameters <= 0):
            raise ValueError("One-compartment fit produced implausible parameters")
        result.update(
            {
                "converged": True,
                "CL": clearance,
                "V": volume,
                "aicc": calculate_aicc(len(times), 2, log_rss),
                "predicted_concentrations": predictions.tolist(),
            }
        )
    except (RuntimeError, ValueError, FloatingPointError) as exc:
        result["failure_reason"] = str(exc)
        result["diagnostic_flags"] = [str(exc)]
    return result


def fit_two_compartment_patient(
    times: np.ndarray,
    concentrations: np.ndarray,
    dose_mg: float,
) -> Dict[str, Any]:
    """Fit a two-compartment biexponential model for one patient."""
    result: Dict[str, Any] = {
        "model_type": "2-compartment",
        "converged": False,
        "CL": np.nan,
        "V": np.nan,
        "V1": np.nan,
        "Q": np.nan,
        "V2": np.nan,
        "A": np.nan,
        "B": np.nan,
        "alpha": np.nan,
        "beta": np.nan,
        "aicc": np.nan,
        "diagnostic_flags": [],
        "failure_reason": None,
        "predicted_concentrations": [],
    }
    try:
        if len(times) <= 5:
            raise ValueError("Two-compartment fitting requires at least 6 observations")
        concentration_scale = max(float(np.max(concentrations)), 1e-3)
        initial_guesses = (
            (0.7 * concentration_scale, 0.3 * concentration_scale, 1.0, 0.05),
            (0.5 * concentration_scale, 0.5 * concentration_scale, 0.5, 0.03),
            (0.8 * concentration_scale, 0.2 * concentration_scale, 2.0, 0.1),
            (0.3 * concentration_scale, 0.7 * concentration_scale, 0.2, 0.02),
        )
        successful_fits: List[
            Tuple[np.ndarray, float, np.ndarray, Dict[str, float]]
        ] = []
        failure_messages: List[str] = []
        for initial_values in initial_guesses:
            try:
                parameters, log_rss, predictions = _log_residual_fit(
                    two_compartment_concentration,
                    times,
                    concentrations,
                    initial_values,
                )
                a_coefficient, b_coefficient, alpha, beta = (
                    float(value) for value in parameters
                )
                if alpha < beta:
                    a_coefficient, b_coefficient = b_coefficient, a_coefficient
                    alpha, beta = beta, alpha
                if not are_hybrid_rates_separable(alpha, beta):
                    raise ValueError(
                        "Two-compartment alpha and beta are not separated by more than 5%"
                    )
                canonical_parameters = np.asarray(
                    [a_coefficient, b_coefficient, alpha, beta], dtype=float
                )
                converted = hybrid_to_micro_constants(
                    dose_mg,
                    a_coefficient,
                    b_coefficient,
                    alpha,
                    beta,
                )
                successful_fits.append(
                    (
                        canonical_parameters,
                        log_rss,
                        predictions,
                        converted,
                    )
                )
            except (RuntimeError, ValueError) as exc:
                failure_messages.append(str(exc))
        if not successful_fits:
            raise RuntimeError(
                "All two-compartment initializations failed: "
                + "; ".join(failure_messages)
            )

        successful_fits.sort(key=lambda fit: fit[1])
        parameters, log_rss, predictions, converted = successful_fits[0]
        a_coefficient, b_coefficient, alpha, beta = (
            float(value) for value in parameters
        )
        diagnostic_flags: List[str] = []
        if len(successful_fits) > 1:
            _, second_log_rss, _, second_converted = successful_fits[1]
            similar_rss = second_log_rss <= (log_rss * 1.10) + 1e-12
            unstable_parameters = [
                parameter_name
                for parameter_name in ("CL", "V1", "Q", "V2")
                if abs(second_converted[parameter_name] - converted[parameter_name])
                / max(abs(converted[parameter_name]), np.finfo(float).tiny)
                > 0.20
            ]
            if similar_rss and unstable_parameters:
                diagnostic_flags.append(
                    "Potential multistart parameter instability: similar log-RSS "
                    "solutions differed by >20% for "
                    + ", ".join(unstable_parameters)
                )
        result.update(
            {
                "converged": True,
                "CL": converted["CL"],
                "V1": converted["V1"],
                "Q": converted["Q"],
                "V2": converted["V2"],
                "A": a_coefficient,
                "B": b_coefficient,
                "alpha": alpha,
                "beta": beta,
                "aicc": calculate_aicc(len(times), 4, log_rss),
                "diagnostic_flags": diagnostic_flags,
                "predicted_concentrations": predictions.tolist(),
            }
        )
    except (RuntimeError, ValueError, FloatingPointError) as exc:
        result["failure_reason"] = str(exc)
        result["diagnostic_flags"] = [str(exc)]
    return result


def prefers_two_compartment(
    one_compartment_fit: Dict[str, Any],
    two_compartment_fit: Dict[str, Any],
) -> bool:
    """Apply the prespecified convergence, identifiability, and delta-AICc rule."""
    return bool(
        one_compartment_fit["converged"]
        and two_compartment_fit["converged"]
        and are_hybrid_rates_separable(
            float(two_compartment_fit["alpha"]),
            float(two_compartment_fit["beta"]),
        )
        and float(one_compartment_fit["aicc"])
        - float(two_compartment_fit["aicc"])
        > 4.0
    )


def _population_parameter_summary(
    model_rows: pd.DataFrame,
    parameter_names: Sequence[str],
) -> Tuple[Dict[str, ParameterEstimate], List[str]]:
    """Summarize between-patient distributions by median and IQR bounds."""
    units = {"CL": "L/h", "V": "L", "V1": "L", "Q": "L/h", "V2": "L"}
    estimates: Dict[str, ParameterEstimate] = {}
    flags: List[str] = []
    for parameter_name in parameter_names:
        values = pd.to_numeric(model_rows[parameter_name], errors="coerce").dropna()
        if values.empty:
            continue
        median_value = float(values.median())
        lower_quartile = float(values.quantile(0.25))
        upper_quartile = float(values.quantile(0.75))
        estimates[parameter_name] = ParameterEstimate(
            estimate=median_value,
            standard_error=None,
            ci_lower=lower_quartile,
            ci_upper=upper_quartile,
            unit=units[parameter_name],
        )
        flags.append(
            f"Population {parameter_name} from {len(values)} usable converged "
            f"fits: median={median_value:.4g}, IQR=[{lower_quartile:.4g}, "
            f"{upper_quartile:.4g}]; ci_lower/ci_upper store between-patient "
            "IQR bounds, not a confidence interval"
        )
    return estimates, flags


def _candidate_result(
    model_type: str,
    model_rows: pd.DataFrame,
    selected_model: str,
) -> PKCandidateResult:
    converged_rows = model_rows.loc[model_rows["converged"]]
    total = len(model_rows)
    converged_count = len(converged_rows)
    nonconvergence_percent = 100.0 * (total - converged_count) / total if total else 100.0
    flags = [
        f"{converged_count}/{total} patients converged ({100.0 - nonconvergence_percent:.1f}%)",
        f"{nonconvergence_percent:.1f}% of patients did not converge for {model_type} model",
    ]

    parameters: Dict[str, ParameterEstimate] = {}
    if model_type == selected_model and converged_count:
        parameter_names = (
            ("CL", "V")
            if model_type == "1-compartment"
            else ("CL", "V1", "Q", "V2")
        )
        parameters, parameter_flags = _population_parameter_summary(
            converged_rows, parameter_names
        )
        flags.extend(parameter_flags)

    return PKCandidateResult(
        model_type=model_type,
        converged=(converged_count / total >= 0.80) if total else False,
        parameters=parameters,
        aic=None,
        bic=None,
        diagnostic_flags=flags,
        failure_reason=(
            None
            if total and converged_count / total >= 0.80
            else (
                f"Fewer than 80% of patients converged for {model_type}: "
                f"{converged_count}/{total}"
            )
        ),
    )


def fit_population_pk(loaded: LoadedData) -> Tuple[PKModelComparison, pd.DataFrame]:
    """Fit both structures per patient and select one cohort-wide PK model."""
    pk_data = loaded["pk_concentrations"]
    fit_records: List[Dict[str, Any]] = []
    paired_fits: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    for patient_id, patient_rows in pk_data.groupby("patient_id", sort=True):
        ordered_rows = patient_rows.sort_values("time_hours")
        times = ordered_rows["time_hours"].to_numpy(dtype=float)
        concentrations = ordered_rows["concentration_mg_l"].to_numpy(dtype=float)
        dose_mg = float(ordered_rows["dose_mg"].iloc[0])
        one_fit = fit_one_compartment_patient(times, concentrations, dose_mg)
        two_fit = fit_two_compartment_patient(times, concentrations, dose_mg)
        for fit in (one_fit, two_fit):
            fit["patient_id"] = str(patient_id)
            fit["dose_mg"] = float(loaded["metadata"]["dose_mg"])
            fit_records.append(fit)
        paired_fits.append((one_fit, two_fit))

    both_converged = [
        (one_fit, two_fit)
        for one_fit, two_fit in paired_fits
        if one_fit["converged"] and two_fit["converged"]
    ]
    two_support_count = sum(
        prefers_two_compartment(one_fit, two_fit)
        for one_fit, two_fit in both_converged
    )
    comparison_count = len(both_converged)
    no_clear_two_support_count = comparison_count - two_support_count
    two_support_percent = (
        100.0 * two_support_count / comparison_count if comparison_count else 0.0
    )
    no_clear_two_support_percent = (
        100.0 * no_clear_two_support_count / comparison_count
        if comparison_count
        else 0.0
    )
    selected_model = (
        "2-compartment" if two_support_percent >= 65.0 else "1-compartment"
    )
    selection_rationale = (
        f"Among {comparison_count} patients with both models converged, "
        f"{two_support_count} ({two_support_percent:.1f}%) had 2-compartment "
        "AICc more than 4 points lower with separable alpha/beta; "
        f"{no_clear_two_support_count} ({no_clear_two_support_percent:.1f}%) "
        "had no clear two-compartment support. Selected "
        f"{selected_model} because at least 65% cohort support is required "
        "for the more complex structure; 1-compartment remains the default "
        "when that threshold is not reached."
    )

    paired_delta_aicc = np.asarray(
        [
            float(one_fit["aicc"]) - float(two_fit["aicc"])
            for one_fit, two_fit in both_converged
        ],
        dtype=float,
    )
    comparison_diagnostic_flags: List[str] = []
    if paired_delta_aicc.size:
        delta_median = float(np.median(paired_delta_aicc))
        delta_lower = float(np.quantile(paired_delta_aicc, 0.25))
        delta_upper = float(np.quantile(paired_delta_aicc, 0.75))
        delta_over_four_percent = float(np.mean(paired_delta_aicc > 4.0) * 100.0)
        comparison_diagnostic_flags.append(
            "Paired delta-AICc (1-compartment minus 2-compartment) among "
            f"{comparison_count} patients with both fits converged: "
            f"median={delta_median:.3f}, IQR=[{delta_lower:.3f}, "
            f"{delta_upper:.3f}], delta-AICc > 4 in "
            f"{delta_over_four_percent:.1f}%"
        )
    else:
        comparison_diagnostic_flags.append(
            "Paired delta-AICc unavailable because no patients had both models converge"
        )

    per_patient = pd.DataFrame.from_records(fit_records)
    output_columns = [
        "patient_id",
        "model_type",
        "converged",
        "CL",
        "V",
        "V1",
        "Q",
        "V2",
        "aicc",
        "diagnostic_flags",
        "predicted_concentrations",
        "dose_mg",
    ]
    per_patient_output = per_patient[output_columns].copy()
    per_patient_output.attrs["dose_mg"] = float(loaded["metadata"]["dose_mg"])
    candidates = [
        _candidate_result(
            model_type,
            per_patient.loc[per_patient["model_type"] == model_type],
            selected_model,
        )
        for model_type in ("1-compartment", "2-compartment")
    ]
    comparison = PKModelComparison(
        candidates=candidates,
        selected_model=selected_model,
        selection_rationale=selection_rationale,
        diagnostic_flags=comparison_diagnostic_flags,
    )
    return comparison, per_patient_output


if __name__ == "__main__":
    model_comparison, patient_parameters = fit_population_pk(load_all())
    print(f"selection_rationale: {model_comparison.selection_rationale}")
    for diagnostic_flag in model_comparison.diagnostic_flags:
        print(f"comparison diagnostic: {diagnostic_flag}")
    for candidate in model_comparison.candidates:
        model_rows = patient_parameters.loc[
            patient_parameters["model_type"] == candidate.model_type
        ]
        convergence_rate = 100.0 * float(model_rows["converged"].mean())
        print(f"{candidate.model_type} convergence rate: {convergence_rate:.1f}%")
    selected_rows = patient_parameters.loc[
        (patient_parameters["model_type"] == model_comparison.selected_model)
        & patient_parameters["converged"]
    ]
    selected_parameters = (
        ["CL", "V", "aicc"]
        if model_comparison.selected_model == "1-compartment"
        else ["CL", "V1", "Q", "V2", "aicc"]
    )
    print("selected-model per-patient parameter summary:")
    print(selected_rows[selected_parameters].describe())
