"""Generate conservative rule-based dosing recommendations from existing evidence."""

import sys
from math import exp
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.schemas import (
    CovariateEffect,
    DiagnosticsSummary,
    DosingRecommendation,
    ExposureResponseResult,
)
from pipeline.covariates import screen_covariates
from pipeline.data_loading import load_all
from pipeline.diagnostics import summarize_diagnostics
from pipeline.exposure_response import fit_exposure_response
from pipeline.pk import fit_population_pk


def _univariate_result(
    results: List[ExposureResponseResult],
    endpoint_type: str,
) -> Optional[ExposureResponseResult]:
    return next(
        (
            result
            for result in results
            if result.endpoint_type == endpoint_type
            and result.model_form == "logistic_univariate"
        ),
        None,
    )


def _positive_ci_excludes_zero(result: Optional[ExposureResponseResult]) -> bool:
    # Exposure-response estimates and CI bounds are log-odds coefficients; null=0, not 1.
    return bool(
        result is not None
        and result.converged
        and result.effect_estimate is not None
        and result.effect_estimate > 0
        and result.ci_lower is not None
        and result.ci_upper is not None
        and result.ci_lower > 0
    )


def _ci_includes_zero(result: Optional[ExposureResponseResult]) -> bool:
    return bool(
        result is not None
        and result.converged
        and result.ci_lower is not None
        and result.ci_upper is not None
        and result.ci_lower <= 0 <= result.ci_upper
    )


def _ci_text(result: Optional[ExposureResponseResult]) -> str:
    if result is None or result.ci_lower is None or result.ci_upper is None:
        return "unavailable"
    return f"[{result.ci_lower:.4g}, {result.ci_upper:.4g}]"


def _effect_percent(effect: CovariateEffect) -> float:
    reference = effect.reference_value
    comparison = effect.comparison_value
    if not isinstance(reference, (int, float)) or not isinstance(
        comparison, (int, float)
    ):
        return np.nan
    if effect.effect_form == "allometric_exponent":
        ratio = (float(comparison) / float(reference)) ** effect.effect_estimate
    elif effect.effect_form == "linear_coefficient_per_10_ml_min_on_log_scale":
        ratio = exp(
            effect.effect_estimate
            * (float(comparison) - float(reference))
            / 10.0
        )
    elif effect.effect_form == "log_scale_per_mutant_allele":
        ratio = exp(
            effect.effect_estimate * (float(comparison) - float(reference))
        )
    else:
        return np.nan
    return (ratio - 1.0) * 100.0


def _covariate_subgroup(covariate: str) -> str:
    labels = {
        "weight_kg": "patients in the upper weight quartile",
        "creatinine_clearance_ml_min": "patients across the creatinine clearance range",
        "genotype": "patients across mutant-allele count groups",
    }
    return labels.get(covariate, f"patients across {covariate} groups")


def generate_dosing_recommendations(
    covariate_effects: List[CovariateEffect],
    exposure_response_results: List[ExposureResponseResult],
    diagnostics: DiagnosticsSummary,
    reference_dose_mg: float = 100.0,
) -> List[DosingRecommendation]:
    """Apply prespecified evidence rules without simulating alternative doses."""
    efficacy = _univariate_result(exposure_response_results, "efficacy")
    safety = _univariate_result(exposure_response_results, "safety")
    efficacy_supported = _positive_ci_excludes_zero(efficacy)
    safety_positive_signal = _positive_ci_excludes_zero(safety)
    safety_not_significant = _ci_includes_zero(safety)

    base_validation = [
        "prospective dose-confirmation study",
        "population PK modeling with full NLME approach",
    ]
    if efficacy_supported and safety_not_significant:
        overall_action = "maintain_current_dose"
        overall_confidence = "moderate"
        overall_dose: Optional[float] = reference_dose_mg
        overall_rationale = (
            "Current exposure is supported by a positive univariate efficacy "
            f"log-odds CI {_ci_text(efficacy)}, while the univariate safety "
            f"log-odds CI {_ci_text(safety)} includes 0 and does not show a "
            "significant exposure-related safety signal."
        )
    elif efficacy_supported and safety_positive_signal:
        overall_action = "insufficient_evidence"
        overall_confidence = "low"
        overall_dose = None
        overall_rationale = (
            "Higher exposure is supported for efficacy, but both the efficacy "
            f"CI {_ci_text(efficacy)} and positive safety CI {_ci_text(safety)} "
            "exclude 0, creating an efficacy-safety tension that does not support "
            "a dose decision."
        )
    else:
        overall_action = "insufficient_evidence"
        overall_confidence = "low"
        overall_dose = None
        overall_rationale = (
            "The univariate efficacy exposure-response evidence does not provide "
            f"a positive CI excluding 0 (CI {_ci_text(efficacy)}), so the current "
            "analysis is insufficient for a population dose recommendation."
        )
        if safety_positive_signal:
            overall_rationale += (
                f" The positive safety CI {_ci_text(safety)} adds caution."
            )

    for flag in diagnostics.critical_flags:
        overall_rationale += f" Diagnostic context: {flag}"
        base_validation.append(flag)

    recommendations: List[DosingRecommendation] = [
        DosingRecommendation(
            subgroup="overall population",
            action=overall_action,
            recommended_dose_mg=overall_dose,
            reference_dose_mg=reference_dose_mg,
            evidence_basis="observed",
            rationale=overall_rationale,
            confidence=overall_confidence,
            validation_required=base_validation,
        )
    ]

    effects_by_covariate: Dict[str, List[CovariateEffect]] = {}
    for effect in covariate_effects:
        effects_by_covariate.setdefault(effect.covariate, []).append(effect)

    for covariate, effects in effects_by_covariate.items():
        clearance_effect = next(
            (effect for effect in effects if effect.parameter_affected == "CL"),
            None,
        )
        material_volume_effects = [
            effect
            for effect in effects
            if effect.parameter_affected in ("V", "V1")
            and effect.clinically_material
        ]
        subgroup = _covariate_subgroup(covariate)

        if clearance_effect is None:
            recommendations.append(
                DosingRecommendation(
                    subgroup=subgroup,
                    action="insufficient_evidence",
                    recommended_dose_mg=None,
                    reference_dose_mg=reference_dose_mg,
                    evidence_basis="unsupported",
                    rationale=(
                        f"No CL effect was available for {covariate}; a subgroup "
                        "dose recommendation cannot be supported."
                    ),
                    confidence="low",
                    validation_required=[
                        "confirmatory population PK covariate assessment"
                    ],
                )
            )
            continue

        clearance_percent = _effect_percent(clearance_effect)
        effect_description = (
            f"an estimated {abs(clearance_percent):.1f}% "
            f"{'increase' if clearance_percent >= 0 else 'decrease'} in CL "
            "across the evaluated covariate range"
            if np.isfinite(clearance_percent)
            else f"a CL coefficient of {clearance_effect.effect_estimate:.4g}"
        )
        volume_note = ""
        if material_volume_effects:
            volume_effect = material_volume_effects[0]
            volume_percent = _effect_percent(volume_effect)
            volume_note = (
                f" The {volume_effect.parameter_affected} effect was also "
                f"clinically material ({abs(volume_percent):.1f}% across the "
                "evaluated range)."
            )

        if clearance_effect.clinically_material:
            recommendations.append(
                DosingRecommendation(
                    subgroup=subgroup,
                    action="insufficient_evidence",
                    recommended_dose_mg=None,
                    reference_dose_mg=reference_dose_mg,
                    evidence_basis="observed",
                    rationale=(
                        f"The exploratory two-stage analysis found {effect_description}."
                        f"{volume_note} Translating this into a specific alternative "
                        "dose requires exposure-matching simulation, which was not "
                        "performed here."
                    ),
                    confidence="low",
                    validation_required=[
                        "exposure-matching simulation to confirm target AUC maintained "
                        "across the covariate's range"
                    ],
                )
            )
        else:
            recommendations.append(
                DosingRecommendation(
                    subgroup=subgroup,
                    action="no_subgroup_adjustment",
                    recommended_dose_mg=reference_dose_mg,
                    reference_dose_mg=reference_dose_mg,
                    evidence_basis="observed",
                    rationale=(
                        f"The exploratory two-stage analysis found {effect_description}, "
                        "which did not meet the prespecified statistical and >=20% "
                        "clinical-materiality criteria for a subgroup adjustment."
                        f"{volume_note}"
                    ),
                    confidence="moderate",
                    validation_required=[
                        "confirmatory population PK covariate assessment"
                    ],
                )
            )

    return recommendations


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
    dosing_recommendations = generate_dosing_recommendations(
        effects,
        exposure_results,
        diagnostics,
        reference_dose_mg=loaded_data["metadata"]["dose_mg"],
    )
    for recommendation in dosing_recommendations:
        print(recommendation)
