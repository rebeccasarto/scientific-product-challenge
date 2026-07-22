"""Thin plain-text wrapper for the report-writing agent."""

import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.llm_client import call_text
from agents.schemas import (
    AnalysisSummary,
    DiagnosticsSummary,
    PKModelComparison,
    ReviewerDecision,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_WRITER_PROMPT_PATH = PROJECT_ROOT / "prompts" / "report_writer.md"


def _model_json(model: BaseModel) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json(indent=2)
    return model.json(indent=2)


def run_report_writer(
    analysis_summary: AnalysisSummary,
    reviewer_decision: ReviewerDecision,
    run_id: str,
) -> str:
    """Ask the report writer for raw partner-facing Markdown."""
    system_prompt = REPORT_WRITER_PROMPT_PATH.read_text(encoding="utf-8")
    user_content = (
        "Analysis summary:\n"
        f"{_model_json(analysis_summary)}\n\n"
        "Reviewer decision:\n"
        f"{_model_json(reviewer_decision)}"
    )
    return call_text(
        system_prompt=system_prompt,
        user_content=user_content,
        run_id=run_id,
        agent_name="report_writer",
    )


if __name__ == "__main__":
    placeholder_summary = AnalysisSummary(
        run_id="test-run",
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
    placeholder_review = ReviewerDecision(
        run_id="test-run",
        generated_at=datetime.now(timezone.utc),
        status="approve",
        reviewer_notes="Placeholder reviewer decision for smoke-testing.",
    )
    print(
        run_report_writer(
            placeholder_summary,
            placeholder_review,
            "test-run",
        )
    )
