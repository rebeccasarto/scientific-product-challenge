"""Tests for deterministic validation of LLM reviewer findings."""

from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

import agents.reviewer as reviewer_module
from agents.reviewer import validate_review_findings
from agents.schemas import (
    AnalysisSummary,
    DiagnosticsSummary,
    DosingRecommendation,
    ExposureResponseResult,
    PKModelComparison,
    ReviewFinding,
    ReviewerDecision,
)


def _exposure_result(endpoint_type: str, ci_lower: float, ci_upper: float):
    endpoint = (
        "clinical_response"
        if endpoint_type == "efficacy"
        else "grade2plus_adverse_event"
    )
    return ExposureResponseResult(
        endpoint=endpoint,
        endpoint_type=endpoint_type,
        model_form="logistic_univariate",
        exposure_metric="AUC_0_inf",
        converged=True,
        n_patients=20,
        n_events=10,
        effect_estimate=0.2,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        key_finding="Synthetic result.",
    )


def _summary(
    critical_flags: List[str],
    recommendation_text: str,
) -> AnalysisSummary:
    return AnalysisSummary(
        run_id="analysis-run",
        generated_at=datetime.now(timezone.utc),
        input_files=[],
        pk_model=PKModelComparison(
            candidates=[],
            selected_model="1-compartment",
            selection_rationale="Synthetic selection.",
        ),
        covariate_effects=[],
        exposure_response=[
            _exposure_result("efficacy", 0.1, 0.4),
            _exposure_result("safety", -0.2, 0.3),
        ],
        diagnostics=DiagnosticsSummary(
            pk_model_converged=True,
            parameter_covariance_valid=True,
            predictive_check_passed=False,
            major_residual_bias=True,
            critical_flags=critical_flags,
            summary="Synthetic diagnostics.",
        ),
        dosing_recommendations=[
            DosingRecommendation(
                subgroup="overall population",
                action="maintain_current_dose",
                recommended_dose_mg=100.0,
                evidence_basis="observed",
                rationale=recommendation_text,
                confidence="moderate",
                validation_required=[],
            )
        ],
        limitations=[],
    )


def _decision(finding: ReviewFinding) -> ReviewerDecision:
    return ReviewerDecision(
        run_id="review-run",
        generated_at=datetime.now(timezone.utc),
        status="revise",
        findings=[finding],
        reviewer_notes="Original reviewer note.",
    )


@pytest.fixture(autouse=True)
def _isolated_override_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reviewer_module,
        "REVIEWER_OVERRIDE_LOG_PATH",
        tmp_path / "reviewer_overrides.jsonl",
    )


def test_acknowledged_critical_flag_is_removed_and_revise_becomes_approve() -> None:
    flag = "Patient-level aggregate predictive check failed."
    summary = _summary([flag], "Additional context: {}".format(flag))
    decision = _decision(
        ReviewFinding(
            severity="critical",
            category="dosing",
            issue="{} was not addressed in dosing.".format(flag),
            evidence="The diagnostic was ignored.",
            required_action="Address the flag.",
        )
    )

    validated = validate_review_findings(decision, summary)

    assert validated.findings == []
    assert validated.status == "approve"
    assert validated.reviewer_notes.startswith(
        "Status changed from REVISE to APPROVE by deterministic post-review "
        "validation"
    )
    assert "Original LLM reviewer_notes: Original reviewer note." in (
        validated.reviewer_notes
    )


def test_missing_evidence_claim_is_removed_when_both_types_are_present() -> None:
    summary = _summary([], "No diagnostic flags.")
    decision = _decision(
        ReviewFinding(
            severity="major",
            category="interpretation",
            issue="Safety evidence is missing from the analysis.",
            evidence="No safety assessment was supplied.",
        )
    )

    validated = validate_review_findings(decision, summary)

    assert validated.findings == []
    assert validated.status == "approve"


def test_supported_moderate_confidence_finding_is_removed() -> None:
    summary = _summary([], "Efficacy significant; safety non-significant.")
    decision = _decision(
        ReviewFinding(
            severity="critical",
            category="dosing",
            issue="Overall population confidence is too high.",
            evidence="The overall recommendation uses moderate confidence.",
            required_action="Lower the confidence.",
        )
    )

    validated = validate_review_findings(decision, summary)

    assert validated.findings == []
    assert validated.status == "approve"


def test_supported_insufficient_evidence_finding_is_removed() -> None:
    summary = _summary([], "Efficacy significant; safety non-significant.")
    summary.dosing_recommendations.append(
        DosingRecommendation(
            subgroup="upper weight quartile",
            action="insufficient_evidence",
            recommended_dose_mg=None,
            evidence_basis="observed",
            rationale="A specific dose requires exposure-matching simulation.",
            confidence="low",
            validation_required=["exposure-matching simulation"],
        )
    )
    decision = _decision(
        ReviewFinding(
            severity="major",
            category="interpretation",
            issue="The insufficient evidence conclusion lacks a dose proposal.",
            evidence="Weight has a material effect.",
            required_action="Provide a specific dose.",
        )
    )

    validated = validate_review_findings(decision, summary)

    assert validated.findings == []
    assert validated.status == "approve"


def test_nullable_aic_bic_finding_is_removed_when_paired_aicc_is_documented() -> None:
    summary = _summary([], "Efficacy significant; safety non-significant.")
    summary.pk_model.selection_rationale = "Paired delta-AICc favored the model."
    decision = _decision(
        ReviewFinding(
            severity="minor",
            category="diagnostics",
            issue="AIC/BIC values are null despite model selection logic.",
            evidence="Candidate AIC/BIC fields are null.",
            required_action="Populate AIC/BIC.",
        )
    )

    validated = validate_review_findings(decision, summary)

    assert validated.findings == []
    assert validated.status == "approve"


def test_genuine_traceability_finding_survives_untouched() -> None:
    summary = _summary([], "Efficacy significant; safety non-significant.")
    finding = ReviewFinding(
        severity="major",
        category="reporting",
        issue="The report does not identify the input dataset paths.",
        evidence="The traceability table omits source filenames.",
        required_action="Add the exact source paths.",
    )

    validated = validate_review_findings(_decision(finding), summary)

    assert validated.findings == [finding]
    assert validated.status == "revise"
