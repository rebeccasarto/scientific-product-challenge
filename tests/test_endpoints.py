"""Tests for patient-level endpoint derivation."""

from typing import Dict, List, Union

import pandas as pd
import pytest

from pipeline.data_loading import LoadedData, StudyMetadata
from pipeline.endpoints import derive_endpoints


def _synthetic_loaded_data() -> LoadedData:
    patient_ids = ["P0", "P1", "P2", "P3"]
    patients = pd.DataFrame(
        {
            "patient_id": patient_ids,
            "adverse_event": [0, 1, 1, 0],
            "ae_grade": [0, 1, 2, 3],
            "clinical_response": [0, 1, 1, 0],
            "disease_score_change": [-1.0, -2.0, -3.0, -4.0],
        }
    )

    biomarker_rows: List[Dict[str, Union[str, float]]] = []
    for patient_number, patient_id in enumerate(patient_ids):
        for week in (0, 6, 12):
            biomarker_rows.append(
                {
                    "patient_id": patient_id,
                    "week": float(week),
                    "inflammatory_marker_reduction_pct": float(
                        week + (2 * patient_number)
                    ),
                }
            )
    pd_biomarkers = pd.DataFrame(biomarker_rows)

    metadata: StudyMetadata = {
        "n_patients": 4,
        "dose_mg": 100.0,
        "route": "IV bolus",
        "primary_endpoint": "clinical response at week 12",
        "safety_endpoint": "adverse event grade 2 or higher",
        "resolved_data_dir": "synthetic",
        "row_counts": {
            "patients": 4,
            "pk_concentrations": 0,
            "pd_biomarkers": len(pd_biomarkers),
        },
    }
    return {
        "patients": patients,
        "pk_concentrations": pd.DataFrame(),
        "pd_biomarkers": pd_biomarkers,
        "metadata": metadata,
    }


def test_grade2plus_adverse_event_threshold() -> None:
    endpoints = derive_endpoints(_synthetic_loaded_data())

    assert endpoints["grade2plus_adverse_event"].tolist() == [0, 0, 1, 1]


def test_any_adverse_event_is_raw_passthrough() -> None:
    loaded = _synthetic_loaded_data()
    endpoints = derive_endpoints(loaded)

    assert endpoints["any_adverse_event"].tolist() == loaded["patients"][
        "adverse_event"
    ].tolist()


def test_week12_biomarker_reduction_is_extracted() -> None:
    endpoints = derive_endpoints(_synthetic_loaded_data())

    assert endpoints["biomarker_reduction_week12"].tolist() == [
        12.0,
        14.0,
        16.0,
        18.0,
    ]


def test_biomarker_auc_and_slope_match_hand_calculation() -> None:
    endpoints = derive_endpoints(_synthetic_loaded_data()).set_index("patient_id")

    assert endpoints.loc["P0", "biomarker_reduction_auc_week0_12"] == pytest.approx(
        72.0
    )
    assert endpoints.loc[
        "P0", "biomarker_linear_slope_pct_per_week"
    ] == pytest.approx(1.0)
