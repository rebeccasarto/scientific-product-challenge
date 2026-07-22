"""Numerical tests for PK fitting and model-selection helpers."""

from math import log
from typing import Any, Dict

import numpy as np
import pytest

from pipeline.pk import (
    calculate_aicc,
    fit_one_compartment_patient,
    fit_two_compartment_patient,
    hybrid_to_micro_constants,
    micro_to_hybrid_constants,
    one_compartment_concentration,
    prefers_two_compartment,
    two_compartment_concentration,
)


def test_one_compartment_fit_recovers_known_parameters() -> None:
    times = np.asarray([0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0])
    dose_mg = 100.0
    known_clearance = 4.0
    known_volume = 20.0
    concentrations = one_compartment_concentration(
        times,
        known_clearance,
        known_volume,
        dose_mg,
    )

    fit = fit_one_compartment_patient(times, concentrations, dose_mg)

    assert fit["converged"] is True
    assert fit["CL"] == pytest.approx(known_clearance, rel=1e-4)
    assert fit["V"] == pytest.approx(known_volume, rel=1e-4)


def test_aicc_matches_hand_calculation() -> None:
    n_observations = 8
    n_parameters = 2
    rss = 4.0
    expected_aic = n_observations * log(rss / n_observations) + 2 * n_parameters
    expected_correction = (2 * n_parameters * (n_parameters + 1)) / (
        n_observations - n_parameters - 1
    )

    assert calculate_aicc(n_observations, n_parameters, rss) == pytest.approx(
        expected_aic + expected_correction
    )


def test_two_compartment_conversion_round_trip_after_fit() -> None:
    dose_mg = 100.0
    known = {"CL": 3.0, "V1": 10.0, "Q": 2.0, "V2": 20.0}
    hybrid = micro_to_hybrid_constants(
        dose_mg,
        known["CL"],
        known["V1"],
        known["Q"],
        known["V2"],
    )
    times = np.asarray([0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0])
    concentrations = two_compartment_concentration(
        times,
        hybrid["A"],
        hybrid["B"],
        hybrid["alpha"],
        hybrid["beta"],
    )

    fit = fit_two_compartment_patient(times, concentrations, dose_mg)
    assert fit["converged"] is True
    recovered = hybrid_to_micro_constants(
        dose_mg,
        fit["A"],
        fit["B"],
        fit["alpha"],
        fit["beta"],
    )

    assert recovered["CL"] == pytest.approx(known["CL"], rel=1e-3)
    assert recovered["V1"] == pytest.approx(known["V1"], rel=1e-3)
    assert recovered["Q"] == pytest.approx(known["Q"], rel=1e-3)
    assert recovered["V2"] == pytest.approx(known["V2"], rel=1e-3)


def test_nonidentifiable_hybrid_rates_do_not_prefer_two_compartments() -> None:
    one_fit: Dict[str, Any] = {"converged": True, "aicc": 20.0}
    two_fit: Dict[str, Any] = {
        "converged": True,
        "aicc": 10.0,
        "alpha": 0.5,
        "beta": 0.5,
    }

    assert prefers_two_compartment(one_fit, two_fit) is False
