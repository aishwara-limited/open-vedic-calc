"""Vimshopaka Bala, the served rasi dignity and the Ashtakavarga table, by BPHS.

Every expected value in this file is typed by hand from the classical text and
worked by hand; none is copied from the code under test.

* Vimshopaka Bala, BPHS ch. 7 vv. 20-27: the Dashavarga weights total 20; in
  each varga a graha in its own sign scores 20, and otherwise it scores by its
  five-fold (compound) relationship with the lord of the varga sign --
  adhimitra 18, mitra 15, sama 10, shatru 7, adhishatru 5. The compound
  relationship is BPHS 3.55-58: the natural relationship combined with the
  temporary one, read from the rasi chart (a graha in the 2nd, 3rd, 4th, 10th,
  11th or 12th sign from another is its temporary friend).
* Rasi dignity, BPHS 3.49-54: the Sun's moolatrikona is Leo 0-20 and the rest
  of Leo is his own sign; the Moon is exalted in Taurus 0-3 and moolatrikona in
  3-30; Mars moolatrikona Aries 0-12; Mercury exalted Virgo 0-15, moolatrikona
  15-20, own sign 20-30; Jupiter moolatrikona Sagittarius 0-10; Venus Libra
  0-15; Saturn Aquarius 0-20.
* Ashtakavarga, BPHS ch. 66: the benefic places of each graha's
  Bhinnashtakavarga counted from the eight reference points (vv. 46-48 for the
  Moon, vv. 56-58 for Venus).
"""
import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bphs_core import utils
from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

_SEVEN = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")
_DASHAVARGA_FIELDS = (
    "rasi_chart", "hora_chart", "drekkana_chart", "saptamsa_chart",
    "navamsa_chart", "decamsa_chart", "dwadasamsa_chart", "shodasamsa_chart",
    "trimshamsa_chart", "shashtyamsa_chart",
)


def _pd(planet: str, sign: str, degrees: float = 1.0) -> PlanetData:
    # The dignity string is deliberately a value no scorer recognises: the
    # Vimshopaka scorer must read the sign and the rasi chart, never the label.
    return PlanetData(
        planet=planet, sign=sign, degrees=degrees, nakshatra="Ashwini",
        dignity="not-read", house=1, conjunctions=[], aspects=[],
        is_retrograde=False,
    )


def _snapshot(rasi: dict[str, str], vargas: dict[str, str] | None = None) -> ChartSnapshot:
    """Every graha in its rasi sign; the grahas named in *vargas* hold that one
    sign in the nine other Dashavarga charts, the others hold their rasi sign."""
    vargas = vargas or {}
    charts = {
        name: {g: _pd(g, vargas.get(g, rasi[g])) for g in rasi}
        for name in _DASHAVARGA_FIELDS
    }
    charts["rasi_chart"] = {g: _pd(g, s) for g, s in rasi.items()}
    return ChartSnapshot(
        person=PersonalData(
            name="Synthetic", birth_date=datetime.date(2000, 1, 1),
            birth_time=datetime.time(12, 0), birth_place="X",
            latitude=0.0, longitude=0.0, timezone_offset_hours=0.0,
        ),
        chaturvimsa_chart={}, lagna="Aries", lagna_lord="Mars",
        ayanamsa_value=0.0, **charts,
    )


# Grahas not under test, parked together in Capricorn.
_PARKED = {"Sun": "Capricorn", "Moon": "Capricorn", "Mars": "Capricorn",
           "Mercury": "Capricorn", "Jupiter": "Capricorn", "Saturn": "Capricorn"}


# ---------------------------------------------------------------------------
# Vimshopaka Bala: the six values of BPHS ch. 7 vv. 24-25
# ---------------------------------------------------------------------------

# When a graha holds the same state in all ten vargas its total equals that
# state's value, because the Dashavarga weights total 20. Each case: Venus's
# sign in every varga, the varga lord, its rasi sign, and the expected total,
# reasoned from BPHS 3.55-58 (Venus: natural friends Mercury and Saturn,
# neutrals Mars and Jupiter, enemies the Sun and the Moon).
_SIX_VALUES = [
    # own sign: Venus in Libra in every varga.
    ("Libra", None, None, 20.0),
    # adhimitra: Mercury a natural friend, in the 2nd from Venus (Gemini ->
    # Cancer), a temporary friend too.
    ("Gemini", "Mercury", "Cancer", 18.0),
    # mitra: Mars a natural neutral, 2nd from Venus (Aries -> Taurus).
    ("Aries", "Mars", "Taurus", 15.0),
    # sama: Saturn a natural friend, 7th from Venus (Capricorn -> Cancer), a
    # temporary enemy.
    ("Capricorn", "Saturn", "Cancer", 10.0),
    # shatru: Jupiter a natural neutral, 5th from Venus (Pisces -> Cancer).
    ("Pisces", "Jupiter", "Cancer", 7.0),
    # adhishatru: the Sun a natural enemy, with Venus in Leo (1st place, a
    # temporary enemy).
    ("Leo", "Sun", "Leo", 5.0),
]


@pytest.mark.parametrize("venus_sign,lord,lord_sign,expected", _SIX_VALUES)
def test_vimshopaka_scores_the_six_bphs_values(venus_sign, lord, lord_sign, expected):
    from bphs_core.vimshopaka import compute_vimshopaka

    rasi = dict(_PARKED, Venus=venus_sign)
    if lord is not None:
        rasi[lord] = lord_sign
    result = compute_vimshopaka(_snapshot(rasi), "Venus")
    assert result.total == pytest.approx(expected)


def test_vimshopaka_has_no_debilitation_zero():
    """Venus in Virgo (her debilitation) with Mercury, a natural friend, in the
    2nd from her: adhimitra, 18 -- the verse has no zero step."""
    from bphs_core.vimshopaka import compute_vimshopaka

    rasi = dict(_PARKED, Venus="Virgo", Mercury="Libra")
    assert compute_vimshopaka(_snapshot(rasi), "Venus").total == pytest.approx(18.0)


def test_vimshopaka_exaltation_is_not_an_own_varga():
    """Venus in Pisces (her exaltation) is in Jupiter's sign: Jupiter is a
    natural neutral and, in the 2nd from her (Aries), a temporary friend --
    mitra, 15. BPHS 7.24-25 gives 20 to the own varga only."""
    from bphs_core.vimshopaka import compute_vimshopaka

    rasi = dict(_PARKED, Venus="Pisces", Jupiter="Aries")
    assert compute_vimshopaka(_snapshot(rasi), "Venus").total == pytest.approx(15.0)


def test_vimshopaka_reads_the_temporary_relationship_from_the_rasi_chart():
    """The rasi chart alone fixes the temporary relationship: Venus's D9 sign
    is Gemini in both charts below, and only Mercury's rasi place moves."""
    from bphs_core.vimshopaka import compute_vimshopaka

    friend = compute_vimshopaka(
        _snapshot(dict(_PARKED, Venus="Aries", Mercury="Taurus"), {"Venus": "Gemini"}),
        "Venus")
    # Mercury 2nd from Venus's rasi Aries: adhimitra 18 in every varga but D1,
    # where Venus is in Aries (Mars, a natural neutral; Mars in Capricorn is
    # 10th from Aries, a temporary friend: mitra 15).
    assert friend.contributions["D9"] == pytest.approx(1.5 * 18 / 20)
    assert friend.contributions["D1"] == pytest.approx(3.0 * 15 / 20)
    stranger = compute_vimshopaka(
        _snapshot(dict(_PARKED, Venus="Aries", Mercury="Virgo"), {"Venus": "Gemini"}),
        "Venus")
    # Mercury 6th from Aries: a temporary enemy, so natural friend -> sama 10.
    assert stranger.contributions["D9"] == pytest.approx(1.5 * 10 / 20)


def test_vimshopaka_refuses_a_chart_without_the_seven_grahas():
    """The temporary relationship needs every varga lord placed in the rasi
    chart; a chart without one is refused rather than scored as nothing."""
    from bphs_core.vimshopaka import compute_vimshopaka

    rasi = dict(_PARKED, Venus="Aries")
    del rasi["Mars"]
    with pytest.raises(ValueError, match="Mars"):
        compute_vimshopaka(_snapshot(rasi), "Venus")


# A fictitious birth worked by hand. The varga signs are what the engine's
# divisional charts give for this instant (pinned below); the points are worked
# from them by hand (BPHS 7.24-25 and 3.55-58).
_WORKED_BIRTH = {
    "name": "worked", "birth_date": "1988-03-14", "birth_time": "09:20:00",
    "birth_place": "Synthetic", "latitude": 6.9271, "longitude": 79.8612,
    "timezone_offset_hours": 5.5,
}
# Rasi chart: Sun Pisces, Moon Capricorn, Mars Sagittarius, Mercury Aquarius,
# Jupiter Aries, Venus Aries, Saturn Sagittarius. From Venus (Aries): Mars and
# Saturn 9th, the Sun 12th, the Moon 10th, Mercury 11th, Jupiter 1st.
#   Mars:    natural neutral, temporary enemy -> shatru 7
#   Sun:     natural enemy, temporary friend   -> sama 10
#   Moon:    natural enemy, temporary friend   -> sama 10
#   Mercury: natural friend, temporary friend  -> adhimitra 18
#   Jupiter: natural neutral, temporary enemy  -> shatru 7
# Venus's vargas and points (weight x value / 20):
_WORKED_VENUS = {
    "D1": ("Aries", 3.0 * 7 / 20),         # Mars    1.05
    "D2": ("Leo", 1.5 * 10 / 20),          # Sun     0.75
    "D3": ("Leo", 1.5 * 10 / 20),          # Sun     0.75
    "D7": ("Cancer", 1.5 * 10 / 20),       # Moon    0.75
    "D9": ("Leo", 1.5 * 10 / 20),          # Sun     0.75
    "D10": ("Leo", 1.5 * 10 / 20),         # Sun     0.75
    "D12": ("Virgo", 1.5 * 18 / 20),       # Mercury 1.35
    "D16": ("Scorpio", 1.5 * 7 / 20),      # Mars    0.525
    "D30": ("Sagittarius", 1.5 * 7 / 20),  # Jupiter 0.525
    "D60": ("Virgo", 5.0 * 18 / 20),       # Mercury 4.50
}
# Totals of the same birth from two implementations of the verse written apart
# from this engine (an auditor's and a verifier's), which agree on every graha.
_WORKED_TOTALS = {
    "Sun": 17.17, "Moon": 16.05, "Mars": 14.60, "Mercury": 16.35,
    "Jupiter": 10.60, "Venus": 11.70, "Saturn": 10.33,
}


def test_vimshopaka_worked_chart_through_the_strength_route():
    r = client.post("/v1/strength", json=_WORKED_BIRTH)
    assert r.status_code == 200, r.text
    vim = r.json()["vimshopaka"]

    chart = client.post("/v1/chart", json=_WORKED_BIRTH).json()
    rasi = {p["planet"]: p["sign"] for p in chart["rasi"]}
    assert {g: rasi[g] for g in _SEVEN} == {
        "Sun": "Pisces", "Moon": "Capricorn", "Mars": "Sagittarius",
        "Mercury": "Aquarius", "Jupiter": "Aries", "Venus": "Aries",
        "Saturn": "Sagittarius",
    }

    venus = vim["Venus"]
    for label, (_sign, points) in _WORKED_VENUS.items():
        assert venus["contributions"][label] == pytest.approx(points, abs=1e-4), label
    assert venus["total"] == pytest.approx(11.70, abs=0.005)
    for graha, total in _WORKED_TOTALS.items():
        assert vim[graha]["total"] == pytest.approx(total, abs=0.005), graha


def test_vimshopaka_worked_chart_varga_signs():
    """Pins the varga signs the hand-worked points above were read from."""
    from bphs_core.chart import Chart
    from bphs_core.vimshopaka import _VARGA_ATTR, _VARGA_LABEL

    p = PersonalData(
        name="worked", birth_date=datetime.date(1988, 3, 14),
        birth_time=datetime.time(9, 20), birth_place="Synthetic",
        latitude=6.9271, longitude=79.8612, timezone_offset_hours=5.5,
    )
    snap = Chart(p).snapshot()
    for dcf, attr in _VARGA_ATTR.items():
        label = _VARGA_LABEL[dcf]
        assert getattr(snap, attr)["Venus"].sign == _WORKED_VENUS[label][0], label


# ---------------------------------------------------------------------------
# Served rasi dignity: the arcs of BPHS 3.49-54
# ---------------------------------------------------------------------------

# Every graha in every sign at 0.5 degrees, typed from BPHS 3.49-54 (exaltation,
# debilitation, moolatrikona, own sign) and BPHS 3.55 (natural relationship with
# the sign lord).
_AT_HALF_DEGREE = {
    "Sun": ["exalted", "enemy", "neutral", "friendly", "moolatrikona", "neutral",
            "debilitated", "friendly", "friendly", "enemy", "enemy", "friendly"],
    "Moon": ["neutral", "exalted", "friendly", "own sign", "friendly", "friendly",
             "neutral", "debilitated", "neutral", "neutral", "neutral", "neutral"],
    "Mars": ["moolatrikona", "neutral", "enemy", "debilitated", "friendly", "enemy",
             "neutral", "own sign", "friendly", "exalted", "neutral", "friendly"],
    "Mercury": ["neutral", "friendly", "own sign", "enemy", "friendly", "exalted",
                "friendly", "neutral", "neutral", "neutral", "neutral", "debilitated"],
    "Jupiter": ["friendly", "enemy", "enemy", "exalted", "friendly", "enemy",
                "enemy", "friendly", "moolatrikona", "debilitated", "neutral", "own sign"],
    "Venus": ["neutral", "own sign", "friendly", "enemy", "enemy", "debilitated",
              "moolatrikona", "neutral", "neutral", "friendly", "friendly", "exalted"],
    "Saturn": ["debilitated", "friendly", "friendly", "enemy", "enemy", "friendly",
               "exalted", "enemy", "neutral", "own sign", "moolatrikona", "neutral"],
}

# The arc limits of BPHS 3.51-54, each side of every limit.
_ARC_EDGES = [
    ("Sun", "Leo", 19.99, "moolatrikona"), ("Sun", "Leo", 20.0, "own sign"),
    ("Sun", "Leo", 29.99, "own sign"),
    ("Moon", "Taurus", 2.99, "exalted"), ("Moon", "Taurus", 3.0, "moolatrikona"),
    ("Moon", "Taurus", 29.99, "moolatrikona"),
    ("Mars", "Aries", 11.99, "moolatrikona"), ("Mars", "Aries", 12.0, "own sign"),
    ("Mars", "Aries", 29.99, "own sign"),
    ("Mercury", "Virgo", 14.99, "exalted"), ("Mercury", "Virgo", 15.0, "moolatrikona"),
    ("Mercury", "Virgo", 19.99, "moolatrikona"), ("Mercury", "Virgo", 20.0, "own sign"),
    ("Mercury", "Virgo", 29.99, "own sign"),
    ("Jupiter", "Sagittarius", 9.99, "moolatrikona"),
    ("Jupiter", "Sagittarius", 10.0, "own sign"),
    ("Jupiter", "Sagittarius", 29.99, "own sign"),
    ("Venus", "Libra", 14.99, "moolatrikona"), ("Venus", "Libra", 15.0, "own sign"),
    ("Venus", "Libra", 29.99, "own sign"),
    ("Saturn", "Aquarius", 19.99, "moolatrikona"), ("Saturn", "Aquarius", 20.0, "own sign"),
    ("Saturn", "Aquarius", 29.99, "own sign"),
    # Exaltation and debilitation in every other sign hold the whole sign.
    ("Sun", "Aries", 29.99, "exalted"), ("Mars", "Capricorn", 29.99, "exalted"),
    ("Jupiter", "Cancer", 29.99, "exalted"), ("Venus", "Pisces", 29.99, "exalted"),
    ("Saturn", "Libra", 29.99, "exalted"), ("Moon", "Scorpio", 29.99, "debilitated"),
    ("Mercury", "Pisces", 29.99, "debilitated"),
]


def test_rasi_dignity_every_graha_in_every_sign():
    for planet, row in _AT_HALF_DEGREE.items():
        for idx, expected in enumerate(row):
            got = utils.get_rasi_dignity(planet, idx * 30.0 + 0.5)
            assert got == expected, (planet, utils.SIGNS[idx], got)


@pytest.mark.parametrize("planet,sign,degree,expected", _ARC_EDGES)
def test_rasi_dignity_honours_the_bphs_arcs(planet, sign, degree, expected):
    longitude = utils.SIGNS.index(sign) * 30.0 + degree
    assert utils.get_rasi_dignity(planet, longitude) == expected


def test_rasi_dignity_of_the_nodes_is_neutral():
    for node in ("Rahu", "Ketu"):
        for idx in range(12):
            assert utils.get_rasi_dignity(node, idx * 30.0 + 15.0) == "neutral"


def test_rasi_moolatrikona_agrees_with_saptavargaja_state():
    """The served label and Shadbala's rasi state read one arc table, so they
    can never disagree on moolatrikona."""
    from bphs_core.strength import varga_state

    longitudes = {g: 0.0 for g in _SEVEN}
    for planet in _SEVEN:
        for tenth in range(3600):
            lon = tenth / 10.0
            sign = utils.SIGNS[int(lon // 30)]
            served = utils.get_rasi_dignity(planet, lon) == "moolatrikona"
            shadbala = varga_state(planet, sign, lon, longitudes) == "moolatrikona"
            assert served == shadbala, (planet, lon)


# Births (UT 06:30, given as 12:00 at +5:30) checked against BPHS 3.51-54 from
# the served degree: the Sun at Leo 24.6, the Moon at Taurus 23.0 and Mercury
# at Virgo 17.6.
_SERVED_CASES = [
    ("2025-09-11", "Sun", "Leo", 20.0, 30.0, "own sign"),
    ("2025-01-11", "Moon", "Taurus", 3.0, 30.0, "moolatrikona"),
    ("2025-09-25", "Mercury", "Virgo", 15.0, 20.0, "moolatrikona"),
]


@pytest.mark.parametrize("day,planet,sign,lo,hi,expected", _SERVED_CASES)
def test_chart_route_serves_the_arc_dignity(day, planet, sign, lo, hi, expected):
    body = {"name": "arc", "birth_date": day, "birth_time": "12:00:00",
            "birth_place": "Synthetic", "latitude": 7.0, "longitude": 80.0,
            "timezone_offset_hours": 5.5}
    r = client.post("/v1/chart", json=body)
    assert r.status_code == 200, r.text
    served = {p["planet"]: p for p in r.json()["rasi"]}[planet]
    assert served["sign"] == sign
    assert lo + 0.5 < served["degrees"] < hi - 0.5
    assert served["dignity"] == expected


def test_varga_dignity_stays_sign_only():
    """BPHS 3.51-54 give the arcs in the rasi chart; a varga is judged by its
    sign (BPHS 27.2-4), so the varga label keeps the whole-sign reading."""
    assert utils.get_planet_dignity("Sun", "Leo") == "moolatrikona"
    assert utils.get_planet_dignity("Moon", "Taurus") == "exalted"
    assert utils.get_planet_dignity("Mercury", "Virgo") == "exalted"


def test_lagna_lord_dignity_reads_the_arc():
    """Lagna Leo at an instant with the Sun at Leo 24.6: the lagna lord is in
    his own sign (BPHS 3.51), not moolatrikona."""
    import swisseph as swe

    from bphs_core import lagna_shuddhi as ls

    jd = swe.julday(2025, 9, 11, 6.5)
    sun = utils.graha_sidereal_longitude(jd, "Sun")
    assert utils.SIGNS[int(sun // 30)] == "Leo" and 20.5 < sun % 30 < 29.5
    day = {
        "date": "2025-09-11", "sunrise": "06:00", "inauspicious_periods": [],
        "auspicious_muhurtas": [], "chogadiya": [],
        "panchanga": {"tithi": "Shukla Panchami", "yogam": "Siddhi",
                      "karana": "Bava", "vaara": "Thursday"},
        "is_eclipse_day": False, "is_adhik_maasa": False,
    }
    _, detail = ls._score_instant(jd, "Leo", "Sun", day, 720, "generic")
    assert detail["lagna_lord_dignity"] == "own sign"


# ---------------------------------------------------------------------------
# Ashtakavarga: the BPHS ch. 66 table, all 56 rows
# ---------------------------------------------------------------------------

# Typed from BPHS ch. 66: for each graha's Bhinnashtakavarga, the places from
# each reference point that give a bindu.
_BPHS_66 = {
    "Sun": {
        "Sun": [1, 2, 4, 7, 8, 9, 10, 11], "Moon": [3, 6, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11], "Mercury": [3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [5, 6, 9, 11], "Venus": [6, 7, 12],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11], "Lagna": [3, 4, 6, 10, 11, 12],
    },
    "Moon": {  # vv. 46-48
        "Sun": [3, 6, 7, 8, 10, 11], "Moon": [1, 3, 6, 7, 9, 10, 11],
        "Mars": [2, 3, 5, 6, 10, 11], "Mercury": [1, 3, 4, 5, 7, 8, 10, 11],
        "Jupiter": [1, 2, 4, 7, 8, 10, 11], "Venus": [3, 4, 5, 7, 9, 10, 11],
        "Saturn": [3, 5, 6, 11], "Lagna": [3, 6, 10, 11],
    },
    "Mars": {
        "Sun": [3, 5, 6, 10, 11], "Moon": [3, 6, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11], "Mercury": [3, 5, 6, 11],
        "Jupiter": [6, 10, 11, 12], "Venus": [6, 8, 11, 12],
        "Saturn": [1, 4, 7, 8, 9, 10, 11], "Lagna": [1, 3, 6, 10, 11],
    },
    "Mercury": {
        "Sun": [5, 6, 9, 11, 12], "Moon": [2, 4, 6, 8, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11], "Mercury": [1, 3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [6, 8, 11, 12], "Venus": [1, 2, 3, 4, 5, 8, 9, 11],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11], "Lagna": [1, 2, 4, 6, 8, 10, 11],
    },
    "Jupiter": {
        "Sun": [1, 2, 3, 4, 7, 8, 9, 10, 11], "Moon": [2, 5, 7, 9, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11], "Mercury": [1, 2, 4, 5, 6, 9, 10, 11],
        "Jupiter": [1, 2, 3, 4, 7, 8, 10, 11], "Venus": [2, 5, 6, 9, 10, 11],
        "Saturn": [3, 5, 6, 12], "Lagna": [1, 2, 4, 5, 6, 7, 9, 10, 11],
    },
    "Venus": {  # vv. 56-58
        "Sun": [8, 11, 12], "Moon": [1, 2, 3, 4, 5, 8, 9, 11, 12],
        "Mars": [3, 4, 6, 9, 11, 12], "Mercury": [3, 5, 6, 9, 11],
        "Jupiter": [5, 8, 9, 10, 11], "Venus": [1, 2, 3, 4, 5, 8, 9, 10, 11],
        "Saturn": [3, 4, 5, 8, 9, 10, 11], "Lagna": [1, 2, 3, 4, 5, 8, 9, 11],
    },
    "Saturn": {
        "Sun": [1, 2, 4, 7, 8, 10, 11], "Moon": [3, 6, 11],
        "Mars": [3, 5, 6, 10, 11, 12], "Mercury": [6, 8, 9, 10, 11, 12],
        "Jupiter": [5, 6, 11, 12], "Venus": [6, 11, 12],
        "Saturn": [3, 5, 6, 11], "Lagna": [1, 3, 4, 6, 10, 11],
    },
}


@pytest.mark.parametrize("planet", list(_BPHS_66))
def test_ashtakavarga_table_is_bphs_66(planet):
    from bphs_core.strength import _ASHTAKAVARGA_BENEFICS

    assert set(_ASHTAKAVARGA_BENEFICS) == set(_BPHS_66)
    table = _ASHTAKAVARGA_BENEFICS[planet]
    assert set(table) == set(_BPHS_66[planet])
    for ref, places in _BPHS_66[planet].items():
        assert sorted(table[ref]) == places, (planet, ref)


def test_ashtakavarga_worked_all_in_aries():
    """Every graha and the lagna in Aries: a sign's bindus are the number of
    rows (of the eight) that name its place counted from Aries. Worked by hand
    from the BPHS ch. 66 rows above."""
    from bphs_core.strength import compute_ashtakavarga

    snap = _snapshot({g: "Aries" for g in _SEVEN})
    akv = compute_ashtakavarga(snap)
    # Moon, place 1..12: 1 Moon Mercury Jupiter; 2 Mars Jupiter; 3 all but
    # Jupiter; 4 Mercury Jupiter Venus; 5 Mars Mercury Venus Saturn; 6 Sun
    # Moon Mars Saturn Lagna; 7 Sun Moon Mercury Jupiter Venus; 8 Sun Mercury
    # Jupiter; 9 Moon Venus; 10 all but Saturn; 11 all eight; 12 none.
    assert [akv["binna"]["Moon"][s] for s in utils.SIGNS] == [
        3, 2, 7, 3, 4, 5, 5, 3, 2, 7, 8, 0]
    # Venus: 1 Moon Venus Lagna; 2 Moon Venus Lagna; 3 Moon Mars Mercury Venus
    # Saturn Lagna; 4 Moon Mars Venus Saturn Lagna; 5 Moon Mercury Jupiter
    # Venus Saturn Lagna; 6 Mars Mercury; 7 none; 8 Sun Moon Jupiter Venus
    # Saturn Lagna; 9 Moon Mars Mercury Jupiter Venus Saturn Lagna; 10 Jupiter
    # Venus Saturn; 11 all eight; 12 Sun Moon Mars.
    assert [akv["binna"]["Venus"][s] for s in utils.SIGNS] == [
        3, 3, 6, 5, 6, 2, 0, 6, 7, 3, 8, 3]
