"""Structured schemas for inter-agent payloads.

Pipeline modules populate these; agents read/write them as JSON.
Top-level envelope carries provenance; nested objects carry the science.
"""

from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel


class ParameterEstimate(BaseModel):
    estimate: float
    standard_error: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    unit: Optional[str] = None


class PKCandidateResult(BaseModel):
    model_type: Literal["1-compartment", "2-compartment"]
    converged: bool
    parameters: Dict[str, ParameterEstimate]
    aic: Optional[float] = None
    bic: Optional[float] = None
    diagnostic_flags: List[str] = []
    failure_reason: Optional[str] = None


class PKModelComparison(BaseModel):
    candidates: List[PKCandidateResult]
    selected_model: Optional[Literal["1-compartment", "2-compartment"]]
    selection_rationale: str


class CovariateEffect(BaseModel):
    covariate: Literal[
        "weight_kg",
        "creatinine_clearance_ml_min",
        "albumin_g_dl",
        "genotype",
        "site",
    ]
    parameter_affected: str
    effect_form: str
    effect_estimate: float
    reference_value: Optional[Union[str, float]] = None
    comparison_value: Optional[Union[str, float]] = None
    confidence_interval: Optional[Tuple[float, float]] = None
    p_value: Optional[float] = None
    clinically_material: bool
    interpretation: str


class ExposureResponseResult(BaseModel):
    endpoint: Literal[
        "clinical_response",
        "disease_score_change",
        "inflammatory_marker_reduction_pct",
        "any_adverse_event",
        "grade2plus_adverse_event",
    ]
    endpoint_type: Literal["efficacy", "safety"]
    model_form: str
    exposure_metric: str
    converged: bool
    n_patients: int
    n_events: Optional[int] = None
    effect_estimate: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    diagnostic_flags: List[str] = []
    key_finding: str


class DiagnosticsSummary(BaseModel):
    pk_model_converged: bool
    parameter_covariance_valid: bool
    predictive_check_passed: bool
    major_residual_bias: bool
    critical_flags: List[str] = []
    warnings: List[str] = []
    summary: str


class DosingRecommendation(BaseModel):
    subgroup: str
    action: Literal[
        "maintain_current_dose",
        "increase_dose",
        "decrease_dose",
        "no_subgroup_adjustment",
        "insufficient_evidence",
    ]
    recommended_dose_mg: Optional[float] = None
    reference_dose_mg: float = 100.0
    evidence_basis: Literal["observed", "model_simulation", "unsupported"]
    rationale: str
    confidence: Literal["high", "moderate", "low"]
    validation_required: List[str] = []


class AnalysisSummary(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    generated_at: datetime
    input_files: List[str]
    pk_model: PKModelComparison
    covariate_effects: List[CovariateEffect]
    exposure_response: List[ExposureResponseResult]
    diagnostics: DiagnosticsSummary
    dosing_recommendations: List[DosingRecommendation]
    limitations: List[str]


class ReviewFinding(BaseModel):
    severity: Literal["critical", "major", "minor"]
    category: Literal[
        "data_quality",
        "modeling",
        "diagnostics",
        "interpretation",
        "dosing",
        "reporting",
    ]
    issue: str
    evidence: str
    required_action: Optional[str] = None


class ReviewerDecision(BaseModel):
    run_id: str
    generated_at: datetime
    status: Literal["approve", "revise", "hold"]
    findings: List[ReviewFinding] = []
    reviewer_notes: str


class ReleaseDecision(BaseModel):
    run_id: str
    generated_at: datetime
    decision: Literal["ready_to_send", "requires_revision", "hold"]
    justification: str
    outstanding_risks: List[str] = []
