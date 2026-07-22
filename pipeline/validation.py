"""Assess loaded data quality before PK/PD modeling."""

from math import isclose
from typing import Any, Dict, List, Optional, Set, Tuple, TypedDict

import pandas as pd

try:
    from pipeline.data_loading import LoadedData, load_all
except ModuleNotFoundError as exc:
    if exc.name != "pipeline":
        raise
    from data_loading import LoadedData, load_all


class ValidationReport(TypedDict):
    errors: List[str]
    warnings: List[str]
    summary: Dict[str, Any]


def _format_patient_ids(patient_ids: Set[str]) -> str:
    return ", ".join(sorted(patient_ids))


def _patient_id_set(dataframe: pd.DataFrame) -> Set[str]:
    return set(dataframe["patient_id"].dropna().astype(str))


def _common_timepoint_count(
    dataframe: pd.DataFrame,
) -> Tuple[Optional[int], Dict[str, int]]:
    counts = dataframe.dropna(subset=["patient_id"]).groupby("patient_id").size()
    if counts.empty:
        return None, {}

    common_count = int(counts.mode().iloc[0])
    irregular_counts = {
        str(patient_id): int(count)
        for patient_id, count in counts.items()
        if int(count) != common_count
    }
    return common_count, irregular_counts


def _duplicate_key_values(
    dataframe: pd.DataFrame,
    key_columns: Tuple[str, ...],
) -> List[str]:
    duplicated_rows = dataframe.loc[
        dataframe.duplicated(subset=list(key_columns), keep=False),
        list(key_columns),
    ].drop_duplicates()
    return [
        repr(tuple(values)) if len(key_columns) > 1 else repr(values[0])
        for values in duplicated_rows.itertuples(index=False, name=None)
    ]


def _format_schedule(values: Set[Any]) -> str:
    return repr(sorted(values, key=lambda value: str(value)))


def validate(loaded: LoadedData) -> ValidationReport:
    """Run data-quality checks and return errors, warnings, and summary values."""
    patients = loaded["patients"]
    pk_concentrations = loaded["pk_concentrations"]
    pd_biomarkers = loaded["pd_biomarkers"]
    metadata = loaded["metadata"]

    errors: List[str] = []
    warnings: List[str] = []
    summary: Dict[str, Any] = {
        "row_counts": {
            "patients": len(patients),
            "pk_concentrations": len(pk_concentrations),
            "pd_biomarkers": len(pd_biomarkers),
        }
    }

    missing_value_counts: Dict[str, Dict[str, int]] = {}
    datasets = {
        "patients": patients,
        "pk_concentrations": pk_concentrations,
        "pd_biomarkers": pd_biomarkers,
    }
    for dataset_name, dataframe in datasets.items():
        dataset_missing = {
            str(column): int(count)
            for column, count in dataframe.isna().sum().items()
            if int(count) > 0
        }
        missing_value_counts[dataset_name] = dataset_missing
        for column, count in dataset_missing.items():
            warnings.append(
                f"{dataset_name}.{column} contains {count} missing value(s)"
            )
    summary["missing_value_counts"] = missing_value_counts

    duplicate_key_definitions = (
        ("patients", patients, ("patient_id",)),
        (
            "pk_concentrations",
            pk_concentrations,
            ("patient_id", "time_hours"),
        ),
        ("pd_biomarkers", pd_biomarkers, ("patient_id", "week")),
    )
    duplicate_key_counts: Dict[str, int] = {}
    for dataset_name, dataframe, key_columns in duplicate_key_definitions:
        duplicate_keys = _duplicate_key_values(dataframe, key_columns)
        duplicate_key_counts[dataset_name] = len(duplicate_keys)
        if duplicate_keys:
            errors.append(
                f"Duplicate key(s) in {dataset_name} for {key_columns}: "
                f"{', '.join(duplicate_keys)}"
            )
    summary["n_duplicate_keys"] = sum(duplicate_key_counts.values())
    summary["duplicate_key_counts"] = duplicate_key_counts

    patient_id_sets = {
        "patients": _patient_id_set(patients),
        "pk_concentrations": _patient_id_set(pk_concentrations),
        "pd_biomarkers": _patient_id_set(pd_biomarkers),
    }
    summary["unique_patient_counts"] = {
        dataset_name: len(patient_ids)
        for dataset_name, patient_ids in patient_id_sets.items()
    }
    patients_ids = patient_id_sets["patients"]
    pk_patient_ids = patient_id_sets["pk_concentrations"]
    biomarker_patient_ids = patient_id_sets["pd_biomarkers"]
    join_integrity_differences = (
        (
            "PK patient_id values not found in patients",
            pk_patient_ids - patients_ids,
        ),
        (
            "PD biomarker patient_id values not found in patients",
            biomarker_patient_ids - patients_ids,
        ),
        (
            "Patient_id values with no PK concentration rows",
            patients_ids - pk_patient_ids,
        ),
        (
            "Patient_id values with no PD biomarker rows",
            patients_ids - biomarker_patient_ids,
        ),
    )
    join_integrity_counts: Dict[str, int] = {}
    for description, differing_ids in join_integrity_differences:
        join_integrity_counts[description] = len(differing_ids)
        if differing_ids:
            errors.append(f"{description}: {_format_patient_ids(differing_ids)}")
    summary["join_integrity_difference_counts"] = join_integrity_counts

    expected_n_patients = metadata["n_patients"]
    if expected_n_patients != len(patients):
        errors.append(
            "Metadata n_patients mismatch: "
            f"metadata={expected_n_patients}, patients rows={len(patients)}"
        )

    expected_dose_mg = metadata["dose_mg"]
    observed_doses = pk_concentrations["dose_mg"].dropna().unique().tolist()
    mismatched_doses: List[Any] = []
    for observed_dose in observed_doses:
        try:
            matches_expected = isclose(
                float(observed_dose),
                float(expected_dose_mg),
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
        except (TypeError, ValueError):
            matches_expected = False
        if not matches_expected:
            mismatched_doses.append(observed_dose)
    summary["observed_dose_mg_values"] = observed_doses
    if mismatched_doses:
        errors.append(
            "PK dose_mg values do not match metadata dose_mg "
            f"({expected_dose_mg}): {mismatched_doses}"
        )

    invalid_clinical_response = patients["clinical_response"].notna() & ~patients[
        "clinical_response"
    ].isin([0, 1])
    invalid_adverse_event = patients["adverse_event"].notna() & ~patients[
        "adverse_event"
    ].isin([0, 1])
    numeric_ae_grade = pd.to_numeric(patients["ae_grade"], errors="coerce")
    invalid_ae_grade = patients["ae_grade"].notna() & (
        numeric_ae_grade.isna() | (numeric_ae_grade < 0) | (numeric_ae_grade > 3)
    )
    numeric_adverse_event = pd.to_numeric(
        patients["adverse_event"], errors="coerce"
    )
    endpoint_values_present = patients["adverse_event"].notna() & patients[
        "ae_grade"
    ].notna()
    adverse_event_grade_mismatch = endpoint_values_present & (
        (numeric_adverse_event == 1) != (numeric_ae_grade > 0)
    )

    endpoint_masks = {
        "invalid_clinical_response": invalid_clinical_response,
        "invalid_adverse_event": invalid_adverse_event,
        "invalid_ae_grade": invalid_ae_grade,
        "adverse_event_ae_grade_mismatch": adverse_event_grade_mismatch,
    }
    endpoint_inconsistency_counts = {
        check_name: int(mask.sum()) for check_name, mask in endpoint_masks.items()
    }
    endpoint_inconsistent_rows: Set[Any] = set()
    for mask in endpoint_masks.values():
        endpoint_inconsistent_rows.update(patients.index[mask].tolist())
    summary["n_endpoint_inconsistencies"] = len(endpoint_inconsistent_rows)
    summary["endpoint_inconsistency_counts"] = endpoint_inconsistency_counts

    if invalid_clinical_response.any():
        invalid_values = patients.loc[
            invalid_clinical_response, "clinical_response"
        ].unique().tolist()
        errors.append(
            "patients.clinical_response contains values outside {0, 1}: "
            f"{invalid_values}"
        )
    if invalid_adverse_event.any():
        invalid_values = patients.loc[
            invalid_adverse_event, "adverse_event"
        ].unique().tolist()
        errors.append(
            "patients.adverse_event contains values outside {0, 1}: "
            f"{invalid_values}"
        )
    if invalid_ae_grade.any():
        invalid_values = patients.loc[invalid_ae_grade, "ae_grade"].unique().tolist()
        errors.append(
            "patients.ae_grade contains values outside the inclusive 0-3 range: "
            f"{invalid_values}"
        )
    if adverse_event_grade_mismatch.any():
        mismatched_rows = patients.loc[
            adverse_event_grade_mismatch,
            ["patient_id", "adverse_event", "ae_grade"],
        ].to_dict(orient="records")
        errors.append(
            "patients adverse_event and ae_grade disagree "
            "(expected adverse_event == 1 iff ae_grade > 0): "
            f"{mismatched_rows}"
        )

    patient_site_lookup = (
        patients.dropna(subset=["patient_id"])
        .drop_duplicates(subset=["patient_id"], keep="first")
        .set_index("patient_id")["site"]
    )
    expected_pk_sites = pk_concentrations["patient_id"].map(patient_site_lookup)
    site_values_present = pk_concentrations["site"].notna() & expected_pk_sites.notna()
    site_mismatch_mask = site_values_present & (
        pk_concentrations["site"] != expected_pk_sites
    )
    site_mismatch_ids = set(
        pk_concentrations.loc[site_mismatch_mask, "patient_id"].astype(str)
    )
    summary["n_site_mismatches"] = len(site_mismatch_ids)
    if site_mismatch_ids:
        errors.append(
            "PK site does not match patients site for patient_id value(s): "
            f"{_format_patient_ids(site_mismatch_ids)}"
        )

    plausibility_checks = (
        ("patients", patients, "age"),
        ("patients", patients, "weight_kg"),
        ("patients", patients, "creatinine_clearance_ml_min"),
        ("pk_concentrations", pk_concentrations, "concentration_mg_l"),
    )
    nonpositive_counts: Dict[str, int] = {}
    for dataset_name, dataframe, column in plausibility_checks:
        numeric_values = pd.to_numeric(dataframe[column], errors="coerce")
        count = int((numeric_values <= 0).sum())
        nonpositive_counts[f"{dataset_name}.{column}"] = count
        if count:
            warnings.append(
                f"{dataset_name}.{column} contains {count} negative or zero value(s)"
            )
    summary["nonpositive_value_counts"] = nonpositive_counts

    ages = pd.to_numeric(patients["age"], errors="coerce")
    implausible_age_count = int(((ages < 18) | (ages > 100)).sum())
    if implausible_age_count:
        warnings.append(
            "patients.age contains "
            f"{implausible_age_count} value(s) outside the 18-100 year range"
        )

    weights = pd.to_numeric(patients["weight_kg"], errors="coerce")
    implausible_weight_count = int(((weights < 30) | (weights > 200)).sum())
    if implausible_weight_count:
        warnings.append(
            "patients.weight_kg contains "
            f"{implausible_weight_count} value(s) outside the 30-200 kg range"
        )
    summary["physiological_range_counts"] = {
        "age_outside_18_100": implausible_age_count,
        "weight_kg_outside_30_200": implausible_weight_count,
    }

    pk_common_count, pk_irregular_counts = _common_timepoint_count(pk_concentrations)
    biomarker_common_count, biomarker_irregular_counts = _common_timepoint_count(
        pd_biomarkers
    )
    summary["common_timepoints_per_patient"] = {
        "pk_concentrations": pk_common_count,
        "pd_biomarkers": biomarker_common_count,
    }
    summary["irregular_timepoint_counts"] = {
        "pk_concentrations": pk_irregular_counts,
        "pd_biomarkers": biomarker_irregular_counts,
    }
    if pk_irregular_counts:
        warnings.append(
            "PK timepoint counts differ from the common count "
            f"of {pk_common_count}: {pk_irregular_counts}"
        )
    if biomarker_irregular_counts:
        warnings.append(
            "Biomarker timepoint counts differ from the common count "
            f"of {biomarker_common_count}: {biomarker_irregular_counts}"
        )

    expected_pk_schedule: Set[Any] = {0.25, 0.5, 1, 2, 4, 8, 12, 24}
    expected_biomarker_schedule: Set[Any] = {0, 2, 4, 8, 12}
    pk_schedule_deviations: Dict[str, Dict[str, List[Any]]] = {}
    for patient_id, patient_rows in pk_concentrations.dropna(
        subset=["patient_id"]
    ).groupby("patient_id"):
        observed_schedule = set(patient_rows["time_hours"].dropna().tolist())
        if observed_schedule != expected_pk_schedule:
            patient_id_string = str(patient_id)
            pk_schedule_deviations[patient_id_string] = {
                "observed": sorted(observed_schedule, key=lambda value: str(value)),
                "expected": sorted(
                    expected_pk_schedule, key=lambda value: str(value)
                ),
            }
            warnings.append(
                f"PK schedule deviation for patient_id {patient_id_string}: "
                f"observed={_format_schedule(observed_schedule)}, "
                f"expected={_format_schedule(expected_pk_schedule)}"
            )

    biomarker_schedule_deviations: Dict[str, Dict[str, List[Any]]] = {}
    for patient_id, patient_rows in pd_biomarkers.dropna(
        subset=["patient_id"]
    ).groupby("patient_id"):
        observed_schedule = set(patient_rows["week"].dropna().tolist())
        if observed_schedule != expected_biomarker_schedule:
            patient_id_string = str(patient_id)
            biomarker_schedule_deviations[patient_id_string] = {
                "observed": sorted(observed_schedule, key=lambda value: str(value)),
                "expected": sorted(
                    expected_biomarker_schedule, key=lambda value: str(value)
                ),
            }
            warnings.append(
                f"PD biomarker schedule deviation for patient_id {patient_id_string}: "
                f"observed={_format_schedule(observed_schedule)}, "
                f"expected={_format_schedule(expected_biomarker_schedule)}"
            )

    schedule_deviation_counts = {
        "pk_concentrations": len(pk_schedule_deviations),
        "pd_biomarkers": len(biomarker_schedule_deviations),
    }
    summary["n_schedule_deviations"] = sum(schedule_deviation_counts.values())
    summary["schedule_deviation_counts"] = schedule_deviation_counts
    summary["schedule_deviations"] = {
        "pk_concentrations": pk_schedule_deviations,
        "pd_biomarkers": biomarker_schedule_deviations,
    }

    return {"errors": errors, "warnings": warnings, "summary": summary}


def raise_if_errors(report: ValidationReport) -> None:
    """Raise a single ValueError containing every blocking validation error."""
    if report["errors"]:
        formatted_errors = "\n".join(f"- {error}" for error in report["errors"])
        raise ValueError(f"Data validation failed:\n{formatted_errors}")


if __name__ == "__main__":
    validation_report = validate(load_all())
    print(validation_report)
