"""Tests for reproducible OpenRouter token-usage spend reporting."""

import json
from pathlib import Path

from pipeline.spend import build_spend_report


def test_build_spend_report_uses_list_prices(tmp_path: Path) -> None:
    log_path = tmp_path / "llm_calls.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "model": "anthropic/claude-haiku-4.5",
                "prompt_tokens": 1_000_000,
                "completion_tokens": 1_000_000,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_spend_report(log_path)

    assert report["estimated_total_list_cost_usd"] == 6.0
    assert report["within_challenge_cap"] is True
