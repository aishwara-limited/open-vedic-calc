"""Regression tests for calculation bugs fixed after cross-checking a known-good
reference chart.

Covers:
  1. Timezone double-subtraction in Chart construction (planet longitudes were
     computed tz hours early, corrupting the Vimshottari dasha balance).
  2. Ashtakavarga — was a degenerate 1-point-per-sign approximation; now the
     full BPHS ch.66 Bhinnashtakavarga (bindus 0-8 per sign).
  3. Arudha pada exception (pada in 1st/7th -> 10th house from pada: 1->10, 7->4).
  4. Favourable gem/metal keyed on the Janma-rasi (Moon-sign) lord.

No personal birth data is used: charts are synthetic, and the dasha/timezone
test asserts an invariant (Chart longitudes == a direct UT swisseph computation)
that holds for any non-zero timezone.
"""
import datetime

from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData


def _mock_chart(planets: dict[str, dict], lagna: str = "Aries",
                lagna_lord: str = "Mars") -> ChartSnapshot:
    rasi = {
        p: PlanetData(
            planet=p,
            sign=d.get("sign", "Aries"),
            degrees=d.get("degrees", 0.0),
            nakshatra=d.get("nakshatra", "Ashwini"),
            dignity=d.get("dignity", "neutral"),
            house=d.get("house", 1),
            conjunctions=[],
            aspects=[],
            is_retrograde=d.get("is_retrograde", False),
        )
        for p, d in planets.items()
    }
    return ChartSnapshot(
        person=PersonalData(
            name="Synthetic", birth_date=datetime.date(2000, 1, 1),
            birth_time=datetime.time(12, 0), birth_place="X",
            latitude=0.0, longitude=0.0, timezone_offset_hours=0.0,
        ),
        rasi_chart=rasi, hora_chart={}, drekkana_chart={}, navamsa_chart={},
        decamsa_chart={}, dwadasamsa_chart={}, chaturvimsa_chart={},
        trimshamsa_chart={}, saptamsa_chart={}, shashtyamsa_chart={},
        lagna=lagna, lagna_lord=lagna_lord, ayanamsa_value=0.0,
        house_cusps=[(i * 30.0) for i in range(12)],
    )


# Planet placements taken from a verified reference chart (synthetic here — just
# signs, no birth data).
_REF_PLACEMENTS = {
    "Sun":     {"sign": "Cancer"},
    "Moon":    {"sign": "Cancer"},
    "Mars":    {"sign": "Virgo"},
    "Mercury": {"sign": "Cancer"},
    "Jupiter": {"sign": "Leo"},
    "Venus":   {"sign": "Gemini"},
    "Saturn":  {"sign": "Virgo"},
}
_REF_LAGNA = "Aquarius"

# Reference Ashtakavarga (bindus per sign, Aries..Pisces), by the BPHS ch. 66
# table. The reference first recorded here came from a calculator carrying the
# variant table (attributed to Brihat Jataka ch. 9) in four rows. The Moon and
# Venus rows and the SAV were re-derived from the placements above by hand
# against the BPHS rows typed in tests/test_strength_dignity_bphs.py (_BPHS_66),
# both from scratch and as the change from the old reference: the Moon gains
# Virgo and Pisces and loses Taurus and Cancer, Venus gains Sagittarius and
# loses Capricorn; the other five rows are the same in both tables.
_REF_BINNA = {
    "Sun":     [7, 7, 4, 4, 1, 4, 3, 3, 7, 3, 1, 4],
    "Moon":    [5, 4, 2, 5, 2, 5, 3, 5, 4, 5, 6, 3],
    "Mars":    [5, 6, 3, 4, 0, 5, 1, 4, 6, 2, 1, 2],
    "Mercury": [5, 6, 6, 6, 2, 5, 4, 3, 6, 2, 3, 6],
    "Jupiter": [4, 5, 3, 5, 6, 3, 6, 6, 3, 3, 5, 7],
    "Venus":   [4, 7, 6, 4, 3, 4, 3, 4, 5, 2, 5, 5],
    "Saturn":  [4, 5, 3, 5, 2, 1, 1, 4, 4, 4, 5, 1],
}
_REF_SAV = [34, 40, 27, 33, 16, 27, 21, 29, 35, 21, 26, 28]
_BAV_TOTALS = {"Sun": 48, "Moon": 49, "Mars": 39, "Mercury": 54,
               "Jupiter": 56, "Venus": 52, "Saturn": 39}


# ---------------------------------------------------------------------------
# Ashtakavarga
# ---------------------------------------------------------------------------

def test_ashtakavarga_matches_reference_distribution():
    from bphs_core import utils
    from bphs_core.strength import compute_ashtakavarga

    snap = _mock_chart(_REF_PLACEMENTS, lagna=_REF_LAGNA, lagna_lord="Saturn")
    akv = compute_ashtakavarga(snap)

    for planet, expected in _REF_BINNA.items():
        got = [akv["binna"][planet][s] for s in utils.SIGNS]
        assert got == expected, f"{planet} BAV {got} != reference {expected}"

    sav = [akv["samudaya"][s] for s in utils.SIGNS]
    assert sav == _REF_SAV


def test_ashtakavarga_bav_totals_are_invariant():
    """Each planet's BAV always totals the classical value; SAV always 337,
    regardless of placements."""
    from bphs_core.strength import compute_ashtakavarga

    for lagna, placements in (
        (_REF_LAGNA, _REF_PLACEMENTS),
        ("Aries", {p: {"sign": "Aries"} for p in _BAV_TOTALS}),
        ("Libra", {  # arbitrary spread
            "Sun": {"sign": "Pisces"}, "Moon": {"sign": "Taurus"},
            "Mars": {"sign": "Leo"}, "Mercury": {"sign": "Scorpio"},
            "Jupiter": {"sign": "Capricorn"}, "Venus": {"sign": "Gemini"},
            "Saturn": {"sign": "Sagittarius"},
        }),
    ):
        snap = _mock_chart(placements, lagna=lagna, lagna_lord="Venus")
        akv = compute_ashtakavarga(snap)
        for planet, total in _BAV_TOTALS.items():
            assert sum(akv["binna"][planet].values()) == total
        assert sum(akv["samudaya"].values()) == 337
        # Lagna must not leak in as its own binna column.
        assert "Lagna" not in akv["binna"]


def test_ashtakavarga_single_planet_shape():
    from bphs_core import utils
    from bphs_core.strength import compute_ashtakavarga

    snap = _mock_chart(_REF_PLACEMENTS, lagna=_REF_LAGNA, lagna_lord="Saturn")
    one = compute_ashtakavarga(snap, "Saturn")
    # binna is now a flat {sign: bindus} for the requested planet.
    assert [one["binna"][s] for s in utils.SIGNS] == _REF_BINNA["Saturn"]


# ---------------------------------------------------------------------------
# Arudha pada exception
# ---------------------------------------------------------------------------

def test_arudha_pada_house_exceptions():
    from bphs_core.special_points import _arudha_pada_house

    # Normal cases: pada = 2*lord_house - 1 (mod 12).
    assert _arudha_pada_house(8) == 3    # 2*8-1 = 15 -> 3
    assert _arudha_pada_house(2) == 3
    assert _arudha_pada_house(3) == 5
    # Exception: pada lands in 1st -> 10th house from pada = 10.
    assert _arudha_pada_house(1) == 10
    assert _arudha_pada_house(7) == 10
    # Exception: pada lands in 7th -> 10th house from pada = 4.
    assert _arudha_pada_house(4) == 4
    assert _arudha_pada_house(10) == 4


def test_arudha_lagna_lord_in_first_house_is_tenth():
    from bphs_core.special_points import get_arudha_lagna

    # Aries lagna, lord Mars in the 1st house -> Arudha = 10th from lagna = Capricorn.
    snap = _mock_chart(
        {"Mars": {"sign": "Aries", "house": 1}},
        lagna="Aries", lagna_lord="Mars",
    )
    assert get_arudha_lagna(snap).sign == "Capricorn"


# ---------------------------------------------------------------------------
# Favourable points (Janma-rasi lord based)
# ---------------------------------------------------------------------------

def test_favourable_points_use_moon_sign_lord():
    from bphs_core.profile import favourable_points

    # Cancer Moon (lord Moon) -> Silver / Pearl, even with a non-Moon lagna lord.
    snap = _mock_chart(
        {"Moon": {"sign": "Cancer"}},
        lagna="Aquarius", lagna_lord="Saturn",
    )
    fav = favourable_points(snap)
    assert fav["rasi_lord"] == "Moon"
    assert fav["lucky_metal"] == "Silver"
    assert fav["lucky_stone"] == "Pearl"


# ---------------------------------------------------------------------------
# Timezone / dasha balance — Chart construction (needs swisseph + pyjhora)
# ---------------------------------------------------------------------------

def test_chart_planet_longitudes_are_not_double_timezone_shifted():
    """Planet longitudes must be computed at the true UT, not tz hours early.

    pyjhora's charts.rasi_chart expects a LOCAL jd and subtracts the timezone
    itself; feeding it a UT jd subtracts tz twice. Anchor the expectation on a
    direct UT swisseph call so a regression to double-subtraction is caught.
    """
    import swisseph as swe
    from jhora.panchanga import drik

    from bphs_core import utils
    from bphs_core.chart import Chart

    tz = 5.5
    p = PersonalData(
        name="Synthetic", birth_date=datetime.date(1990, 6, 15),
        birth_time=datetime.time(14, 30, 0), birth_place="X",
        latitude=12.0, longitude=78.0, timezone_offset_hours=tz,
    )
    snap = Chart(p).snapshot()

    # True UT, derived independently of bphs_core helpers.
    jd_utc_true = swe.julday(1990, 6, 15, 14.5 - tz)  # 14:30 local - 5.5h = 09:00 UT
    drik.set_ayanamsa_mode("LAHIRI")
    moon_lon = drik.sidereal_longitude(jd_utc_true, swe.MOON)
    exp_sign = utils.SIGNS[int(moon_lon // 30)]
    exp_deg = moon_lon % 30

    assert snap.rasi_chart["Moon"].sign == exp_sign
    assert abs(snap.rasi_chart["Moon"].degrees - exp_deg) < 0.05


def test_vimshottari_balance_tracks_moon_fraction():
    """First mahadasha lord = Moon's nakshatra lord, and the balance remaining
    from birth equals (1 - elapsed_fraction) * lord's full period."""
    from bphs_core.chart import Chart
    from bphs_core.dashas import (
        NAKSHATRA_LORDS,
        VIMSHOTTARI_YEARS,
        _moon_nakshatra_and_fraction,
        vimshottari_mahadashas,
    )

    p = PersonalData(
        name="Synthetic", birth_date=datetime.date(1990, 6, 15),
        birth_time=datetime.time(14, 30, 0), birth_place="X",
        latitude=12.0, longitude=78.0, timezone_offset_hours=5.5,
    )
    snap = Chart(p).snapshot()
    birth = datetime.datetime.combine(p.birth_date, p.birth_time)

    nak, frac = _moon_nakshatra_and_fraction(snap)
    lord = NAKSHATRA_LORDS[nak]
    mds = vimshottari_mahadashas(snap, birth)

    assert mds[0].lord == lord
    remaining = (mds[0].end_date - birth).days / 365.25
    expected = (1.0 - frac) * VIMSHOTTARI_YEARS[lord]
    assert abs(remaining - expected) < 0.05
