"""Coordinate the evidence review and report-writing stages in sequence."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.report_writer import run_report_writer
from agents.reviewer import run_reviewer
from agents.schemas import AnalysisSummary, ReviewerDecision


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION_CYCLES_LOG_PATH = PROJECT_ROOT / "logs" / "revision_cycles.jsonl"


def _log_revision_cycle(run_id: str, reviewer_status: str) -> None:
    """Append one audit record for the completed review/report sequence."""
    REVISION_CYCLES_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "reviewer_status": reviewer_status,
        "note": (
            "Report-level validation and regeneration, if any, are tracked "
            "separately in logs/report_validation.jsonl by run_report_writer."
        ),
    }
    with REVISION_CYCLES_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record) + "\n")


def run_reviewed_report(
    analysis_summary: AnalysisSummary,
    run_id: str,
) -> Tuple[str, ReviewerDecision]:
    """Review analytical evidence once, then generate and validate its report."""
    reviewer_decision = run_reviewer(analysis_summary, run_id)
    report = run_report_writer(analysis_summary, reviewer_decision, run_id)
    _log_revision_cycle(run_id, reviewer_decision.status)
    return report, reviewer_decision


if __name__ == "__main__":
    from run_pkpd_analysis import run_analysis

    pipeline_run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    summary = run_analysis(pipeline_run_id)
    final_report, final_decision = run_reviewed_report(summary, pipeline_run_id)
    print(final_report)
    print("Reviewer status: {}".format(final_decision.status))
