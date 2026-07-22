"""Load the supplied PK/PD datasets and study metadata."""

import re
from pathlib import Path
from typing import Dict, TypedDict, Union

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


class StudyMetadata(TypedDict):
    n_patients: int
    dose_mg: float
    route: str
    primary_endpoint: str
    safety_endpoint: str
    resolved_data_dir: str
    row_counts: Dict[str, int]


class LoadedData(TypedDict):
    patients: pd.DataFrame
    pk_concentrations: pd.DataFrame
    pd_biomarkers: pd.DataFrame
    metadata: StudyMetadata


def parse_dose_mg(value: str) -> float:
    """Parse a dose formatted as a number followed by a case-insensitive ``mg``."""
    stripped_value = value.strip()
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+mg",
        stripped_value,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError(
            f"Invalid dose format: {value!r}; expected a numeric value followed by ' mg'"
        )
    return float(match.group(1))


def load_metadata(
    data_dir: Union[str, Path] = DEFAULT_DATA_DIR,
) -> StudyMetadata:
    """Load and parse study metadata from ``metadata.txt``."""
    resolved_data_dir = Path(data_dir).resolve()
    metadata_path = resolved_data_dir / "metadata.txt"
    raw_metadata: Dict[str, str] = {}

    with metadata_path.open(encoding="utf-8") as metadata_file:
        for line_number, line in enumerate(metadata_file, start=1):
            stripped_line = line.strip()
            if not stripped_line:
                continue
            if ":" not in stripped_line:
                raise ValueError(
                    "Invalid metadata.txt line without a colon "
                    f"(line {line_number}): {stripped_line!r}"
                )
            key, value = stripped_line.split(":", maxsplit=1)
            raw_metadata[key.strip()] = value.strip()

    required_keys = (
        "n_patients",
        "dose",
        "route",
        "primary_endpoint",
        "safety_endpoint",
    )
    for key in required_keys:
        if key not in raw_metadata:
            raise KeyError(f"metadata.txt is missing required key: {key}")

    return {
        "n_patients": int(raw_metadata["n_patients"]),
        "dose_mg": parse_dose_mg(raw_metadata["dose"]),
        "route": raw_metadata["route"],
        "primary_endpoint": raw_metadata["primary_endpoint"],
        "safety_endpoint": raw_metadata["safety_endpoint"],
        "resolved_data_dir": str(resolved_data_dir),
        "row_counts": {},
    }


def _read_dataset(
    path: Path,
    logical_name: str,
) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype={"patient_id": "string"})
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Required {logical_name} dataset not found: {path}"
        ) from exc


def load_all(data_dir: Union[str, Path] = DEFAULT_DATA_DIR) -> LoadedData:
    """Load all supplied datasets and metadata from ``data_dir``."""
    resolved_data_dir = Path(data_dir).resolve()
    patients = _read_dataset(resolved_data_dir / "patients.csv", "patients")
    pk_concentrations = _read_dataset(
        resolved_data_dir / "pk_concentrations.csv",
        "PK",
    )
    pd_biomarkers = _read_dataset(
        resolved_data_dir / "pd_biomarkers.csv",
        "PD biomarkers",
    )
    metadata = load_metadata(resolved_data_dir)
    metadata["resolved_data_dir"] = str(resolved_data_dir)
    metadata["row_counts"] = {
        "patients": len(patients),
        "pk_concentrations": len(pk_concentrations),
        "pd_biomarkers": len(pd_biomarkers),
    }

    return {
        "patients": patients,
        "pk_concentrations": pk_concentrations,
        "pd_biomarkers": pd_biomarkers,
        "metadata": metadata,
    }


if __name__ == "__main__":
    loaded = load_all()
    for dataset_name in ("patients", "pk_concentrations", "pd_biomarkers"):
        dataframe = loaded[dataset_name]
        print(f"{dataset_name}: shape={dataframe.shape}")
        print(dataframe.dtypes)
    print(f"metadata: {loaded['metadata']}")
    print(f"row_counts: {loaded['metadata']['row_counts']}")
    print(f"resolved_data_dir: {loaded['metadata']['resolved_data_dir']}")
