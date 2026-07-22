"""Tests for two-stage PK covariate screening."""

from math import exp, log
from typing import List

import pandas as pd
import pytest

from pipeline.covariates import screen_covariates


@pytest.mark.parametrize(
    "known_coefficient, expected_material",
    [(0.08, True), (0.02, False)],
)
def test_crcl_effect_recovery_and_materiality(
    known_coefficient: float,
    expected_material: bool,
) -> None:
    patient_ids: List[str] = [f"P{index}" for index in range(8)]
    creatinine_clearance = [40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0]
    median_crcl = 75.0
    clearance = [
        5.0 * exp(known_coefficient * ((value - median_crcl) / 10.0))
        for value in creatinine_clearance
    ]
    per_patient_pk = pd.DataFrame(
        {
            "patient_id": patient_ids,
            "model_type": ["1-compartment"] * 8,
            "converged": [True] * 8,
            "CL": clearance,
            "V": [20.0] * 8,
            "V1": [float("nan")] * 8,
        }
    )
    patients = pd.DataFrame(
        {
            "patient_id": patient_ids,
            "weight_kg": [55.0, 62.0, 68.0, 73.0, 79.0, 86.0, 94.0, 103.0],
            "creatinine_clearance_ml_min": creatinine_clearance,
            "genotype": ["WT/WT", "WT/MUT"] * 4,
        }
    )

    effects = screen_covariates(per_patient_pk, patients, "1-compartment")
    crcl_clearance_effect = next(
        effect
        for effect in effects
        if effect.covariate == "creatinine_clearance_ml_min"
        and effect.parameter_affected == "CL"
    )

    assert crcl_clearance_effect.effect_estimate == pytest.approx(
        known_coefficient,
        abs=1e-10,
    )
    assert crcl_clearance_effect.clinically_material is expected_material


def test_genotype_effect_recovery_and_materiality() -> None:
    patient_ids: List[str] = [f"G{index}" for index in range(9)]
    genotypes = ["WT/WT"] * 3 + ["WT/MUT"] * 3 + ["MUT/MUT"] * 3
    allele_counts = [0] * 3 + [1] * 3 + [2] * 3
    known_per_allele_ratio = 1.12
    known_coefficient = log(known_per_allele_ratio)
    per_patient_pk = pd.DataFrame(
        {
            "patient_id": patient_ids,
            "model_type": ["1-compartment"] * 9,
            "converged": [True] * 9,
            "CL": [
                5.0 * exp(known_coefficient * allele_count)
                for allele_count in allele_counts
            ],
            "V": [20.0] * 9,
            "V1": [float("nan")] * 9,
        }
    )
    patients = pd.DataFrame(
        {
            "patient_id": patient_ids,
            "weight_kg": [58.0, 64.0, 71.0, 77.0, 83.0, 89.0, 96.0, 104.0, 111.0],
            "creatinine_clearance_ml_min": [
                55.0,
                65.0,
                75.0,
                85.0,
                60.0,
                70.0,
                80.0,
                90.0,
                100.0,
            ],
            "genotype": genotypes,
        }
    )

    effects = screen_covariates(per_patient_pk, patients, "1-compartment")
    genotype_clearance_effect = next(
        effect
        for effect in effects
        if effect.covariate == "genotype" and effect.parameter_affected == "CL"
    )
    recovered_full_range_percent_difference = (
        exp(genotype_clearance_effect.effect_estimate * 2.0) - 1.0
    ) * 100.0

    assert genotype_clearance_effect.effect_estimate == pytest.approx(
        known_coefficient,
        abs=1e-10,
    )
    assert recovered_full_range_percent_difference == pytest.approx(
        ((known_per_allele_ratio**2) - 1.0) * 100.0,
        abs=1e-10,
    )
    assert genotype_clearance_effect.clinically_material is True
