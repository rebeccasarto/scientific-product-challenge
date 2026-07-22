"""Coordinate the evidence review and report-writing stages in sequence."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.report_writer import run_report_writer
from agents.reviewer import run_reviewer
from agents.schemas import AnalysisSummary, ReleaseDecision, ReviewerDecision


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_CYCLES_LOG_PATH = PROJECT_ROOT / "logs" / "revision_cycles.jsonl"
RELEASE_DECISION_PATH = (
    PROJECT_ROOT / "results" / "final" / "release_decision.json"
)
REVIEWER_DECISION_PATH = (
    PROJECT_ROOT / "results" / "final" / "reviewer_decision.json"
)


def _log_revision_cycle(run_id: str, reviewer_status: str, phase: str) -> None:
    """Append one audit record for a bounded review/report sequence phase."""
    REVISION_CYCLES_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "reviewer_status": reviewer_status,
        "phase": phase,
        "note": (
            "Report-level validation and regeneration, if any, are tracked "
            "separately in logs/report_validation.jsonl by run_report_writer."
        ),
    }
    with REVISION_CYCLES_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record) + "\n")


def generate_release_decision(
    reviewer_decision: ReviewerDecision,
    analysis_summary: AnalysisSummary,
    run_id: str,
) -> ReleaseDecision:
    """Map final review and unresolved critical diagnostics to release status."""
    decision_by_status = {
        "approve": "ready_to_send",
        "revise": "requires_revision",
        "hold": "hold",
    }
    severity_counts = {
        severity: sum(
            finding.severity == severity for finding in reviewer_decision.findings
        )
        for severity in ("critical", "major", "minor")
    }
    critical_diagnostics = list(analysis_summary.diagnostics.critical_flags)
    mapped_decision = decision_by_status[reviewer_decision.status]
    if critical_diagnostics and mapped_decision == "ready_to_send":
        mapped_decision = "requires_revision"

    justification = (
        "{} critical, {} major, {} minor finding(s) from scientific review. "
        "Reviewer notes: {}"
    ).format(
        severity_counts["critical"],
        severity_counts["major"],
        severity_counts["minor"],
        reviewer_decision.reviewer_notes,
    )
    outstanding_risks: List[str] = [
        "[{}] {}".format(finding.category, finding.issue)
        for finding in reviewer_decision.findings
    ]
    outstanding_risks.extend(
        "[diagnostics] {}".format(flag) for flag in critical_diagnostics
    )
    if critical_diagnostics:
        justification += (
            " Release is not ready_to_send because {} unresolved critical "
            "diagnostic flag(s) remain."
        ).format(len(critical_diagnostics))
    return ReleaseDecision(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc),
        decision=mapped_decision,
        justification=justification,
        outstanding_risks=outstanding_risks,
    )


def run_reviewed_report(
    analysis_summary: AnalysisSummary,
    run_id: str,
) -> Tuple[str, ReviewerDecision, ReleaseDecision]:
    """Run at most one reviewer-directed report revision and re-review it."""
    reviewer_decision = run_reviewer(analysis_summary, run_id)
    report = run_report_writer(analysis_summary, reviewer_decision, run_id)
    _log_revision_cycle(run_id, reviewer_decision.status, "initial_review")

    if reviewer_decision.status == "revise":
        revision_request = "\n".join(
            "- {}".format(finding.required_action or finding.issue)
            for finding in reviewer_decision.findings
        ) or "- Address the reviewer notes while preserving evidence traceability."
        report = run_report_writer(
            analysis_summary,
            reviewer_decision,
            run_id,
            revision_request=revision_request,
        )
        reviewer_decision = run_reviewer(
            analysis_summary,
            run_id,
            partner_report=report,
        )
        _log_revision_cycle(run_id, reviewer_decision.status, "post_revision_review")

    REVIEWER_DECISION_PATH.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(reviewer_decision, "model_dump_json"):
        reviewer_payload = reviewer_decision.model_dump_json(indent=2)
    else:
        reviewer_payload = reviewer_decision.json(indent=2)
    REVIEWER_DECISION_PATH.write_text(reviewer_payload + "\n", encoding="utf-8")
    release_decision = generate_release_decision(
        reviewer_decision,
        analysis_summary,
        run_id,
    )
    RELEASE_DECISION_PATH.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(release_decision, "model_dump_json"):
        release_payload = release_decision.model_dump_json(indent=2)
    else:
        release_payload = release_decision.json(indent=2)
    RELEASE_DECISION_PATH.write_text(release_payload + "\n", encoding="utf-8")
    return report, reviewer_decision, release_decision


if __name__ == "__main__":
    from run_pkpd_analysis import run_analysis

    pipeline_run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    summary = run_analysis(pipeline_run_id)
    final_report, final_decision, final_release = run_reviewed_report(
        summary,
        pipeline_run_id,
    )
    print(final_report)
    print("Reviewer status: {}".format(final_decision.status))
    print("Release decision: {}".format(final_release.decision))
