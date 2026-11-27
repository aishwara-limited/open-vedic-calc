"""Mangal dosha follows BPHS ch. 80 vv. 47-49 alone.

The rule, read from the verses (Santhanam numbering):

* v. 47, "lagne vyaye sukhe vapi saptame va'shtame kuje,
  shubha-drig-yoga-hine": Mars in the lagna (1st), the 12th (vyaya), the 4th
  (sukha), the 7th or the 8th, counted from the lagna, forms the yoga when no
  benefic aspects or joins him. Five houses; the 2nd is not among them, and the
  count is from the lagna only (the verse names no count from the Moon).
* The same verse grades nothing: there is no "mild" or "strong" Mangal dosha.
* vv. 48-49: the evil is cancelled when the partner's chart carries the same
  yoga.

The benefics are the natural benefics of BPHS 3.11, as
``bphs_core/strength.py::is_benefic`` reads them: Jupiter and Venus; the Moon
while waxing (elongation from the Sun in the open interval 0-180 degrees);
Mercury unless he shares his sign with the Sun, Mars, Saturn, the waning Moon,
Rahu or Ketu. So Mercury joining Mars is never a benefic conjunction: Mars is in
his sign. An aspect is the one the benefic casts on Mars (BPHS ch. 26, vv. 2-5:
every graha the 7th from itself, Jupiter also the 5th and 9th), read from the
benefic's own aspect list.

Every expected value below is derived by hand from those verses, never copied
from the code under test. The worked births were computed independently with
the Swiss Ephemeris directly (sidereal, Lahiri, ascendant from
``swe.houses_ex``), not through this service; every graha and the lagna sit at
least 2.5 degrees from a sign boundary, so both ephemeris runtimes place them
alike.
"""
import dataclasses
import datetime
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CALC_SERVICE_TOKEN", "test")
os.environ.setdefault("PUBLIC_SOURCE_URL", "https://example.com")

from app.main import app
from bphs_core import compat, profile
from bphs_core.chart import (
    ChartSnapshot,
    PersonalData,
    PlanetData,
    _find_aspects,
    _find_conjunctions,
)
from tests.conftest import SAMPLE_B

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# BPHS 80.47, house by house, typed from the verse: lagne (1), sukhe (4),
# saptame (7), ashtame (8), vyaye (12). Nothing else.
_DOSHA_HOUSE = {
    1: True, 2: False, 3: False, 4: True, 5: False, 6: False,
    7: True, 8: True, 9: False, 10: False, 11: False, 12: True,
}

MUTUAL = "Both charts carry Mangal Dosha, which mutually cancels the affliction."


def joins(graha: str) -> str:
    return f"{graha} joins Mars, and a natural benefic's conjunction cancels the Mangal Dosha."


def aspects(graha: str) -> str:
    return f"{graha} aspects Mars, and a natural benefic's aspect cancels the Mangal Dosha."


def _snapshot(lagna: str, placements: dict[str, float]) -> ChartSnapshot:
    """A whole-sign rasi chart from absolute sidereal longitudes, with the
    conjunction and aspect lists filled by the builders the real chart uses."""
    lagna_idx = _SIGNS.index(lagna)
    rasi = {}
    for p, lon in placements.items():
        lon %= 360.0
        sign_idx = int(lon // 30.0)
        rasi[p] = PlanetData(
            planet=p, sign=_SIGNS[sign_idx], degrees=lon % 30.0,
            nakshatra="Ashwini", dignity="neutral",
            house=(sign_idx - lagna_idx) % 12 + 1,
            conjunctions=[], aspects=[], is_retrograde=False,
            longitude_abs=lon,
        )
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
        lagna=lagna, lagna_lord="Mars", ayanamsa_value=0.0,
        house_cusps=[(i * 30.0) for i in range(12)],
    )


def _mid(sign_idx: int) -> float:
    return (sign_idx % 12) * 30.0 + 15.0


# ---------------------------------------------------------------------------
# The exhaustive table: Mars in each of the 12 houses x each natural benefic
# x (aspect, conjunction, none)
# ---------------------------------------------------------------------------

def test_dosha_house_table_is_the_verse():
    assert sorted(h for h, hit in _DOSHA_HOUSE.items() if hit) == [1, 4, 7, 8, 12]
    assert sorted(_DOSHA_HOUSE) == list(range(1, 13))


def _expected(house: int, benefic: str, influence: str) -> list[str]:
    """By hand: no yoga outside the five houses; inside them a benefic's
    aspect or conjunction cancels. Mercury joining Mars shares a sign with a
    malefic, so BPHS 3.11 makes him a malefic there and he cancels nothing."""
    if not _DOSHA_HOUSE[house] or influence == "none":
        return []
    if influence == "conjunction":
        return [] if benefic == "Mercury" else [joins(benefic)]
    return [aspects(benefic)]


@pytest.mark.parametrize("influence", ["aspect", "conjunction", "none"])
@pytest.mark.parametrize("benefic", ["Jupiter", "Venus", "Mercury", "Moon"])
@pytest.mark.parametrize("house", range(1, 13))
def test_every_house_every_benefic(house, benefic, influence):
    """Aries lagna, so Mars in house h is in the h-th sign. The benefic sits in
    Mars's sign (conjunction), in the 7th sign from Mars (aspect: every graha
    aspects its 7th), or in the 3rd from Mars, from where none of the four
    aspects Mars (Mars is then the 11th from it). The Moon is waxing: the Sun
    stands 90 degrees behind her, never in Mars's sign or the Moon's."""
    mars = _mid(house - 1)
    offset = {"aspect": 180.0, "conjunction": 0.0, "none": 60.0}[influence]
    placements = {"Mars": mars, benefic: mars + offset}
    if benefic == "Moon":
        placements["Sun"] = mars + offset - 90.0
    has, reasons = compat._mangal_dosha_raw(_snapshot("Aries", placements))
    assert has is _DOSHA_HOUSE[house]
    assert reasons == _expected(house, benefic, influence)


# Mars in Leo (the 4th from a Taurus lagna). Jupiter's sign -> the house Mars
# holds counted from Jupiter. Jupiter aspects or joins him from the 1st
# (conjunction), 5th, 7th and 9th only (BPHS 26.2-5).
_JUPITER_FROM = {
    "Aries": 5, "Taurus": 4, "Gemini": 3, "Cancer": 2, "Leo": 1, "Virgo": 12,
    "Libra": 11, "Scorpio": 10, "Sagittarius": 9, "Capricorn": 8,
    "Aquarius": 7, "Pisces": 6,
}


@pytest.mark.parametrize("jupiter_sign", _SIGNS)
def test_jupiter_all_twelve_placements(jupiter_sign):
    n = _JUPITER_FROM[jupiter_sign]
    assert (_SIGNS.index("Leo") - _SIGNS.index(jupiter_sign)) % 12 + 1 == n
    snap = _snapshot("Taurus", {"Mars": _mid(4), "Jupiter": _mid(_SIGNS.index(jupiter_sign))})
    expected = {1: [joins("Jupiter")], 5: [aspects("Jupiter")],
                7: [aspects("Jupiter")], 9: [aspects("Jupiter")]}.get(n, [])
    assert compat._mangal_dosha_raw(snap) == (True, expected)


# ---------------------------------------------------------------------------
# Which planets count as benefic (BPHS 3.11)
# ---------------------------------------------------------------------------

def test_waning_moon_cancels_nothing():
    """Moon in the 7th from Mars (she aspects him) and in Mars's sign, each
    with the Sun 90 degrees AHEAD of her: elongation 270, waning, a malefic."""
    for moon in (_mid(6) + 180.0, _mid(6)):
        snap = _snapshot("Aries", {"Mars": _mid(6), "Moon": moon, "Sun": moon + 90.0})
        assert compat._mangal_dosha_raw(snap) == (True, [])


def test_full_and_new_moon_are_not_waxing():
    """Elongation exactly 180 or 0 lies outside the open interval (0, 180)."""
    for elong in (180.0, 0.0):
        moon = _mid(6) + 180.0
        snap = _snapshot("Aries", {"Mars": _mid(6), "Moon": moon, "Sun": moon - elong})
        assert compat._mangal_dosha_raw(snap) == (True, [])


@pytest.mark.parametrize("companion", ["Sun", "Saturn", "Rahu", "Ketu"])
def test_mercury_with_a_malefic_cancels_nothing(companion):
    """Mercury in the 7th from Mars aspects him, but a malefic in Mercury's
    sign makes Mercury a malefic (BPHS 3.11)."""
    snap = _snapshot("Aries", {"Mars": _mid(6), "Mercury": _mid(0),
                               companion: _mid(0) + 5.0})
    assert compat._mangal_dosha_raw(snap) == (True, [])


def test_mercury_with_a_waning_moon_cancels_nothing():
    """Mercury and a waning Moon (Sun 90 degrees ahead) both in Aries, the 7th
    from Mars in Libra: neither is a benefic."""
    snap = _snapshot("Aries", {"Mars": _mid(6), "Mercury": _mid(0),
                               "Moon": _mid(0) + 5.0, "Sun": _mid(0) + 95.0})
    assert compat._mangal_dosha_raw(snap) == (True, [])


def test_mercury_with_a_waxing_moon_both_cancel_in_order():
    """Mercury and a waxing Moon (Sun 90 degrees behind) in Aries: both are
    benefics and both aspect Mars in Libra. Reasons come Jupiter, Venus,
    Mercury, Moon; callers serve the first."""
    snap = _snapshot("Aries", {"Mars": _mid(6), "Mercury": _mid(0),
                               "Moon": _mid(0) + 5.0, "Sun": _mid(0) - 85.0})
    assert compat._mangal_dosha_raw(snap) == (True, [aspects("Mercury"), aspects("Moon")])


@pytest.mark.parametrize("malefic, offset", [
    ("Saturn", 180.0), ("Saturn", 60.0), ("Saturn", -90.0),  # Mars is his 7th, 3rd, 10th
    ("Sun", 0.0), ("Sun", 180.0),
    ("Rahu", 0.0), ("Rahu", 120.0), ("Ketu", 240.0),
])
def test_a_malefic_aspect_or_conjunction_cancels_nothing(malefic, offset):
    snap = _snapshot("Aries", {"Mars": _mid(6), malefic: _mid(6) - offset})
    assert compat._mangal_dosha_raw(snap) == (True, [])


def test_mars_aspecting_a_benefic_is_not_the_benefic_aspecting_mars():
    """Mars in Gemini casts his 8th aspect on Jupiter in Capricorn; Gemini is
    the 6th from Capricorn, so Jupiter does not aspect Mars (calc #137)."""
    snap = _snapshot("Sagittarius", {"Mars": _mid(2), "Jupiter": _mid(9)})
    assert "Jupiter" in snap.rasi_chart["Mars"].aspects
    assert compat._mangal_dosha_raw(snap) == (True, [])


def test_no_mars_no_dosha():
    assert compat._mangal_dosha_raw(_snapshot("Aries", {"Sun": _mid(0)})) == (False, [])


# ---------------------------------------------------------------------------
# The popular cancellations are gone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lagna, placements, has", [
    ("Aries", {"Mars": _mid(0)}, True),                   # Mars in his own Aries, 1st
    ("Aries", {"Mars": _mid(7)}, True),                   # Mars in his own Scorpio, 8th
    ("Cancer", {"Mars": _mid(9)}, True),                  # Mars exalted in Capricorn, 7th
    ("Scorpio", {"Mars": _mid(10)}, True),                # Scorpio lagna, Mars 4th
    ("Taurus", {"Mars": _mid(4), "Moon": _mid(0), "Sun": _mid(0) - 90.0}, True),
    # ^ Moon in Aries; Leo is her 5th, so she does not aspect Mars
    ("Taurus", {"Mars": _mid(2)}, False),                 # Mars in the 2nd in Gemini
    ("Leo", {"Mars": _mid(5)}, False),                    # Mars in the 2nd in Virgo
])
def test_popular_cancellations_are_not_served(lagna, placements, has):
    assert compat._mangal_dosha_raw(_snapshot(lagna, placements)) == (has, [])


# ---------------------------------------------------------------------------
# The partner rule, BPHS 80.48-49
# ---------------------------------------------------------------------------

_FORMED = {"Mars": _mid(6)}                          # Aries lagna, Mars 7th, alone
_FORMED_2 = {"Mars": _mid(11)}                       # Aries lagna, Mars 12th, alone
_VENUS_JOINED = {"Mars": _mid(3), "Venus": _mid(3) + 5.0}   # Mars 4th, Venus with him
_JUPITER_ASPECTED = {"Mars": _mid(7), "Jupiter": _mid(3)}   # Mars 8th, Jupiter's 5th
_NONE = {"Mars": _mid(2)}                            # Mars 3rd


@pytest.mark.parametrize("a, b, expected_a, expected_b", [
    (_FORMED, _FORMED_2, (True, MUTUAL), (True, MUTUAL)),
    (_FORMED, _NONE, (True, ""), (False, "")),
    (_NONE, _FORMED, (False, ""), (True, "")),
    (_NONE, _NONE, (False, ""), (False, "")),
    # The partner whose Mars a benefic joins carries no yoga (v. 47 forms it
    # only "shubha-drig-yoga-hine"), so the other's yoga stands.
    (_FORMED, _VENUS_JOINED, (True, ""), (True, joins("Venus"))),
    (_VENUS_JOINED, _FORMED, (True, joins("Venus")), (True, "")),
    (_VENUS_JOINED, _JUPITER_ASPECTED, (True, joins("Venus")), (True, aspects("Jupiter"))),
])
def test_partner_rule(a, b, expected_a, expected_b):
    info_a, info_b = compat.compute_mangal_dosha(_snapshot("Aries", a), _snapshot("Aries", b))
    assert (info_a.has_dosha, info_a.cancellation) == expected_a
    assert (info_b.has_dosha, info_b.cancellation) == expected_b


def test_no_severity_grade_is_carried():
    assert [f.name for f in dataclasses.fields(compat.MangalDoshaInfo)] == [
        "has_dosha", "cancellation"]


def test_profile_counts_from_the_lagna_only():
    """Mars in the 3rd from an Aries lagna, a waxing Moon in Gemini with him:
    the old six-house count from the Moon flagged him (the 1st from the Moon).
    BPHS 80.47 counts from the lagna, so nothing is present."""
    snap = _snapshot("Aries", {"Mars": _mid(2), "Moon": _mid(2) + 5.0, "Sun": _mid(2) - 85.0})
    assert profile.mangal_dosha(snap) == {"present": False, "cancellation": None, "mars_house": 3}


# ---------------------------------------------------------------------------
# Worked examples through the served routes
# ---------------------------------------------------------------------------
#
# All at 6.9 N, 79.8 E, UTC+5:30. Sidereal positions from the Swiss Ephemeris
# directly (degrees within the sign), and the verdict reasoned from the verses:
#
#  second_house  1961-03-18 10:00  Lagna Taurus 4.23; Mars Gemini 14.76 (2nd).
#                Not one of v. 47's houses: no dosha.
#  venus_joins   1962-01-09 18:00  Lagna Gemini 23.94; Mars Sagittarius 18.63
#                (7th) with Venus Sagittarius 21.17. Jupiter Capricorn 19.06 and
#                Mercury Capricorn 9.72 (Mars is their 12th), Moon Aquarius 6.44
#                (Mars is her 11th): Venus alone cancels.
#  mercury_joins 1976-11-03 18:00  Lagna Aries 21.14; Mars Libra 24.12 (7th) with
#                Mercury Libra 15.27, the Sun Libra 17.68 and Rahu Libra 10.04, so
#                Mercury is a malefic. Venus Scorpio 23.25 (Mars is her 12th),
#                Jupiter Taurus 4.56 (his 6th), Moon Pisces 10.33 (her 8th): the
#                dosha stands, uncancelled.
#  waxing_moon   1960-06-05 14:00  Lagna Virgo 18.14; Mars Pisces 25.60 (7th);
#                Moon Virgo 24.01, the 7th from Mars, elongation 122.6 (waxing).
#                Jupiter Sagittarius 7.27 (Mars is his 4th), Venus Taurus 16.64
#                (her 11th), Mercury Gemini 11.00 (his 10th): the Moon cancels.
#  waning_moon   1965-05-25 06:00  Lagna Taurus 10.96; Mars Leo 21.78 (4th);
#                Moon Aquarius 26.21, the 7th from Mars, elongation 286.0
#                (waning). Jupiter and Venus Taurus (Mars is their 4th), Mercury
#                Aries 21.33 (his 5th): the dosha stands.
#  jupiter_ninth 1979-04-28 16:00  Lagna Virgo 9.65; Mars Pisces 22.96 (7th);
#                Jupiter Cancer 7.14 (Mars is his 9th: aspect); Venus Pisces
#                12.78 joins Mars; Mercury Pisces 17.80 joins Mars and is a
#                malefic there. Jupiter's reason is served first.
#  no_benefic    1985-12-17 21:00  Lagna Cancer 14.70; Mars Libra 8.10 (4th);
#                Jupiter Capricorn 21.67 (Mars is his 10th), Venus and Mercury
#                Scorpio (their 12th), Moon Aquarius 15.38 (her 9th): stands.

def _birth(name, d, t):
    return {"name": name, "birth_date": d, "birth_time": t, "birth_place": "X",
            "latitude": 6.9, "longitude": 79.8, "timezone_offset_hours": 5.5}


_WORKED = {
    "second_house": (_birth("w1", "1961-03-18", "10:00:00"), "Taurus",
                     {"Mars": ("Gemini", 2)}, False, None),
    "venus_joins": (_birth("w2", "1962-01-09", "18:00:00"), "Gemini",
                    {"Mars": ("Sagittarius", 7), "Venus": ("Sagittarius", 7),
                     "Jupiter": ("Capricorn", 8), "Mercury": ("Capricorn", 8),
                     "Moon": ("Aquarius", 9)}, True, joins("Venus")),
    "mercury_joins": (_birth("w3", "1976-11-03", "18:00:00"), "Aries",
                      {"Mars": ("Libra", 7), "Mercury": ("Libra", 7), "Sun": ("Libra", 7),
                       "Venus": ("Scorpio", 8), "Jupiter": ("Taurus", 2),
                       "Moon": ("Pisces", 12)}, True, None),
    "waxing_moon": (_birth("w4", "1960-06-05", "14:00:00"), "Virgo",
                    {"Mars": ("Pisces", 7), "Moon": ("Virgo", 1),
                     "Jupiter": ("Sagittarius", 4), "Venus": ("Taurus", 9),
                     "Mercury": ("Gemini", 10)}, True, aspects("Moon")),
    "waning_moon": (_birth("w5", "1965-05-25", "06:00:00"), "Taurus",
                    {"Mars": ("Leo", 4), "Moon": ("Aquarius", 10),
                     "Jupiter": ("Taurus", 1), "Venus": ("Taurus", 1),
                     "Mercury": ("Aries", 12)}, True, None),
    "jupiter_ninth": (_birth("w6", "1979-04-28", "16:00:00"), "Virgo",
                      {"Mars": ("Pisces", 7), "Jupiter": ("Cancer", 11),
                       "Venus": ("Pisces", 7), "Mercury": ("Pisces", 7)},
                      True, aspects("Jupiter")),
    "no_benefic": (_birth("w7", "1985-12-17", "21:00:00"), "Cancer",
                   {"Mars": ("Libra", 4), "Jupiter": ("Capricorn", 7),
                    "Venus": ("Scorpio", 5), "Mercury": ("Scorpio", 5),
                    "Moon": ("Aquarius", 8)}, True, None),
}


@pytest.mark.parametrize("key", list(_WORKED))
def test_worked_example_profile(key):
    birth, lagna, placements, present, cancellation = _WORKED[key]
    chart = client.post("/v1/chart", json=birth)
    assert chart.status_code == 200, chart.text
    body = chart.json()
    assert body["lagna"] == lagna
    served = {p["planet"]: (p["sign"], p["house"]) for p in body["rasi"]}
    for planet, placement in placements.items():
        assert served[planet] == placement, planet

    r = client.post("/v1/profile", json=birth)
    assert r.status_code == 200, r.text
    assert r.json()["mangal_dosha"] == {
        "present": present, "cancellation": cancellation,
        "mars_house": placements["Mars"][1]}


@pytest.mark.parametrize("key", list(_WORKED))
def test_worked_example_compat(key):
    """The partner (sample B, Mars in the 5th) carries no yoga, so each
    person's own first reason is served."""
    birth, _, _, present, cancellation = _WORKED[key]
    r = client.post("/v1/compat", json={"person_a": birth, "person_b": SAMPLE_B})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mangal_dosha_b"] == {"has_dosha": False, "cancellation": ""}
    assert body["mangal_dosha_a"] == {"has_dosha": present, "cancellation": cancellation or ""}


def test_worked_partner_rule_both_formed():
    """mercury_joins and no_benefic both carry the uncancelled yoga: vv. 48-49
    cancel it in each."""
    r = client.post("/v1/compat", json={"person_a": _WORKED["mercury_joins"][0],
                                        "person_b": _WORKED["no_benefic"][0]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mangal_dosha_a"] == {"has_dosha": True, "cancellation": MUTUAL}
    assert body["mangal_dosha_b"] == {"has_dosha": True, "cancellation": MUTUAL}


def test_worked_partner_rule_one_cancelled_by_a_benefic():
    """venus_joins carries no yoga (Venus joins Mars), so mercury_joins's
    yoga is not matched and stands."""
    r = client.post("/v1/compat", json={"person_a": _WORKED["mercury_joins"][0],
                                        "person_b": _WORKED["venus_joins"][0]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mangal_dosha_a"] == {"has_dosha": True, "cancellation": ""}
    assert body["mangal_dosha_b"] == {"has_dosha": True, "cancellation": joins("Venus")}
