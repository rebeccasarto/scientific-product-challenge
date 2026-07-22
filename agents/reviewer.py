"""Thin structured wrapper for the scientific-review agent."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from pydantic import BaseModel


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.llm_client import call_structured
from agents.schemas import (
    AnalysisSummary,
    DiagnosticsSummary,
    PKModelComparison,
    ReviewerDecision,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEWER_PROMPT_PATH = PROJECT_ROOT / "prompts" / "scientific_reviewer.md"


def _model_json(model: BaseModel) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json(indent=2)
    return model.json(indent=2)


def _placeholder_analysis_summary(run_id: str) -> AnalysisSummary:
    return AnalysisSummary(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc),
        input_files=[],
        pk_model=PKModelComparison(
            candidates=[],
            selected_model=None,
            selection_rationale="Placeholder analysis summary for smoke-testing.",
        ),
        covariate_effects=[],
        exposure_response=[],
        diagnostics=DiagnosticsSummary(
            pk_model_converged=False,
            parameter_covariance_valid=False,
            predictive_check_passed=False,
            major_residual_bias=False,
            summary="Placeholder diagnostics.",
        ),
        dosing_recommendations=[],
        limitations=["Placeholder input; not an analytical result."],
    )


def run_reviewer(
    analysis_summary: AnalysisSummary,
    run_id: str,
) -> ReviewerDecision:
    """Ask the reviewer for a schema-validated scientific decision."""
    system_prompt = REVIEWER_PROMPT_PATH.read_text(encoding="utf-8")
    return cast(
        ReviewerDecision,
        call_structured(
            system_prompt=system_prompt,
            user_content=_model_json(analysis_summary),
            response_model=ReviewerDecision,
            run_id=run_id,
            agent_name="reviewer",
        ),
    )


if __name__ == "__main__":
    placeholder = _placeholder_analysis_summary("test-run")
    print(run_reviewer(placeholder, "test-run"))
