"""Tests for exploratory exposure-response modeling."""

from typing import Dict, List, Union

import pandas as pd

from pipeline.data_loading import LoadedData, StudyMetadata
from pipeline.exposure_response import fit_exposure_response


def test_deterministic_auc_response_has_positive_significant_coefficient() -> None:
    patient_ids = [f"P{index:02d}" for index in range(40)]
    auc_values = [50.0 + (5.0 * index) for index in range(40)]
    clinical_response = [int(auc > 145.0) for auc in auc_values]
    adverse_event = [index % 2 for index in range(40)]
    patients = pd.DataFrame(
        {
            "patient_id": patient_ids,
            "weight_kg": [60.0 + (index % 10) * 2.0 for index in range(40)],
            "clinical_response": clinical_response,
            "disease_score_change": [-float(value) for value in clinical_response],
            "adverse_event": adverse_event,
            "ae_grade": [2 if event else 0 for event in adverse_event],
        }
    )

    biomarker_rows: List[Dict[str, Union[str, float]]] = []
    for patient_id in patient_ids:
        for week in (0.0, 6.0, 12.0):
            biomarker_rows.append(
                {
                    "patient_id": patient_id,
                    "week": week,
                    "inflammatory_marker_reduction_pct": 2.0 * week,
                }
            )
    pd_biomarkers = pd.DataFrame(biomarker_rows)
    metadata: StudyMetadata = {
        "n_patients": 40,
        "dose_mg": 100.0,
        "route": "IV bolus",
        "primary_endpoint": "clinical response at week 12",
        "safety_endpoint": "adverse event grade 2 or higher",
        "resolved_data_dir": "synthetic",
        "row_counts": {
            "patients": 40,
            "pk_concentrations": 0,
            "pd_biomarkers": len(pd_biomarkers),
        },
    }
    loaded: LoadedData = {
        "patients": patients,
        "pk_concentrations": pd.DataFrame(),
        "pd_biomarkers": pd_biomarkers,
        "metadata": metadata,
    }
    per_patient_pk = pd.DataFrame(
        {
            "patient_id": patient_ids,
            "model_type": ["1-compartment"] * 40,
            "converged": [True] * 40,
            "CL": [100.0 / auc for auc in auc_values],
            "dose_mg": [100.0] * 40,
        }
    )
    per_patient_pk.attrs["dose_mg"] = metadata["dose_mg"]

    results = fit_exposure_response(loaded, per_patient_pk, "1-compartment")
    univariate_efficacy = next(
        result
        for result in results
        if result.endpoint == "clinical_response"
        and result.model_form == "logistic_univariate"
    )

    assert univariate_efficacy.converged is True
    assert univariate_efficacy.effect_estimate is not None
    assert univariate_efficacy.effect_estimate > 0
    assert univariate_efficacy.ci_lower is not None
    assert univariate_efficacy.ci_lower > 0
