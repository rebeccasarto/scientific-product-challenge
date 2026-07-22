"""Screen prespecified covariates against two-stage individual PK estimates."""

import sys
from math import exp, log
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import linregress


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.schemas import CovariateEffect
from pipeline.data_loading import load_all
from pipeline.pk import fit_population_pk


def _fit_regression(
    predictor: pd.Series,
    parameter: pd.Series,
) -> Tuple[float, float, float, float]:
    usable = pd.DataFrame(
        {
            "predictor": pd.to_numeric(predictor, errors="coerce"),
            "parameter": pd.to_numeric(parameter, errors="coerce"),
        }
    ).replace([np.inf, -np.inf], np.nan)
    usable = usable.dropna()
    usable = usable.loc[usable["parameter"] > 0]
    if len(usable) < 3 or usable["predictor"].nunique() < 2:
        raise ValueError("Covariate screening requires at least three usable observations")

    regression = linregress(
        usable["predictor"].to_numpy(dtype=float),
        np.log(usable["parameter"].to_numpy(dtype=float)),
    )
    estimate = float(regression.slope)
    standard_error = float(regression.stderr)
    ci_lower = estimate - (1.96 * standard_error)
    ci_upper = estimate + (1.96 * standard_error)
    return estimate, ci_lower, ci_upper, float(regression.pvalue)


def _is_clinically_material(
    confidence_interval: Tuple[float, float],
    iqr_parameter_ratio: float,
) -> bool:
    ci_lower, ci_upper = confidence_interval
    confidence_interval_excludes_zero = ci_lower > 0 or ci_upper < 0
    material_iqr_change = iqr_parameter_ratio >= 1.20 or iqr_parameter_ratio <= 0.833
    return confidence_interval_excludes_zero and material_iqr_change


def _interpretation(
    covariate_label: str,
    parameter_name: str,
    iqr_parameter_ratio: float,
) -> str:
    percent_change = (iqr_parameter_ratio - 1.0) * 100.0
    direction = "increases" if percent_change >= 0 else "decreases"
    return (
        f"Exploratory two-stage association: across the interquartile range of "
        f"{covariate_label}, {parameter_name} {direction} by approximately "
        f"{abs(percent_change):.1f}%; not a definitive population PK covariate effect."
    )


def screen_covariates(
    per_patient_pk: pd.DataFrame,
    patients: pd.DataFrame,
    selected_model: str,
) -> List[CovariateEffect]:
    """Screen weight and creatinine clearance against selected-model PK estimates."""
    if selected_model not in ("1-compartment", "2-compartment"):
        raise ValueError(f"Unsupported selected_model: {selected_model}")

    volume_parameter = "V" if selected_model == "1-compartment" else "V1"
    selected_fits = per_patient_pk.loc[
        (per_patient_pk["model_type"] == selected_model)
        & per_patient_pk["converged"]
    ]
    analysis_data = selected_fits.merge(
        patients[
            [
                "patient_id",
                "weight_kg",
                "creatinine_clearance_ml_min",
                "genotype",
            ]
        ],
        on="patient_id",
        how="inner",
        validate="one_to_one",
    )

    weight_q25 = float(analysis_data["weight_kg"].quantile(0.25))
    weight_q75 = float(analysis_data["weight_kg"].quantile(0.75))
    crcl_median = float(
        analysis_data["creatinine_clearance_ml_min"].median()
    )
    crcl_q25 = float(
        analysis_data["creatinine_clearance_ml_min"].quantile(0.25)
    )
    crcl_q75 = float(
        analysis_data["creatinine_clearance_ml_min"].quantile(0.75)
    )
    observed_genotypes = set(analysis_data["genotype"].dropna().astype(str))
    allowed_genotypes = {"WT/WT", "WT/MUT", "MUT/MUT"}
    additional_genotypes = observed_genotypes - allowed_genotypes
    if additional_genotypes:
        raise ValueError(
            "Genotype covariate screening supports only WT/WT, WT/MUT, and "
            "MUT/MUT; unsupported observed genotype category/categories: "
            + ", ".join(sorted(additional_genotypes))
        )
    allele_count = analysis_data["genotype"].map(
        {"WT/WT": 0.0, "WT/MUT": 1.0, "MUT/MUT": 2.0}
    )
    effects: List[CovariateEffect] = []

    for parameter_name in ("CL", volume_parameter):
        weight_estimate, weight_ci_lower, weight_ci_upper, weight_p_value = (
            _fit_regression(
                np.log(analysis_data["weight_kg"]),
                analysis_data[parameter_name],
            )
        )
        weight_ratio = (weight_q75 / weight_q25) ** weight_estimate
        weight_confidence_interval = (weight_ci_lower, weight_ci_upper)
        effects.append(
            CovariateEffect(
                covariate="weight_kg",
                parameter_affected=parameter_name,
                effect_form="allometric_exponent",
                effect_estimate=weight_estimate,
                reference_value=weight_q25,
                comparison_value=weight_q75,
                confidence_interval=weight_confidence_interval,
                p_value=weight_p_value,
                clinically_material=_is_clinically_material(
                    weight_confidence_interval,
                    weight_ratio,
                ),
                interpretation=_interpretation(
                    "weight",
                    parameter_name,
                    weight_ratio,
                ),
            )
        )

        scaled_crcl = (
            analysis_data["creatinine_clearance_ml_min"] - crcl_median
        ) / 10.0
        crcl_estimate, crcl_ci_lower, crcl_ci_upper, crcl_p_value = (
            _fit_regression(scaled_crcl, analysis_data[parameter_name])
        )
        crcl_ratio = exp(crcl_estimate * (crcl_q75 - crcl_q25) / 10.0)
        crcl_confidence_interval = (crcl_ci_lower, crcl_ci_upper)
        effects.append(
            CovariateEffect(
                covariate="creatinine_clearance_ml_min",
                parameter_affected=parameter_name,
                effect_form="linear_coefficient_per_10_ml_min_on_log_scale",
                effect_estimate=crcl_estimate,
                reference_value=crcl_q25,
                comparison_value=crcl_q75,
                confidence_interval=crcl_confidence_interval,
                p_value=crcl_p_value,
                clinically_material=_is_clinically_material(
                    crcl_confidence_interval,
                    crcl_ratio,
                ),
                interpretation=_interpretation(
                    "creatinine clearance",
                    parameter_name,
                    crcl_ratio,
                ),
            )
        )

        genotype_estimate, genotype_ci_lower, genotype_ci_upper, genotype_p_value = (
            _fit_regression(allele_count, analysis_data[parameter_name])
        )
        genotype_confidence_interval = (genotype_ci_lower, genotype_ci_upper)
        per_allele_percent_difference = (exp(genotype_estimate) - 1.0) * 100.0
        full_range_percent_difference = (exp(genotype_estimate * 2.0) - 1.0) * 100.0
        genotype_ci_excludes_zero = genotype_ci_lower > 0 or genotype_ci_upper < 0
        genotype_direction = (
            "higher" if per_allele_percent_difference >= 0 else "lower"
        )
        effects.append(
            CovariateEffect(
                covariate="genotype",
                parameter_affected=parameter_name,
                effect_form="log_scale_per_mutant_allele",
                effect_estimate=genotype_estimate,
                reference_value=0,
                comparison_value=2,
                confidence_interval=genotype_confidence_interval,
                p_value=genotype_p_value,
                clinically_material=(
                    genotype_ci_excludes_zero
                    and abs(full_range_percent_difference) >= 20.0
                ),
                interpretation=(
                    "Exploratory two-stage association: each additional mutant "
                    f"allele is associated with approximately "
                    f"{abs(per_allele_percent_difference):.1f}% "
                    f"{genotype_direction} {parameter_name}; comparing homozygous "
                    "wild-type to homozygous mutant implies an approximate "
                    f"{abs(full_range_percent_difference):.1f}% difference; not a "
                    "definitive population PK covariate effect."
                ),
            )
        )

    return effects


if __name__ == "__main__":
    loaded_data = load_all()
    comparison, patient_pk = fit_population_pk(loaded_data)
    if comparison.selected_model is None:
        raise RuntimeError("PK model selection did not produce a structural model")
    covariate_effects = screen_covariates(
        patient_pk,
        loaded_data["patients"],
        comparison.selected_model,
    )
    for effect in covariate_effects:
        print(effect)
