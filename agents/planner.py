"""Thin structured wrapper for the analysis-planning agent."""

import sys
from pathlib import Path
from typing import Any, List, cast

from pydantic import BaseModel, ConfigDict


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.llm_client import call_structured


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLANNER_PROMPT_PATH = PROJECT_ROOT / "prompts" / "analysis_planner.md"


class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    proposed_model: Any
    covariates_to_test: List[Any]
    validation_checks: List[Any]
    decision_thresholds: Any
    planned_report_outputs: List[Any]


def run_planner(run_id: str) -> PlannerOutput:
    """Ask the planner for a pre-analysis plan based only on study context."""
    system_prompt = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
    user_content = (
        "Plan the analysis for a dataset with 240 patients receiving a single "
        "100 mg IV bolus dose, with concentration-time PK, longitudinal PD "
        "biomarker, efficacy, covariate, and safety data available."
    )
    return cast(
        PlannerOutput,
        call_structured(
            system_prompt=system_prompt,
            user_content=user_content,
            response_model=PlannerOutput,
            run_id=run_id,
            agent_name="planner",
        ),
    )


if __name__ == "__main__":
    print(run_planner("test-run"))
