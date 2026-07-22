"""Thin plain-text wrapper for the report-writing agent."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set

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
REPORT_VALIDATION_LOG_PATH = PROJECT_ROOT / "logs" / "report_validation.jsonl"

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "these",
    "this",
    "those",
    "to",
    "was",
    "were",
    "with",
}
_BANNED_CONFIDENCE_TERMS = (
    "robust",
    "substantial evidence",
    "definitive",
    "high confidence",
    "strongly supports",
    "clearly demonstrates",
)


def _model_json(model: BaseModel) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json(indent=2)
    return model.json(indent=2)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _significant_words(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return [word for word in words if word not in _STOPWORDS]


def _critical_flag_is_represented(flag: str, report: str) -> bool:
    normalized_flag = _normalize(flag)
    normalized_report = _normalize(report)
    if normalized_flag and normalized_flag in normalized_report:
        return True

    flag_words = _significant_words(flag)
    if not flag_words:
        return False
    report_words: Set[str] = set(_significant_words(report))
    unique_flag_words = set(flag_words)
    overlap = len(unique_flag_words.intersection(report_words))
    if overlap / len(unique_flag_words) >= 0.60:
        return True

    # A short ordered phrase can preserve a flag's distinctive key content even
    # when the surrounding sentence has been paraphrased.
    if len(flag_words) >= 4:
        report_key_text = " ".join(_significant_words(report))
        return any(
            " ".join(flag_words[index : index + 4]) in report_key_text
            for index in range(len(flag_words) - 3)
        )
    return False


def validate_report(
    report: str,
    analysis_summary: AnalysisSummary,
) -> List[str]:
    """Return deterministic factual and confidence-policy violations."""
    violations = []
    for flag in analysis_summary.diagnostics.critical_flags:
        if not _critical_flag_is_represented(flag, report):
            violations.append(
                "Critical diagnostic flag is not represented in the report: "
                "{}".format(flag)
            )

    overall_confidence = None
    for recommendation in analysis_summary.dosing_recommendations:
        if _normalize(recommendation.subgroup) == "overall population":
            overall_confidence = recommendation.confidence
            break

    normalized_report = _normalize(report)
    if overall_confidence is not None and overall_confidence != "high":
        for banned_term in _BANNED_CONFIDENCE_TERMS:
            if banned_term in normalized_report:
                violations.append(
                    "Banned confidence-inflating term '{}' was found while the "
                    "overall population recommendation confidence is '{}'.".format(
                        banned_term, overall_confidence
                    )
                )
    return violations


def _log_report_validation(
    run_id: str,
    first_pass_violations: List[str],
    regenerated: bool,
    final_violations: List[str],
    final_status: str,
) -> None:
    REPORT_VALIDATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "first_pass_violations": first_pass_violations,
        "regenerated": regenerated,
        "final_violations": final_violations,
        "final_status": final_status,
    }
    with REPORT_VALIDATION_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record) + "\n")


def run_report_writer(
    analysis_summary: AnalysisSummary,
    reviewer_decision: ReviewerDecision,
    run_id: str,
) -> str:
    """Generate and deterministically validate partner-facing Markdown."""
    system_prompt = REPORT_WRITER_PROMPT_PATH.read_text(encoding="utf-8")
    user_content = (
        "Analysis summary:\n"
        f"{_model_json(analysis_summary)}\n\n"
        "Reviewer decision:\n"
        f"{_model_json(reviewer_decision)}"
    )
    report = call_text(
        system_prompt=system_prompt,
        user_content=user_content,
        run_id=run_id,
        agent_name="report_writer",
    )
    first_pass_violations = validate_report(report, analysis_summary)
    if not first_pass_violations:
        _log_report_validation(
            run_id=run_id,
            first_pass_violations=[],
            regenerated=False,
            final_violations=[],
            final_status="passed_first_attempt",
        )
        return report

    correction_line = (
        "The previous report failed deterministic validation. Fix each of "
        "these violations specifically: {}"
    ).format(" | ".join(first_pass_violations))
    regeneration_content = "{}\n{}".format(user_content, correction_line)
    try:
        regenerated_report = call_text(
            system_prompt=system_prompt,
            user_content=regeneration_content,
            run_id=run_id,
            agent_name="report_writer",
        )
    except Exception as exc:
        final_violations = ["Report regeneration failed: {}".format(exc)]
        _log_report_validation(
            run_id=run_id,
            first_pass_violations=first_pass_violations,
            regenerated=True,
            final_violations=final_violations,
            final_status="failed",
        )
        raise RuntimeError(
            "Report regeneration failed for run_id={}: {}".format(run_id, exc)
        ) from exc

    final_violations = validate_report(regenerated_report, analysis_summary)
    if final_violations:
        _log_report_validation(
            run_id=run_id,
            first_pass_violations=first_pass_violations,
            regenerated=True,
            final_violations=final_violations,
            final_status="failed",
        )
        raise RuntimeError(
            "Report validation failed after one regeneration for run_id={}: "
            "{}".format(run_id, "; ".join(final_violations))
        )

    _log_report_validation(
        run_id=run_id,
        first_pass_violations=first_pass_violations,
        regenerated=True,
        final_violations=[],
        final_status="passed_after_regeneration",
    )
    return regenerated_report


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
