"""Pydantic request and response models for the PK/PD API."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class PatientCovariates(BaseModel):
    weight_kg: float
    creatinine_clearance_ml_min: float
    genotype: Literal["WT/WT", "WT/MUT", "MUT/MUT"]


class DoseRecommendationResponse(BaseModel):
    recommended_dose_mg: Optional[float]
    action: str
    confidence: str
    rationale: str
    uncertainty_note: str


class ModelSummaryResponse(BaseModel):
    selected_pk_model: str
    pk_parameters: Dict[str, float]
    covariate_effects_summary: List[Dict[str, Any]]
    key_findings: List[str]
    last_analysis_run_id: str
    last_analysis_generated_at: str
