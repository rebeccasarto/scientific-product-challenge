"""Minimal FastAPI service over the latest validated analysis summary."""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, List, Optional

from fastapi import FastAPI, HTTPException

from agents.schemas import (
    AnalysisSummary,
    CovariateEffect,
    DosingRecommendation,
)
from api.models import (
    DoseRecommendationResponse,
    ModelSummaryResponse,
    PatientCovariates,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS_SUMMARY_PATH = (
    PROJECT_ROOT / "results" / "final" / "analysis_summary.json"
)
UNCERTAINTY_NOTE = (
    "This is a rule-based lookup against prespecified subgroup findings, not "
    "a live simulation."
)

_analysis_summary: Optional[AnalysisSummary] = None


def load_analysis_summary(path: Optional[str] = None) -> AnalysisSummary:
    """Read and validate an analysis summary from disk."""
    summary_path = Path(path) if path is not None else DEFAULT_ANALYSIS_SUMMARY_PATH
    if not summary_path.exists():
        raise RuntimeError(
            "Analysis summary not found at {}. Run run_pkpd_analysis.py first.".format(
                summary_path
            )
        )
    with summary_path.open("r", encoding="utf-8") as summary_file:
        payload = json.load(summary_file)
    if hasattr(AnalysisSummary, "model_validate"):
        return AnalysisSummary.model_validate(payload)
    return AnalysisSummary.parse_obj(payload)


def get_analysis_summary() -> Optional[AnalysisSummary]:
    """Return the currently loaded summary, if startup has supplied one."""
    return _analysis_summary


def set_analysis_summary(summary: Optional[AnalysisSummary]) -> None:
    """Set or clear the in-memory summary, primarily for startup and tests."""
    global _analysis_summary
    _analysis_summary = summary


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if get_analysis_summary() is None:
        set_analysis_summary(load_analysis_summary())
    yield


app = FastAPI(title="PK/PD Analysis API", lifespan=_lifespan)


def _require_analysis_summary() -> AnalysisSummary:
    summary = get_analysis_summary()
    if summary is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Analysis data is not loaded. Run run_pkpd_analysis.py before "
                "starting the API."
            ),
        )
    return summary


def _overall_recommendation(
    summary: AnalysisSummary,
) -> DosingRecommendation:
    for recommendation in summary.dosing_recommendations:
        if recommendation.subgroup.strip().casefold() == "overall population":
            return recommendation
    raise HTTPException(
        status_code=503,
        detail="The loaded analysis has no overall population recommendation.",
    )


def _weight_cl_effect(summary: AnalysisSummary) -> Optional[CovariateEffect]:
    for effect in summary.covariate_effects:
        if effect.covariate == "weight_kg" and effect.parameter_affected == "CL":
            return effect
    return None


def _weight_subgroup_recommendation(
    summary: AnalysisSummary,
) -> Optional[DosingRecommendation]:
    for recommendation in summary.dosing_recommendations:
        if "weight" in recommendation.subgroup.casefold():
            return recommendation
    return None


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@app.post("/recommend", response_model=DoseRecommendationResponse)
def recommend(covariates: PatientCovariates) -> DoseRecommendationResponse:
    """Return a prespecified rule-based recommendation lookup."""
    summary = _require_analysis_summary()
    overall = _overall_recommendation(summary)
    selected_recommendation = overall
    rationale_note = ""

    weight_effect = _weight_cl_effect(summary)
    numeric_bounds = (
        weight_effect is not None
        and _is_numeric(weight_effect.reference_value)
        and _is_numeric(weight_effect.comparison_value)
    )
    if weight_effect is not None and weight_effect.clinically_material:
        if numeric_bounds:
            comparison_value = float(weight_effect.comparison_value)
            if covariates.weight_kg >= comparison_value:
                subgroup_recommendation = _weight_subgroup_recommendation(summary)
                if subgroup_recommendation is not None:
                    selected_recommendation = subgroup_recommendation
                    rationale_note = (
                        " Patient weight ({:.1f} kg) is at or above the analyzed "
                        "upper-quartile boundary ({:.1f} kg), where weight was "
                        "identified as a clinically material covariate; no "
                        "specific alternative dose is asserted."
                    ).format(covariates.weight_kg, comparison_value)
            else:
                rationale_note = (
                    " Patient weight is below the analyzed upper-quartile "
                    "boundary, so the overall population recommendation is used."
                )
        else:
            rationale_note = (
                " Weight was a clinically material covariate in the analysis, "
                "but numeric subgroup bounds were unavailable; this patient was "
                "not classified into a weight subgroup."
            )
    elif weight_effect is None:
        rationale_note = (
            " The analysis did not provide numeric material-weight bounds for "
            "patient classification, so the overall recommendation is used."
        )

    return DoseRecommendationResponse(
        recommended_dose_mg=selected_recommendation.recommended_dose_mg,
        action=selected_recommendation.action,
        confidence=selected_recommendation.confidence,
        rationale=selected_recommendation.rationale + rationale_note,
        uncertainty_note=UNCERTAINTY_NOTE,
    )


@app.get("/model-summary", response_model=ModelSummaryResponse)
def model_summary() -> ModelSummaryResponse:
    """Return a compact summary of the selected PK model and findings."""
    summary = _require_analysis_summary()
    selected_model = summary.pk_model.selected_model
    if selected_model is None:
        raise HTTPException(
            status_code=503,
            detail="The loaded analysis has no selected PK model.",
        )

    selected_candidate = next(
        (
            candidate
            for candidate in summary.pk_model.candidates
            if candidate.model_type == selected_model
        ),
        None,
    )
    pk_parameters = {}
    if selected_candidate is not None:
        pk_parameters = {
            name: estimate.estimate
            for name, estimate in selected_candidate.parameters.items()
        }

    covariate_effects_summary = [
        {
            "covariate": effect.covariate,
            "parameter_affected": effect.parameter_affected,
            "clinically_material": effect.clinically_material,
            "interpretation": effect.interpretation,
        }
        for effect in summary.covariate_effects
    ]
    key_findings: List[str] = [summary.diagnostics.summary]
    key_findings.extend(
        "{}: {}".format(recommendation.subgroup, recommendation.action)
        for recommendation in summary.dosing_recommendations
    )

    return ModelSummaryResponse(
        selected_pk_model=selected_model,
        pk_parameters=pk_parameters,
        covariate_effects_summary=covariate_effects_summary,
        key_findings=key_findings,
        last_analysis_run_id=summary.run_id,
        last_analysis_generated_at=summary.generated_at.isoformat(),
    )
