"""Summarize committed OpenRouter usage with a reproducible list-price estimate."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LLM_LOG_PATH = PROJECT_ROOT / "logs" / "llm_calls.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results" / "final" / "spend_report.json"

# List prices verified against OpenRouter's model page on 2026-07-22.
MODEL_PRICE_PER_MILLION_USD = {
    "anthropic/claude-haiku-4.5": {"input": 1.0, "output": 5.0},
}


def build_spend_report(log_path: Path = LLM_LOG_PATH) -> Dict[str, Any]:
    """Calculate a conservative, reproducible estimate from JSONL usage logs."""
    by_model: Dict[str, Dict[str, float]] = {}
    attempts = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        attempts += 1
        model = str(record["model"])
        summary = by_model.setdefault(
            model,
            {"attempts": 0, "input_tokens": 0, "output_tokens": 0},
        )
        summary["attempts"] += 1
        summary["input_tokens"] += int(record.get("prompt_tokens") or 0)
        summary["output_tokens"] += int(record.get("completion_tokens") or 0)

    total_estimated_cost = 0.0
    for model, summary in by_model.items():
        prices = MODEL_PRICE_PER_MILLION_USD.get(model)
        if prices is None:
            summary["estimated_list_cost_usd"] = None
            continue
        estimated_cost = (
            summary["input_tokens"] * prices["input"] / 1_000_000
            + summary["output_tokens"] * prices["output"] / 1_000_000
        )
        summary["input_price_usd_per_million"] = prices["input"]
        summary["output_price_usd_per_million"] = prices["output"]
        summary["estimated_list_cost_usd"] = round(estimated_cost, 6)
        total_estimated_cost += estimated_cost

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usage_source": "logs/llm_calls.jsonl",
        "pricing_source": "https://openrouter.ai/anthropic/claude-haiku-4.5/pricing",
        "pricing_verified_on": "2026-07-22",
        "estimate_note": (
            "This is a conservative list-price estimate from logged token usage, "
            "not an OpenRouter invoice. It excludes cache discounts and any "
            "provider-specific adjustments."
        ),
        "attempts": attempts,
        "models": by_model,
        "estimated_total_list_cost_usd": round(total_estimated_cost, 6),
        "challenge_spend_cap_usd": 20.0,
        "within_challenge_cap": total_estimated_cost <= 20.0,
    }


def write_spend_report(output_path: Path = DEFAULT_OUTPUT_PATH) -> Dict[str, Any]:
    """Persist the current usage summary with stable formatting."""
    report = build_spend_report()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
