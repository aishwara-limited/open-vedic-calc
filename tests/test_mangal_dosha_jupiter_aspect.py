"""Mangal dosha: the Jupiter cancellation needs Jupiter to ASPECT Mars.

``PlanetData.aspects`` lists the grahas a planet casts its drishti ON (see
``bphs_core/chart.py::_find_aspects``), not the grahas that aspect it. The
cancellation in ``bphs_core/compat.py::_mangal_dosha_raw`` must therefore read
JUPITER's aspect list, counted from Jupiter to Mars.

The aspect rule, BPHS ch. 26 (Graha Drishti), vv. 2-5: every graha gives a
full aspect to the 7th house from itself, and Jupiter alone gives full aspects
also to the 5th and 9th (Mars to the 4th and 8th, Saturn to the 3rd and 10th).
BPHS 26.12 gives the same peaks in the sphuta drishti of Jupiter (120 and 240
degrees), as ``bphs_core/strength.py::sphuta_drishti`` computes. A conjunction
(the same sign) is the other influence the served rule counts.

Expected values below are computed by hand from that rule, never copied from
the code under test: with Mars in Leo, Jupiter aspects or joins Mars exactly
when Mars is the 1st, 5th, 7th or 9th sign counted from Jupiter, i.e. Jupiter
in Leo, Aries, Aquarius or Sagittarius.
"""
import datetime
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CALC_SERVICE_TOKEN", "test")
os.environ.setdefault("PUBLIC_SOURCE_URL", "https://example.com")

from app.main import app
from bphs_core import compat
from bphs_core.chart import (
    ChartSnapshot,
    PersonalData,
    PlanetData,
    _find_aspects,
    _find_conjunctions,
)
from tests.conftest import SAMPLE_B

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

JUPITER_REASON = "Jupiter's influence on Mars cancels the Mangal Dosha."

_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# Jupiter's sign -> (house of Mars counted from Jupiter, Jupiter aspects or
# joins Mars?). Mars is fixed in Leo. Counted by hand: from Aries, Leo is the
# 5th sign; from Taurus the 4th; ... from Pisces the 6th. Jupiter influences
# Mars at the 1st (conjunction), 5th, 7th and 9th only (BPHS 26.2-5).
_JUPITER_SIGN_TABLE = {
    "Aries":       (5, True),
    "Taurus":      (4, False),
    "Gemini":      (3, False),
    "Cancer":      (2, False),
    "Leo":         (1, True),
    "Virgo":       (12, False),
    "Libra":       (11, False),
    "Scorpio":     (10, False),
    "Sagittarius": (9, True),
    "Capricorn":   (8, False),
    "Aquarius":    (7, True),
    "Pisces":      (6, False),
}


def _snapshot(lagna: str, signs: dict[str, str]) -> ChartSnapshot:
    """A whole-sign rasi chart whose conjunction and aspect lists are filled by
    the same builders the real ``Chart`` uses."""
    lagna_idx = _SIGNS.index(lagna)
    rasi = {
        p: PlanetData(
            planet=p, sign=s, degrees=15.0, nakshatra="Ashwini",
            dignity="neutral", house=(_SIGNS.index(s) - lagna_idx) % 12 + 1,
            conjunctions=[], aspects=[], is_retrograde=False,
        )
        for p, s in signs.items()
    }
    for name, pd in rasi.items():
        pd.conjunctions = _find_conjunctions(name, pd.house, rasi)
        pd.aspects = _find_aspects(name, pd.house, rasi)
    return ChartSnapshot(
        person=PersonalData(
            name="Synthetic", birth_date=datetime.date(2000, 1, 1),
            birth_time=datetime.time(12, 0), birth_place="X",
            latitude=0.0, longitude=0.0, timezone_offset_hours=0.0,
        ),
        rasi_chart=rasi, hora_chart={}, drekkana_chart={}, navamsa_chart={},
        decamsa_chart={}, dwadasamsa_chart={}, chaturvimsa_chart={},
        trimshamsa_chart={}, saptamsa_chart={}, shashtyamsa_chart={},
        lagna=lagna, lagna_lord="Venus", ayanamsa_value=0.0,
        house_cusps=[(i * 30.0) for i in range(12)],
    )


def test_table_covers_every_sign_once():
    assert sorted(_JUPITER_SIGN_TABLE) == sorted(_SIGNS)
    assert sorted(h for h, _ in _JUPITER_SIGN_TABLE.values()) == list(range(1, 13))
    assert [s for s, (_, hit) in _JUPITER_SIGN_TABLE.items() if hit] == [
        "Aries", "Leo", "Sagittarius", "Aquarius"]


@pytest.mark.parametrize("jupiter_sign", _SIGNS)
def test_jupiter_cancellation_all_twelve_placements(jupiter_sign):
    """Taurus lagna, Mars in Leo (4th house: a mild dosha), Moon in Gemini.

    No other served cancellation can fire: Mars is not in Aries, Scorpio or
    Capricorn, the lagna and the Moon are neither Aries nor Scorpio, and Mars
    is not in the 2nd house. So the Jupiter reason is the only one possible,
    and it must appear exactly when Jupiter aspects or joins Mars.
    """
    house_from_jupiter, expected = _JUPITER_SIGN_TABLE[jupiter_sign]
    snap = _snapshot("Taurus", {"Mars": "Leo", "Moon": "Gemini",
                                "Jupiter": jupiter_sign})
    assert (_SIGNS.index("Leo") - _SIGNS.index(jupiter_sign)) % 12 + 1 == house_from_jupiter

    has, severity, reasons = compat._mangal_dosha_raw(snap)

    assert has is True
    assert severity == "mild"
    assert reasons == ([JUPITER_REASON] if expected else [])


def test_no_jupiter_in_chart_gives_no_jupiter_reason():
    snap = _snapshot("Taurus", {"Mars": "Leo", "Moon": "Gemini"})
    assert compat._mangal_dosha_raw(snap) == (True, "mild", [])


# ---------------------------------------------------------------------------
# Worked examples through the served routes
# ---------------------------------------------------------------------------
#
# Both births are at 6.9 N, 79.8 E, UTC+5:30. Positions were computed
# independently with the Swiss Ephemeris directly (sidereal, Lahiri ayanamsa,
# ascendant from swe.houses_ex), not through this service:
#
#   1985-12-17 21:00  Lagna Cancer 14.70, Mars Libra 8.10, Jupiter Capricorn
#                     21.67, Moon Aquarius 15.38. Mars is in the 4th house and
#                     is the 10th sign from Jupiter, so Jupiter does NOT aspect
#                     Mars (Mars aspects Jupiter by its own 4th aspect instead).
#                     No other served cancellation applies: none is served.
#   1979-04-28 16:00  Lagna Virgo 9.65, Mars Pisces 22.96, Jupiter Cancer 7.14,
#                     Moon Taurus 7.94. Mars is in the 7th house and is the 9th
#                     sign from Jupiter, so the 9th aspect of Jupiter falls on
#                     Mars: the Jupiter cancellation applies.

_NO_JUPITER_ASPECT = {
    "name": "worked_a", "birth_date": "1985-12-17", "birth_time": "21:00:00",
    "birth_place": "X", "latitude": 6.9, "longitude": 79.8,
    "timezone_offset_hours": 5.5,
}
_JUPITER_NINTH_ASPECT = {
    "name": "worked_b", "birth_date": "1979-04-28", "birth_time": "16:00:00",
    "birth_place": "X", "latitude": 6.9, "longitude": 79.8,
    "timezone_offset_hours": 5.5,
}

_WORKED = [
    # (birth data, lagna, {planet: (sign, house)}, served cancellation or None)
    (_NO_JUPITER_ASPECT, "Cancer",
     {"Mars": ("Libra", 4), "Jupiter": ("Capricorn", 7), "Moon": ("Aquarius", 8)},
     None),
    (_JUPITER_NINTH_ASPECT, "Virgo",
     {"Mars": ("Pisces", 7), "Jupiter": ("Cancer", 11), "Moon": ("Taurus", 9)},
     JUPITER_REASON),
]
_WORKED_IDS = ["jupiter-10th-from-mars", "jupiter-9th-aspect"]


@pytest.mark.parametrize("birth, lagna, placements, cancellation", _WORKED,
                         ids=_WORKED_IDS)
def test_worked_example_profile(birth, lagna, placements, cancellation):
    chart = client.post("/v1/chart", json=birth)
    assert chart.status_code == 200, chart.text
    body = chart.json()
    assert body["lagna"] == lagna
    served = {p["planet"]: (p["sign"], p["house"]) for p in body["rasi"]}
    for planet, placement in placements.items():
        assert served[planet] == placement, planet

    r = client.post("/v1/profile", json=birth)
    assert r.status_code == 200, r.text
    dosha = r.json()["mangal_dosha"]
    assert dosha["present"] is True
    assert dosha["severity"] == "mild"
    assert dosha["cancellation"] == cancellation


@pytest.mark.parametrize("birth, cancellation",
                         [(w[0], w[3]) for w in _WORKED], ids=_WORKED_IDS)
def test_worked_example_compat(birth, cancellation):
    """The partner (sample B, Mars in the 5th) has no dosha, so the mutual
    cancellation does not replace the person's own first reason."""
    r = client.post("/v1/compat", json={"person_a": birth, "person_b": SAMPLE_B})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mangal_dosha_b"]["has_dosha"] is False
    dosha = body["mangal_dosha_a"]
    assert dosha["has_dosha"] is True
    assert dosha["severity"] == "mild"
    assert dosha["cancellation"] == (cancellation or "")
