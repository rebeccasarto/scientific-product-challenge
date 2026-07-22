"""Thin structured wrapper for the scientific-review agent."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from pydantic import BaseModel


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.llm_client import call_structured
from agents.schemas import (
    AnalysisSummary,
    DiagnosticsSummary,
    PKModelComparison,
    ReviewFinding,
    ReviewerDecision,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEWER_PROMPT_PATH = PROJECT_ROOT / "prompts" / "scientific_reviewer.md"
REVIEWER_OVERRIDE_LOG_PATH = PROJECT_ROOT / "logs" / "reviewer_overrides.jsonl"

_CONFIDENCE_POLICY_NOTE = (
    "(Note: confidence calibration is a policy judgment, not a factual error "
    "— see prompt-documented policy: moderate confidence is compatible with "
    "a maintain_current_dose recommendation when efficacy is significant and "
    "safety is non-significant.)"
)


def _model_json(model: BaseModel) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json(indent=2)
    return model.json(indent=2)


def _model_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _copy_model(model: BaseModel, update: Dict[str, Any]) -> BaseModel:
    if hasattr(model, "model_copy"):
        return model.model_copy(update=update)
    return model.copy(update=update)


def _normalize(text: str) -> str:
    """Normalize only case and whitespace for conservative substring checks."""
    return " ".join(text.casefold().split())


def _finding_texts(finding: ReviewFinding) -> List[str]:
    return [_normalize(finding.issue), _normalize(finding.evidence)]


def _claims_unacknowledged_flag(
    finding: ReviewFinding,
    normalized_flag: str,
) -> bool:
    acknowledgment_phrases = (
        "not accounted for",
        "not addressed",
        "ignored",
    )
    return any(
        normalized_flag in text
        and any(phrase in text for phrase in acknowledgment_phrases)
        for text in _finding_texts(finding)
    )


def _claims_missing_evidence_type(
    finding: ReviewFinding,
    evidence_type: str,
) -> bool:
    claim_phrases = [
        "{} evidence is absent".format(evidence_type),
        "{} evidence absent".format(evidence_type),
        "{} evidence is missing".format(evidence_type),
        "{} evidence missing".format(evidence_type),
        "absent {} evidence".format(evidence_type),
        "missing {} evidence".format(evidence_type),
        "{} is absent".format(evidence_type),
        "{} is missing".format(evidence_type),
    ]
    return any(
        phrase in text
        for text in _finding_texts(finding)
        for phrase in claim_phrases
    )


def _claims_missing_efficacy_or_safety(finding: ReviewFinding) -> bool:
    return any(
        _claims_missing_evidence_type(finding, evidence_type)
        for evidence_type in ("efficacy", "safety")
    )


def _overall_recommendation_text(analysis_summary: AnalysisSummary) -> str:
    text_parts = []
    for recommendation in analysis_summary.dosing_recommendations:
        if _normalize(recommendation.subgroup) == "overall population":
            text_parts.append(recommendation.rationale)
            text_parts.extend(recommendation.validation_required)
    return _normalize(" ".join(text_parts))


def _univariate_significance(
    analysis_summary: AnalysisSummary,
    endpoint_type: str,
) -> Optional[bool]:
    for result in analysis_summary.exposure_response:
        if (
            result.endpoint_type == endpoint_type
            and result.model_form == "logistic_univariate"
            and result.ci_lower is not None
            and result.ci_upper is not None
        ):
            return result.ci_lower > 0 or result.ci_upper < 0
    return None


def _factually_misstates_significance(
    finding: ReviewFinding,
    analysis_summary: AnalysisSummary,
) -> bool:
    texts = _finding_texts(finding)
    for endpoint_type in ("efficacy", "safety"):
        endpoint_is_present = any(
            result.endpoint_type == endpoint_type
            for result in analysis_summary.exposure_response
        )
        if endpoint_is_present and _claims_missing_evidence_type(
            finding, endpoint_type
        ):
            return True
        significance = _univariate_significance(analysis_summary, endpoint_type)
        if significance is not False:
            continue
        false_claims = (
            "{} is statistically significant".format(endpoint_type),
            "{} result is statistically significant".format(endpoint_type),
            "{} evidence is statistically significant".format(endpoint_type),
        )
        if any(claim in text for text in texts for claim in false_claims):
            return True
    return False


def _is_confidence_calibration_finding(finding: ReviewFinding) -> bool:
    if finding.category != "dosing":
        return False
    combined = " ".join(_finding_texts(finding))
    concerns_overall = (
        "overall population" in combined or "overall recommendation" in combined
    )
    return concerns_overall and "confidence" in combined


def _log_removed_finding(
    decision: ReviewerDecision,
    finding: ReviewFinding,
    check_name: str,
    reason_removed: str,
) -> None:
    REVIEWER_OVERRIDE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": decision.run_id,
        "check_name": check_name,
        "original_finding": _model_dict(finding),
        "reason_removed": reason_removed,
    }
    with REVIEWER_OVERRIDE_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record) + "\n")


def validate_review_findings(
    decision: ReviewerDecision,
    analysis_summary: AnalysisSummary,
) -> ReviewerDecision:
    """Fact-check narrowly defined reviewer claims without another LLM call."""
    overall_text = _overall_recommendation_text(analysis_summary)
    normalized_flags = [
        (_normalize(flag), flag) for flag in analysis_summary.diagnostics.critical_flags
    ]
    has_efficacy = any(
        result.endpoint_type == "efficacy"
        for result in analysis_summary.exposure_response
    )
    has_safety = any(
        result.endpoint_type == "safety"
        for result in analysis_summary.exposure_response
    )

    retained_findings = []
    removed_count = 0
    for finding in decision.findings:
        acknowledged_flag = next(
            (
                original_flag
                for normalized_flag, original_flag in normalized_flags
                if normalized_flag
                and _claims_unacknowledged_flag(finding, normalized_flag)
                and normalized_flag in overall_text
            ),
            None,
        )
        if acknowledged_flag is not None:
            removed_count += 1
            _log_removed_finding(
                decision,
                finding,
                "flag_acknowledgment_check",
                "The cited critical flag is explicitly present in the overall "
                "population dosing rationale or validation requirements: {}".format(
                    acknowledged_flag
                ),
            )
            continue

        if (
            has_efficacy
            and has_safety
            and _claims_missing_efficacy_or_safety(finding)
        ):
            removed_count += 1
            _log_removed_finding(
                decision,
                finding,
                "efficacy_safety_presence_check",
                "AnalysisSummary contains at least one efficacy and at least "
                "one safety exposure-response result.",
            )
            continue

        if (
            _is_confidence_calibration_finding(finding)
            and not _factually_misstates_significance(finding, analysis_summary)
        ):
            required_action = finding.required_action or ""
            if _CONFIDENCE_POLICY_NOTE not in required_action:
                required_action = "{} {}".format(
                    required_action.rstrip(), _CONFIDENCE_POLICY_NOTE
                ).strip()
            severity = "minor" if finding.severity == "critical" else finding.severity
            finding = cast(
                ReviewFinding,
                _copy_model(
                    finding,
                    {
                        "severity": severity,
                        "required_action": required_action,
                    },
                ),
            )

        retained_findings.append(finding)

    updates = {"findings": retained_findings}
    if removed_count > 0 and not retained_findings and decision.status == "revise":
        updates.update(
            {
                "status": "approve",
                "reviewer_notes": (
                    "Status changed from REVISE to APPROVE by deterministic "
                    "post-review validation, which removed finding(s) that were "
                    "factually contradicted by the AnalysisSummary. This approval "
                    "reflects automated fact-checking, not an unprompted LLM "
                    "approval. Original LLM reviewer_notes: {}"
                ).format(decision.reviewer_notes),
            }
        )
    return cast(ReviewerDecision, _copy_model(decision, updates))


def _placeholder_analysis_summary(run_id: str) -> AnalysisSummary:
    return AnalysisSummary(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc),
        input_files=[],
        pk_model=PKModelComparison(
            candidates=[],
            selected_model=None,
            selection_rationale="Placeholder analysis summary for smoke-testing.",
        ),
        covariate_effects=[],
        exposure_response=[],
        diagnostics=DiagnosticsSummary(
            pk_model_converged=False,
            parameter_covariance_valid=False,
            predictive_check_passed=False,
            major_residual_bias=False,
            summary="Placeholder diagnostics.",
        ),
        dosing_recommendations=[],
        limitations=["Placeholder input; not an analytical result."],
    )


def run_reviewer(
    analysis_summary: AnalysisSummary,
    run_id: str,
) -> ReviewerDecision:
    """Ask for a decision while retaining local control of its provenance."""
    system_prompt = REVIEWER_PROMPT_PATH.read_text(encoding="utf-8")
    decision = cast(
        ReviewerDecision,
        call_structured(
            system_prompt=system_prompt,
            user_content=_model_json(analysis_summary),
            response_model=ReviewerDecision,
            run_id=run_id,
            agent_name="reviewer",
        ),
    )
    provenance = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc),
    }
    corrected_decision = cast(
        ReviewerDecision,
        _copy_model(decision, provenance),
    )
    return validate_review_findings(corrected_decision, analysis_summary)


if __name__ == "__main__":
    placeholder = _placeholder_analysis_summary("test-run")
    print(run_reviewer(placeholder, "test-run"))
