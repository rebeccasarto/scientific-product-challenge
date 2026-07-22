"""Run the complete analytical PK/PD pipeline and save its validated summary."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import List, Optional

from agents.schemas import AnalysisSummary
from pipeline.covariates import screen_covariates
from pipeline.data_loading import load_all
from pipeline.diagnostics import summarize_diagnostics
from pipeline.dosing import generate_dosing_recommendations
from pipeline.eda import run_eda
from pipeline.exposure_response import fit_exposure_response
from pipeline.pk import fit_population_pk
from pipeline.validation import raise_if_errors, validate


PROJECT_ROOT = Path(__file__).resolve().parent
ANALYSIS_SUMMARY_PATH = PROJECT_ROOT / "results" / "final" / "analysis_summary.json"
PARTNER_REPORT_PATH = PROJECT_ROOT / "results" / "final" / "partner_report.md"


def _input_file_paths(resolved_data_dir: str) -> List[str]:
    """Return project-relative paths for the three analytical input datasets."""
    data_dir = Path(resolved_data_dir).resolve()
    try:
        relative_data_dir = data_dir.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(
            "The analysis data directory must be inside the project root."
        ) from exc
    return [
        str(relative_data_dir / "patients.csv"),
        str(relative_data_dir / "pk_concentrations.csv"),
        str(relative_data_dir / "pd_biomarkers.csv"),
    ]


def _serialize_summary(summary: AnalysisSummary) -> str:
    """Serialize with either the Pydantic v2 or v1 API."""
    if hasattr(summary, "model_dump_json"):
        return summary.model_dump_json(indent=2)
    return summary.json(indent=2)


def run_analysis(
    run_id: Optional[str] = None,
    run_agents: bool = True,
) -> AnalysisSummary:
    """Run all core analytical stages and persist an ``AnalysisSummary``."""
    effective_run_id = run_id or datetime.now(timezone.utc).strftime(
        "run_%Y%m%d_%H%M%S"
    )

    loaded = load_all()
    validation_report = validate(loaded)
    raise_if_errors(validation_report)

    pk_comparison, per_patient_pk = fit_population_pk(loaded)
    selected_model = pk_comparison.selected_model
    if selected_model is None:
        raise ValueError("PK model comparison did not select a structural model.")

    covariate_effects = screen_covariates(
        per_patient_pk,
        loaded["patients"],
        selected_model,
    )
    exposure_response_results = fit_exposure_response(
        loaded,
        per_patient_pk,
        selected_model,
    )
    diagnostics_summary = summarize_diagnostics(
        pk_comparison,
        per_patient_pk,
        covariate_effects,
        exposure_response_results,
        loaded["pk_concentrations"],
    )
    dosing_recommendations = generate_dosing_recommendations(
        covariate_effects,
        exposure_response_results,
        diagnostics_summary,
        reference_dose_mg=loaded["metadata"]["dose_mg"],
    )

    eda_succeeded = True
    try:
        run_eda(loaded)
    except Exception as exc:  # Supporting visuals must not block core analysis.
        eda_succeeded = False
        print(
            "WARNING: EDA generation failed, continuing without visuals: "
            "{}".format(exc),
            file=sys.stderr,
        )

    limitations = [
        "This analysis uses a two-stage approximation rather than a full "
        "nonlinear mixed-effects (NLME) population PK model.",
        "The single studied dose level precludes assessment of dose "
        "proportionality.",
        "Covariate effects are exploratory associations and are not definitive "
        "population PK covariates.",
    ]
    if diagnostics_summary.critical_flags:
        limitations.append(
            "Diagnostic limitations were identified; see the diagnostics "
            "section before interpreting the analytical conclusions."
        )

    analysis_summary = AnalysisSummary(
        schema_version="1.0",
        run_id=effective_run_id,
        generated_at=datetime.now(timezone.utc),
        input_files=_input_file_paths(
            loaded["metadata"]["resolved_data_dir"]
        ),
        pk_model=pk_comparison,
        covariate_effects=covariate_effects,
        exposure_response=exposure_response_results,
        diagnostics=diagnostics_summary,
        dosing_recommendations=dosing_recommendations,
        limitations=limitations,
    )

    ANALYSIS_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_SUMMARY_PATH.write_text(
        _serialize_summary(analysis_summary) + "\n",
        encoding="utf-8",
    )
    produced_files = ["results/final/analysis_summary.json"]

    if run_agents:
        try:
            from agents.orchestrator import run_reviewed_report

            report, reviewer_decision, release_decision = run_reviewed_report(
                analysis_summary,
                effective_run_id,
            )
            PARTNER_REPORT_PATH.write_text(report, encoding="utf-8")
            produced_files.extend(
                [
                    "results/final/release_decision.json",
                    "results/final/partner_report.md",
                ]
            )
            print("Reviewer status: {}".format(reviewer_decision.status))
            print("Release decision: {}".format(release_decision.decision))
        except Exception as exc:
            print(
                "WARNING: Agent pipeline failed, continuing with analytical "
                "results only: {}".format(exc),
                file=sys.stderr,
            )

    material_count = sum(
        effect.clinically_material for effect in covariate_effects
    )
    action_counts = Counter(
        recommendation.action for recommendation in dosing_recommendations
    )
    print("Selected PK model: {}".format(selected_model))
    print("Clinically material covariate effects: {}".format(material_count))
    print("Dosing recommendations by action: {}".format(dict(action_counts)))
    print("EDA: {}".format("succeeded" if eda_succeeded else "skipped"))
    print("Saved analysis summary: {}".format(ANALYSIS_SUMMARY_PATH))
    print("Produced files: {}".format(produced_files))

    return analysis_summary


if __name__ == "__main__":
    run_analysis()
