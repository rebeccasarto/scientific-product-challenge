"""Tests for two-stage PK covariate screening."""

from math import exp
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
