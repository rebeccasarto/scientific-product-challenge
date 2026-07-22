"""Thin structured wrapper for the analysis-planning agent."""

import sys
from pathlib import Path
from typing import List, Literal, cast

from pydantic import BaseModel, ConfigDict


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.llm_client import call_structured


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLANNER_PROMPT_PATH = PROJECT_ROOT / "agents" / "prompts" / "analysis_planner.md"


class PlannerOutput(BaseModel):
    """Constrained planning contract for the prespecified analysis scope."""

    model_config = ConfigDict(extra="forbid")

    pk_models_to_compare: List[Literal["1-compartment", "2-compartment"]]
    covariates_to_test: List[
        Literal["weight_kg", "creatinine_clearance_ml_min", "genotype"]
    ]
    efficacy_endpoint: Literal["clinical_response"]
    safety_endpoint: Literal["grade2plus_adverse_event"]
    validation_checks: List[str]
    dosing_policy: str


def run_planner(run_id: str) -> PlannerOutput:
    """Ask the planner to confirm the bounded, prespecified analysis plan."""
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
