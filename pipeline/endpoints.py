"""Derive patient-level efficacy and safety analysis endpoints."""

from typing import Any, Dict, List, Set

import numpy as np
import pandas as pd

try:
    from pipeline.data_loading import LoadedData, load_all
except ModuleNotFoundError as exc:
    if exc.name != "pipeline":
        raise
    from data_loading import LoadedData, load_all


def derive_endpoints(loaded: LoadedData) -> pd.DataFrame:
    """Return one patient-level dataframe with derived analysis endpoints."""
    patient_endpoints = loaded["patients"].copy()
    biomarkers = loaded["pd_biomarkers"]

    patient_endpoints["any_adverse_event"] = patient_endpoints["adverse_event"]
    patient_endpoints["grade2plus_adverse_event"] = (
        patient_endpoints["ae_grade"] >= 2
    ).astype(int)

    week_values = pd.to_numeric(biomarkers["week"], errors="coerce")
    week12_rows = biomarkers.loc[
        (week_values == 12)
        & biomarkers["inflammatory_marker_reduction_pct"].notna()
    ]
    patient_ids: Set[str] = set(
        patient_endpoints["patient_id"].dropna().astype(str)
    )
    week12_patient_ids: Set[str] = set(
        week12_rows["patient_id"].dropna().astype(str)
    )
    missing_week12_patient_ids = patient_ids - week12_patient_ids
    if missing_week12_patient_ids:
        missing_ids = ", ".join(sorted(missing_week12_patient_ids))
        raise ValueError(
            "Missing week 12 biomarker reading for patient_id value(s): "
            f"{missing_ids}"
        )

    biomarker_records: List[Dict[str, Any]] = []
    for patient_id, patient_biomarkers in biomarkers.groupby("patient_id"):
        ordered_biomarkers = patient_biomarkers.assign(
            _week=pd.to_numeric(patient_biomarkers["week"], errors="coerce"),
            _reduction=pd.to_numeric(
                patient_biomarkers["inflammatory_marker_reduction_pct"],
                errors="coerce",
            ),
        )
        ordered_biomarkers = ordered_biomarkers.loc[
            ordered_biomarkers["_week"].between(0, 12, inclusive="both")
        ].sort_values("_week")
        weeks = ordered_biomarkers["_week"].to_numpy(dtype=float)
        reductions = ordered_biomarkers["_reduction"].to_numpy(dtype=float)
        week12_reduction = ordered_biomarkers.loc[
            ordered_biomarkers["_week"] == 12,
            "_reduction",
        ].iloc[0]

        biomarker_records.append(
            {
                "patient_id": patient_id,
                "biomarker_reduction_week12": float(week12_reduction),
                "biomarker_reduction_auc_week0_12": float(
                    np.trapezoid(reductions, weeks)
                ),
                "biomarker_linear_slope_pct_per_week": float(
                    np.polyfit(weeks, reductions, deg=1)[0]
                ),
            }
        )

    biomarker_endpoints = pd.DataFrame.from_records(biomarker_records)
    biomarker_endpoints["patient_id"] = biomarker_endpoints["patient_id"].astype(
        patient_endpoints["patient_id"].dtype
    )
    return patient_endpoints.merge(
        biomarker_endpoints,
        on="patient_id",
        how="left",
        validate="one_to_one",
    )


if __name__ == "__main__":
    endpoints = derive_endpoints(load_all())
    derived_columns = [
        "biomarker_reduction_week12",
        "biomarker_reduction_auc_week0_12",
        "biomarker_linear_slope_pct_per_week",
        "grade2plus_adverse_event",
    ]
    print(f"shape: {endpoints.shape}")
    print(f"columns: {endpoints.columns.tolist()}")
    print("dtypes:")
    print(endpoints.dtypes)
    print("derived endpoint summary:")
    print(endpoints[derived_columns].describe())
