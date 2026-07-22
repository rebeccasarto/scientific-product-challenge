"""Create concise visual and descriptive summaries of validated study data."""

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

matplotlib_config_dir = Path(tempfile.gettempdir()) / "iollo-matplotlib"
matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config_dir))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.data_loading import LoadedData, load_all


def run_eda(
    loaded: LoadedData,
    output_dir: str = "results/baseline",
) -> Dict[str, Any]:
    """Generate three descriptive plots and a compact observational summary."""
    patients = loaded["patients"]
    pk_concentrations = loaded["pk_concentrations"]
    pd_biomarkers = loaded["pd_biomarkers"]
    metadata = loaded["metadata"]

    resolved_output_dir = Path(output_dir).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    plot_paths: Dict[str, str] = {}

    concentration_path = resolved_output_dir / "concentration_time_profiles.png"
    figure, axis = plt.subplots(figsize=(9, 6))
    for _, patient_profile in pk_concentrations.groupby("patient_id"):
        ordered_profile = patient_profile.sort_values("time_hours")
        axis.plot(
            ordered_profile["time_hours"],
            ordered_profile["concentration_mg_l"],
            color="#4C78A8",
            alpha=0.15,
            linewidth=0.8,
        )
    median_concentrations = (
        pk_concentrations.groupby("time_hours", as_index=False)[
            "concentration_mg_l"
        ]
        .median()
        .sort_values("time_hours")
    )
    axis.plot(
        median_concentrations["time_hours"],
        median_concentrations["concentration_mg_l"],
        color="#E45756",
        linewidth=2.8,
        marker="o",
        markersize=4,
        label="Population median",
    )
    axis.set_yscale("log")
    axis.set_xlabel("Time after dose (hours)")
    axis.set_ylabel("Concentration (mg/L, log scale)")
    axis.set_title("Individual and Median Concentration–Time Profiles")
    axis.grid(alpha=0.2)
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(concentration_path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    plot_paths["concentration_time_profiles"] = str(concentration_path)

    covariate_path = resolved_output_dir / "covariate_distributions.png"
    figure, axes = plt.subplots(2, 2, figsize=(10, 8))
    histogram_specs = (
        ("weight_kg", "Weight (kg)"),
        ("creatinine_clearance_ml_min", "Creatinine clearance (mL/min)"),
        ("albumin_g_dl", "Albumin (g/dL)"),
    )
    for axis, (column, label) in zip(axes.flat[:3], histogram_specs):
        axis.hist(
            patients[column],
            bins=20,
            color="#4C78A8",
            alpha=0.8,
            edgecolor="white",
        )
        axis.set_xlabel(label)
        axis.set_ylabel("Patients")
        axis.grid(axis="y", alpha=0.2)
    genotype_counts = patients["genotype"].value_counts().sort_index()
    axes.flat[3].bar(
        genotype_counts.index.astype(str),
        genotype_counts.values,
        color="#72B7B2",
        alpha=0.9,
    )
    axes.flat[3].set_xlabel("Genotype")
    axes.flat[3].set_ylabel("Patients")
    axes.flat[3].grid(axis="y", alpha=0.2)
    figure.suptitle("Baseline Covariate Distributions")
    figure.tight_layout()
    figure.savefig(covariate_path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    plot_paths["covariate_distributions"] = str(covariate_path)

    biomarker_path = resolved_output_dir / "biomarker_trajectories.png"
    figure, axis = plt.subplots(figsize=(9, 6))
    for _, patient_profile in pd_biomarkers.groupby("patient_id"):
        ordered_profile = patient_profile.sort_values("week")
        axis.plot(
            ordered_profile["week"],
            ordered_profile["inflammatory_marker_reduction_pct"],
            color="#4C78A8",
            alpha=0.15,
            linewidth=0.8,
        )
    median_biomarkers = (
        pd_biomarkers.groupby("week", as_index=False)[
            "inflammatory_marker_reduction_pct"
        ]
        .median()
        .sort_values("week")
    )
    axis.plot(
        median_biomarkers["week"],
        median_biomarkers["inflammatory_marker_reduction_pct"],
        color="#E45756",
        linewidth=2.8,
        marker="o",
        markersize=4,
        label="Population median",
    )
    axis.set_xlabel("Study week")
    axis.set_ylabel("Inflammatory marker reduction (%)")
    axis.set_title("Individual and Median Biomarker Trajectories")
    axis.grid(alpha=0.2)
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(biomarker_path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    plot_paths["biomarker_trajectories"] = str(biomarker_path)

    concentrations = pk_concentrations["concentration_mg_l"]
    week12_biomarkers = pd_biomarkers.loc[
        pd_biomarkers["week"] == 12,
        "inflammatory_marker_reduction_pct",
    ]
    summary: Dict[str, Any] = {
        "n_patients": metadata["n_patients"],
        "dose_mg": metadata["dose_mg"],
        "route": metadata["route"],
        "concentration_min_mg_l": float(concentrations.min()),
        "concentration_max_mg_l": float(concentrations.max()),
        "concentration_mean_mg_l": float(concentrations.mean()),
        "week12_biomarker_reduction_min_pct": float(week12_biomarkers.min()),
        "week12_biomarker_reduction_max_pct": float(week12_biomarkers.max()),
        "week12_biomarker_reduction_mean_pct": float(week12_biomarkers.mean()),
        "curve_shape_note": (
            "Concentration-time profiles show a broadly "
            "monoexponential-appearing decline across the population."
        ),
    }
    return {"plots": plot_paths, "summary": summary}


if __name__ == "__main__":
    eda_results = run_eda(load_all())
    print(f"plots: {eda_results['plots']}")
    print(f"summary: {eda_results['summary']}")
