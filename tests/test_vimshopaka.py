"""Vimshopaka Bala (Dashavarga, 0-20) — unit tests."""

from datetime import datetime, time

from bphs_core.chart import Chart, PersonalData
from bphs_core.vimshopaka import (
    _DASHAVARGA_WEIGHTS_RAW,
    _VARGA_ATTR,
    _VIMSHOPAKA_SCORE,
    _grade,
    compute_all_vimshopaka,
)
from tests.conftest import SAMPLE_A


def _snapshot(sample: dict):
    p = PersonalData(
        name=sample["name"],
        birth_date=datetime.strptime(sample["birth_date"], "%Y-%m-%d"),
        birth_time=time.fromisoformat(sample["birth_time"]),
        birth_place=sample["birth_place"],
        latitude=sample["latitude"],
        longitude=sample["longitude"],
        timezone_offset_hours=sample["timezone_offset_hours"],
    )
    return Chart(p).snapshot()


# ---------------------------------------------------------------------------
# Weight table invariants (the wrapped pyjhora Dashavarga scheme)
# ---------------------------------------------------------------------------

def test_dashavarga_weights_sum_to_20():
    assert abs(sum(_DASHAVARGA_WEIGHTS_RAW.values()) - 20.0) < 1e-9


def test_dashavarga_is_the_classical_ten_varga_set():
    # Exactly the BPHS Dashavarga: D1,D2,D3,D7,D9,D10,D12,D16,D30,D60.
    assert set(_DASHAVARGA_WEIGHTS_RAW) == {1, 2, 3, 7, 9, 10, 12, 16, 30, 60}
    assert set(_VARGA_ATTR) == set(_DASHAVARGA_WEIGHTS_RAW)


def test_individual_weights_match_bphs():
    expected = {1: 3, 2: 1.5, 3: 1.5, 7: 1.5, 9: 1.5,
                10: 1.5, 12: 1.5, 16: 1.5, 30: 1.5, 60: 5}
    assert _DASHAVARGA_WEIGHTS_RAW == expected


# ---------------------------------------------------------------------------
# The varga scores of BPHS 7.24-25
# ---------------------------------------------------------------------------

def test_varga_scores_are_the_bphs_scale():
    # Own varga 20, adhimitra 18, mitra 15, sama 10, shatru 7, adhishatru 5;
    # no step for exaltation or debilitation.
    assert _VIMSHOPAKA_SCORE == {
        "own": 20.0, "great friend": 18.0, "friend": 15.0,
        "neutral": 10.0, "enemy": 7.0, "great enemy": 5.0,
    }


def test_grade_bands():
    assert _grade(4.99) == "very weak"
    assert _grade(5.0) == "weak"
    assert _grade(9.99) == "weak"
    assert _grade(10.0) == "good"
    assert _grade(14.99) == "good"
    assert _grade(15.0) == "excellent"
    assert _grade(20.0) == "excellent"


# ---------------------------------------------------------------------------
# Computation over a real fixture chart
# ---------------------------------------------------------------------------

def test_compute_all_vimshopaka_seven_grahas():
    snap = _snapshot(SAMPLE_A)
    results = compute_all_vimshopaka(snap)
    planets = {r.planet for r in results}
    assert planets == {"Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"}
    # Nodes excluded by design.
    assert "Rahu" not in planets and "Ketu" not in planets


def test_vimshopaka_total_in_range_and_consistent():
    snap = _snapshot(SAMPLE_A)
    for r in compute_all_vimshopaka(snap):
        assert 0.0 <= r.total <= 20.0
        # Total equals the sum of its varga contributions (within rounding).
        assert abs(sum(r.contributions.values()) - r.total) < 0.02
        # Exactly the ten Dashavarga columns are present.
        assert set(r.contributions) == {"D1", "D2", "D3", "D7", "D9",
                                        "D10", "D12", "D16", "D30", "D60"}
        assert r.grade in ("very weak", "weak", "good", "excellent")


def test_vimshopaka_d16_contributes():
    # D16 was newly wired into the varga machinery; its column must be populated
    # (non-None) for every graha and never exceed its 1.5 weight.
    snap = _snapshot(SAMPLE_A)
    for r in compute_all_vimshopaka(snap):
        assert "D16" in r.contributions
        assert 0.0 <= r.contributions["D16"] <= 1.5


def test_per_varga_contribution_bounded_by_weight():
    snap = _snapshot(SAMPLE_A)
    label_weight = {"D1": 3, "D2": 1.5, "D3": 1.5, "D7": 1.5, "D9": 1.5,
                    "D10": 1.5, "D12": 1.5, "D16": 1.5, "D30": 1.5, "D60": 5}
    for r in compute_all_vimshopaka(snap):
        for label, pts in r.contributions.items():
            assert 0.0 <= pts <= label_weight[label] + 1e-9
