"""Tests for deterministic report validation and bounded regeneration."""

from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

import agents.report_writer as report_writer_module
from agents.report_writer import run_report_writer, validate_report
from agents.schemas import (
    AnalysisSummary,
    DiagnosticsSummary,
    DosingRecommendation,
    PKModelComparison,
    ReviewerDecision,
)


def _summary(
    critical_flags: List[str],
    confidence: str = "moderate",
) -> AnalysisSummary:
    return AnalysisSummary(
        run_id="analysis-run",
        generated_at=datetime.now(timezone.utc),
        input_files=[],
        pk_model=PKModelComparison(
            candidates=[],
            selected_model="1-compartment",
            selection_rationale="Synthetic selection.",
        ),
        covariate_effects=[],
        exposure_response=[],
        diagnostics=DiagnosticsSummary(
            pk_model_converged=True,
            parameter_covariance_valid=True,
            predictive_check_passed=False,
            major_residual_bias=True,
            critical_flags=critical_flags,
            summary="Synthetic diagnostics.",
        ),
        dosing_recommendations=[
            DosingRecommendation(
                subgroup="overall population",
                action="maintain_current_dose",
                recommended_dose_mg=100.0,
                evidence_basis="observed",
                rationale="Synthetic recommendation.",
                confidence=confidence,
            )
        ],
        limitations=[],
    )


@pytest.fixture(autouse=True)
def _isolated_validation_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        report_writer_module,
        "REPORT_VALIDATION_LOG_PATH",
        tmp_path / "report_validation.jsonl",
    )


def test_missing_critical_flag_is_reported() -> None:
    flag = "Patient-level aggregate predictions missed observed concentrations."

    violations = validate_report(
        "The analysis recommends retaining the current dose.",
        _summary([flag]),
    )

    assert any(flag in violation for violation in violations)


def test_robust_is_rejected_for_moderate_confidence() -> None:
    violations = validate_report(
        "The analysis provides robust support for the current regimen.",
        _summary([], confidence="moderate"),
    )

    assert any("'robust'" in violation for violation in violations)
    assert any("'moderate'" in violation for violation in violations)


def test_clean_report_mentions_flag_without_inflating_confidence() -> None:
    flag = "Patient-level aggregate predictions missed observed concentrations."
    report = (
        "Patient-level aggregate predictions missed observed concentrations. "
        "The current dose is recommended with moderate confidence."
    )

    assert validate_report(report, _summary([flag])) == []


def test_run_report_writer_regenerates_once_and_returns_clean_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flag = "Patient-level aggregate predictions missed observed concentrations."
    summary = _summary([flag])
    decision = ReviewerDecision(
        run_id="review-run",
        generated_at=datetime.now(timezone.utc),
        status="approve",
        reviewer_notes="Synthetic approval.",
    )
    responses = [
        "The current regimen is appropriate for the analyzed population.",
        "{} The current regimen has moderate confidence.".format(flag),
    ]
    user_contents = []

    def fake_call_text(**kwargs: str) -> str:
        user_contents.append(kwargs["user_content"])
        return responses.pop(0)

    monkeypatch.setattr(report_writer_module, "call_text", fake_call_text)

    report = run_report_writer(summary, decision, "report-run")

    assert flag in report
    assert len(user_contents) == 2
    assert user_contents[1].startswith(user_contents[0] + "\n")
    assert "Critical diagnostic flag is not represented" in user_contents[1]

