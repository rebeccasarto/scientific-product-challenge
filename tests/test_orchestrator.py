"""Tests for the bounded reviewer-directed report revision workflow."""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pytest

import agents.orchestrator as orchestrator
from agents.schemas import (
    AnalysisSummary,
    DiagnosticsSummary,
    DosingRecommendation,
    PKModelComparison,
    ReviewFinding,
    ReviewerDecision,
)


def _summary(critical_flags: Optional[List[str]] = None) -> AnalysisSummary:
    return AnalysisSummary(
        run_id="analysis-run",
        generated_at=datetime.now(timezone.utc),
        input_files=[],
        pk_model=PKModelComparison(
            candidates=[], selected_model=None, selection_rationale="Synthetic input."
        ),
        covariate_effects=[],
        exposure_response=[],
        diagnostics=DiagnosticsSummary(
            pk_model_converged=True,
            parameter_covariance_valid=True,
            predictive_check_passed=not bool(critical_flags),
            major_residual_bias=bool(critical_flags),
            critical_flags=critical_flags or [],
            summary="Synthetic diagnostics.",
        ),
        dosing_recommendations=[],
        limitations=["Synthetic limitation."],
    )


def _decision(status: str) -> ReviewerDecision:
    findings = []
    if status == "revise":
        findings = [
            ReviewFinding(
                severity="major",
                category="reporting",
                issue="Clarify the report limitation.",
                evidence="Synthetic evidence.",
                required_action="Clarify the report limitation.",
            )
        ]
    return ReviewerDecision(
        run_id="orchestrator-run",
        generated_at=datetime.now(timezone.utc),
        status=status,
        findings=findings,
        reviewer_notes="Synthetic reviewer decision.",
    )


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestrator, "REVISION_CYCLES_LOG_PATH", tmp_path / "revision_cycles.jsonl"
    )
    monkeypatch.setattr(
        orchestrator, "RELEASE_DECISION_PATH", tmp_path / "release_decision.json"
    )
    monkeypatch.setattr(
        orchestrator, "REVIEWER_DECISION_PATH", tmp_path / "reviewer_decision.json"
    )


def test_revise_runs_one_report_revision_and_one_rereview(
    isolated_paths: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _summary()
    decisions = [_decision("revise"), _decision("approve")]
    events: List[str] = []

    def fake_reviewer(*_args, partner_report: Optional[str] = None) -> ReviewerDecision:
        events.append("rereview" if partner_report else "review")
        return decisions.pop(0)

    def fake_report_writer(*_args, revision_request: str = "") -> str:
        events.append("revision" if revision_request else "report")
        return "Revised report" if revision_request else "Initial report"

    monkeypatch.setattr(orchestrator, "run_reviewer", fake_reviewer)
    monkeypatch.setattr(orchestrator, "run_report_writer", fake_report_writer)

    report, decision, release = orchestrator.run_reviewed_report(
        summary, "orchestrator-run"
    )

    assert events == ["review", "report", "revision", "rereview"]
    assert report == "Revised report"
    assert decision.status == "approve"
    assert release.decision == "ready_to_send"


def test_critical_diagnostic_blocks_ready_to_send() -> None:
    summary = _summary(["Predictive check failed."])
    release = orchestrator.generate_release_decision(
        _decision("approve"), summary, "controlled-run"
    )

    assert release.decision == "requires_revision"
    assert release.outstanding_risks == ["[diagnostics] Predictive check failed."]
    assert "not ready_to_send" in release.justification


def test_missing_exposure_matching_simulation_blocks_ready_to_send() -> None:
    summary = _summary()
    summary.dosing_recommendations = [
        DosingRecommendation(
            subgroup="upper weight quartile",
            action="insufficient_evidence",
            recommended_dose_mg=None,
            evidence_basis="observed",
            rationale="A specific dose requires exposure-matching simulation.",
            confidence="low",
            validation_required=["exposure-matching simulation"],
        )
    ]

    release = orchestrator.generate_release_decision(
        _decision("approve"), summary, "controlled-run"
    )

    assert release.decision == "requires_revision"
    assert "No exposure-matching dose simulation" in release.justification


@pytest.mark.parametrize(
    ("reviewer_status", "expected_release"),
    [("approve", "ready_to_send"), ("revise", "requires_revision"), ("hold", "hold")],
)
def test_release_mapping_without_critical_diagnostics(
    reviewer_status: str, expected_release: str
) -> None:
    release = orchestrator.generate_release_decision(
        _decision(reviewer_status), _summary(), "controlled-run"
    )
    assert release.decision == expected_release
