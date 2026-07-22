"""Tests for the linear reviewer/report-writer orchestrator."""

from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

import agents.orchestrator as orchestrator
from agents.schemas import (
    AnalysisSummary,
    DiagnosticsSummary,
    PKModelComparison,
    ReviewerDecision,
)


def _analysis_summary() -> AnalysisSummary:
    return AnalysisSummary(
        run_id="analysis-run",
        generated_at=datetime.now(timezone.utc),
        input_files=[],
        pk_model=PKModelComparison(
            candidates=[],
            selected_model=None,
            selection_rationale="Synthetic test input.",
        ),
        covariate_effects=[],
        exposure_response=[],
        diagnostics=DiagnosticsSummary(
            pk_model_converged=False,
            parameter_covariance_valid=False,
            predictive_check_passed=False,
            major_residual_bias=False,
            summary="Synthetic diagnostics.",
        ),
        dosing_recommendations=[],
        limitations=[],
    )


def _decision(status: str) -> ReviewerDecision:
    return ReviewerDecision(
        run_id="orchestrator-run",
        generated_at=datetime.now(timezone.utc),
        status=status,
        findings=[],
        reviewer_notes="Synthetic reviewer decision.",
    )


@pytest.mark.parametrize("status", ["approve", "revise", "hold"])
def test_calls_each_stage_once_in_order_regardless_of_status(
    status: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _analysis_summary()
    decision = _decision(status)
    events: List[str] = []

    def fake_reviewer(
        received_summary: AnalysisSummary,
        received_run_id: str,
    ) -> ReviewerDecision:
        assert received_summary is summary
        assert received_run_id == "orchestrator-run"
        events.append("reviewer")
        return decision

    def fake_report_writer(
        received_summary: AnalysisSummary,
        received_decision: ReviewerDecision,
        received_run_id: str,
    ) -> str:
        assert received_summary is summary
        assert received_decision is decision
        assert received_run_id == "orchestrator-run"
        events.append("report_writer")
        return "Generated report text."

    monkeypatch.setattr(orchestrator, "run_reviewer", fake_reviewer)
    monkeypatch.setattr(orchestrator, "run_report_writer", fake_report_writer)
    monkeypatch.setattr(
        orchestrator,
        "REVISION_CYCLES_LOG_PATH",
        tmp_path / "revision_cycles.jsonl",
    )
    monkeypatch.setattr(
        orchestrator,
        "RELEASE_DECISION_PATH",
        tmp_path / "release_decision.json",
    )
    monkeypatch.setattr(
        orchestrator,
        "REVIEWER_DECISION_PATH",
        tmp_path / "reviewer_decision.json",
    )

    orchestrator.run_reviewed_report(summary, "orchestrator-run")

    assert events == ["reviewer", "report_writer"]


def test_returns_report_and_decision_unmodified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _analysis_summary()
    decision = _decision("revise")
    report = "Exact report output from the mocked report writer."

    monkeypatch.setattr(orchestrator, "run_reviewer", lambda *_: decision)
    monkeypatch.setattr(orchestrator, "run_report_writer", lambda *_: report)
    monkeypatch.setattr(
        orchestrator,
        "REVISION_CYCLES_LOG_PATH",
        tmp_path / "revision_cycles.jsonl",
    )
    monkeypatch.setattr(
        orchestrator,
        "RELEASE_DECISION_PATH",
        tmp_path / "release_decision.json",
    )
    monkeypatch.setattr(
        orchestrator,
        "REVIEWER_DECISION_PATH",
        tmp_path / "reviewer_decision.json",
    )

    returned_report, returned_decision, returned_release = (
        orchestrator.run_reviewed_report(
            summary,
            "orchestrator-run",
        )
    )

    assert returned_report is report
    assert returned_decision is decision
    assert returned_release.decision == "requires_revision"
    assert returned_release.run_id == "orchestrator-run"
    assert (tmp_path / "reviewer_decision.json").exists()


@pytest.mark.parametrize(
    ("reviewer_status", "expected_release_decision"),
    [
        ("approve", "ready_to_send"),
        ("revise", "requires_revision"),
        ("hold", "hold"),
    ],
)
def test_generate_release_decision_is_pure_and_maps_all_statuses(
    reviewer_status: str,
    expected_release_decision: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_path = tmp_path / "release_decision.json"
    monkeypatch.setattr(
        orchestrator,
        "RELEASE_DECISION_PATH",
        release_path,
    )

    release = orchestrator.generate_release_decision(
        _decision(reviewer_status),
        "code-controlled-run-id",
    )

    assert release.decision == expected_release_decision
    assert release.run_id == "code-controlled-run-id"
    assert release.outstanding_risks == []
    assert "0 critical, 0 major, 0 minor" in release.justification
    assert not release_path.exists()
