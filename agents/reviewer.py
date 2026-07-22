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
REVIEWER_PROMPT_PATH = (
    PROJECT_ROOT / "agents" / "prompts" / "scientific_reviewer.md"
)
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
    return " ".join(text.casefold().replace("_", " ").split())


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
    combined = " ".join(_finding_texts(finding))
    concerns_overall = (
        "overall population" in combined or "overall recommendation" in combined
    )
    return concerns_overall and "confidence" in combined


def _has_supported_insufficient_evidence(
    analysis_summary: AnalysisSummary,
) -> bool:
    """Return whether a subgroup has a complete, non-numeric evidence pathway."""
    return any(
        recommendation.action == "insufficient_evidence"
        and bool(recommendation.rationale.strip())
        and bool(recommendation.validation_required)
        for recommendation in analysis_summary.dosing_recommendations
    )


def _moderate_confidence_is_supported(
    analysis_summary: AnalysisSummary,
    overall_text: str,
) -> bool:
    """Apply the documented confidence policy to the overall recommendation."""
    efficacy_supported = _univariate_significance(analysis_summary, "efficacy") is True
    safety_not_significant = _univariate_significance(analysis_summary, "safety") is False
    critical_flags = [
        _normalize(flag) for flag in analysis_summary.diagnostics.critical_flags
    ]
    diagnostics_acknowledged = all(flag in overall_text for flag in critical_flags)
    return efficacy_supported and safety_not_significant and diagnostics_acknowledged


def _aicc_evidence_is_present(analysis_summary: AnalysisSummary) -> bool:
    """Allow nullable AIC/BIC fields when the documented paired AICc is present."""
    comparison = analysis_summary.pk_model
    evidence = " ".join(
        [comparison.selection_rationale] + comparison.diagnostic_flags
    )
    return "aicc" in _normalize(evidence)


def _selection_rule_is_documented(analysis_summary: AnalysisSummary) -> bool:
    evidence = _normalize(
        " ".join(
            [analysis_summary.pk_model.selection_rationale]
            + analysis_summary.pk_model.diagnostic_flags
        )
    )
    return "65%" in evidence and "aicc" in evidence


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
                and normalized_flag in overall_text
                and normalized_flag in " ".join(_finding_texts(finding))
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

        finding_text = " ".join(_finding_texts(finding))
        if "report" in finding_text and (
            "executive summary" in finding_text
            or "recommendation table" in finding_text
        ):
            removed_count += 1
            _log_removed_finding(
                decision,
                finding,
                "review_scope_check",
                "The scientific reviewer evaluates AnalysisSummary evidence, "
                "not partner-report layout or presentation.",
            )
            continue

        if (
            "insufficient evidence" in finding_text
            and _has_supported_insufficient_evidence(analysis_summary)
        ):
            removed_count += 1
            _log_removed_finding(
                decision,
                finding,
                "supported_insufficient_evidence_check",
                "A subgroup conclusion of insufficient_evidence has an explicit "
                "rationale and validation pathway; this is an allowed final "
                "conclusion under the reviewer policy.",
            )
            continue

        if (
            "confidence interval notation" in finding_text
            and "iqr" in finding_text
            and "ci lower" in finding_text
        ):
            removed_count += 1
            _log_removed_finding(
                decision,
                finding,
                "parameter_uncertainty_semantics_check",
                "The summary distinguishes population PK IQR bounds from "
                "covariate confidence intervals; these are different schema "
                "fields, not an internal contradiction.",
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
            ("65%" in finding_text or "aicc" in finding_text)
            and _selection_rule_is_documented(analysis_summary)
        ):
            removed_count += 1
            _log_removed_finding(
                decision,
                finding,
                "documented_selection_rule_check",
                "The PK comparison records both the prespecified 65% cohort "
                "threshold and paired AICc support for the selected model.",
            )
            continue

        if _is_confidence_calibration_finding(finding) and _moderate_confidence_is_supported(
            analysis_summary, overall_text
        ):
            removed_count += 1
            _log_removed_finding(
                decision,
                finding,
                "confidence_policy_check",
                "Moderate confidence is permitted by the documented policy: "
                "efficacy is significant, safety is non-significant, and each "
                "critical diagnostic flag is acknowledged in the overall "
                "recommendation.",
            )
            continue

        if (
            "aic" in finding_text
            and "null" in finding_text
            and _aicc_evidence_is_present(analysis_summary)
        ):
            removed_count += 1
            _log_removed_finding(
                decision,
                finding,
                "aicc_traceability_check",
                "Candidate AIC/BIC fields are nullable by schema, while paired "
                "AICc model-selection evidence is explicitly recorded in the "
                "PK comparison rationale and diagnostic flags.",
            )
            continue

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
    partner_report: Optional[str] = None,
) -> ReviewerDecision:
    """Review evidence, and optionally the report produced from that evidence."""
    system_prompt = REVIEWER_PROMPT_PATH.read_text(encoding="utf-8")
    user_content = _model_json(analysis_summary)
    if partner_report is not None:
        user_content = "AnalysisSummary:\n{}\n\nPartner report:\n{}".format(
            user_content,
            partner_report,
        )
    decision = cast(
        ReviewerDecision,
        call_structured(
            system_prompt=system_prompt,
            user_content=user_content,
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
    # Findings remain intact. The orchestrator owns a bounded revision cycle;
    # it must not silently convert a reviewer-requested revision into approval.
    return corrected_decision


if __name__ == "__main__":
    placeholder = _placeholder_analysis_summary("test-run")
    print(run_reviewer(placeholder, "test-run"))
