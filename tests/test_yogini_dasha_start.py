"""Yogini dasha: the starting yogini, checked against the classical rule.

THE RULE
--------
BPHS (Brihat Parashara Hora Shastra) ch. 46, sloka 199 in the standard Sanskrit
numbering: take the number of the birth nakshatra (Ashwini = 1), add three and
divide by eight; the remainder, counted from one, names the yogini in the order
Mangala, Pingala, Dhanya, Bhramari, Bhadrika, Ulka, Siddha, Sankata (a remainder
of 0 is the eighth, Sankata). So Ashwini (1 + 3 = 4) starts Bhramari, not Mangala.

The engine used to take the ZERO-BASED nakshatra index mod 8 with no +3, which
started Ashwini on Mangala and put every chart's whole Yogini timeline three
periods out of step (the two rules always differ by 3 mod 8, so they never agree).

HOW THE EXPECTED VALUES WERE OBTAINED (never from the code under test)
---------------------------------------------------------------------
* ``_CLASSICAL_START`` is written out BY HAND from the rule above, one row per
  nakshatra: (n + 3) mod 8 -> yogini, then the yogini's graha.
* ``test_hand_table_agrees_with_the_library_star_lists`` cross-checks that hand
  table against a second, independent source: the star lists in the astronomy
  library's own yogini module (``dhasa_adhipathi_dict``), which map each graha to
  the birth stars whose yogini it rules.
* Worked examples are computed by hand in their docstrings.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bphs_core import utils
from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData
from bphs_core.dashas import _yogini_dashas, get_active_dasha, get_dasha_timeline

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

# Hand-derived: nakshatra (number) -> (n + 3) mod 8 -> starting yogini -> graha.
# Remainders: 1 Mangala/Moon, 2 Pingala/Sun, 3 Dhanya/Jupiter, 4 Bhramari/Mars,
# 5 Bhadrika/Mercury, 6 Ulka/Saturn, 7 Siddha/Venus, 0 Sankata/Rahu.
_CLASSICAL_START: dict[str, tuple[str, str]] = {
    "Ashwini": ("Bhramari", "Mars"),             # 1 + 3 = 4
    "Bharani": ("Bhadrika", "Mercury"),          # 2 + 3 = 5
    "Krittika": ("Ulka", "Saturn"),              # 3 + 3 = 6
    "Rohini": ("Siddha", "Venus"),               # 4 + 3 = 7
    "Mrigashira": ("Sankata", "Rahu"),           # 5 + 3 = 8 -> 0
    "Ardra": ("Mangala", "Moon"),                # 6 + 3 = 9 -> 1
    "Punarvasu": ("Pingala", "Sun"),             # 7 + 3 = 10 -> 2
    "Pushya": ("Dhanya", "Jupiter"),             # 8 + 3 = 11 -> 3
    "Ashlesha": ("Bhramari", "Mars"),            # 9 + 3 = 12 -> 4
    "Magha": ("Bhadrika", "Mercury"),            # 10 + 3 = 13 -> 5
    "Purva Phalguni": ("Ulka", "Saturn"),        # 11 + 3 = 14 -> 6
    "Uttara Phalguni": ("Siddha", "Venus"),      # 12 + 3 = 15 -> 7
    "Hasta": ("Sankata", "Rahu"),                # 13 + 3 = 16 -> 0
    "Chitra": ("Mangala", "Moon"),               # 14 + 3 = 17 -> 1
    "Swati": ("Pingala", "Sun"),                 # 15 + 3 = 18 -> 2
    "Vishakha": ("Dhanya", "Jupiter"),           # 16 + 3 = 19 -> 3
    "Anuradha": ("Bhramari", "Mars"),            # 17 + 3 = 20 -> 4
    "Jyeshtha": ("Bhadrika", "Mercury"),         # 18 + 3 = 21 -> 5
    "Mula": ("Ulka", "Saturn"),                  # 19 + 3 = 22 -> 6
    "Purva Ashadha": ("Siddha", "Venus"),        # 20 + 3 = 23 -> 7
    "Uttara Ashadha": ("Sankata", "Rahu"),       # 21 + 3 = 24 -> 0
    "Shravana": ("Mangala", "Moon"),             # 22 + 3 = 25 -> 1
    "Dhanishta": ("Pingala", "Sun"),             # 23 + 3 = 26 -> 2
    "Shatabhisha": ("Dhanya", "Jupiter"),        # 24 + 3 = 27 -> 3
    "Purva Bhadrapada": ("Bhramari", "Mars"),    # 25 + 3 = 28 -> 4
    "Uttara Bhadrapada": ("Bhadrika", "Mercury"),  # 26 + 3 = 29 -> 5
    "Revati": ("Ulka", "Saturn"),                # 27 + 3 = 30 -> 6
}
_YEARS = {"Mangala": 1, "Pingala": 2, "Dhanya": 3, "Bhramari": 4,
          "Bhadrika": 5, "Ulka": 6, "Siddha": 7, "Sankata": 8}

_NAK = 360.0 / 27.0
_BIRTH = datetime.datetime(1990, 1, 1, 12, 0)


def _snapshot_with_moon_at(longitude: float) -> ChartSnapshot:
    sign_idx = int(longitude // 30)
    moon = PlanetData(
        planet="Moon", sign=utils.SIGNS[sign_idx], degrees=longitude - sign_idx * 30,
        nakshatra=utils.longitude_to_nakshatra(longitude), dignity="neutral", house=1,
        conjunctions=[], aspects=[], is_retrograde=False, longitude_abs=longitude,
    )
    person = PersonalData(name="t", birth_date=_BIRTH.date(), birth_time=_BIRTH.time(),
                          birth_place="Sample City", latitude=10.0, longitude=10.0,
                          timezone_offset_hours=0.0)
    return ChartSnapshot(
        person=person, rasi_chart={"Moon": moon}, hora_chart={}, drekkana_chart={},
        navamsa_chart={}, decamsa_chart={}, dwadasamsa_chart={}, chaturvimsa_chart={},
        trimshamsa_chart={}, saptamsa_chart={}, shashtyamsa_chart={},
        lagna="Aries", lagna_lord="Mars", ayanamsa_value=0.0,
    )


def test_hand_table_covers_every_nakshatra_in_order():
    assert list(_CLASSICAL_START) == list(utils.NAKSHATRAS)


def test_hand_table_agrees_with_the_library_star_lists():
    """Second, independent source for the same table: the library's yogini module
    lists, per graha (library planet ids: Sun 0, Moon 1, Mars 2, Mercury 3,
    Jupiter 4, Venus 5, Saturn 6, Rahu 7), the 1-based birth stars that start on
    that graha's yogini."""
    from jhora.horoscope.dhasa.graha import yogini as lib_yogini

    lib_names = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu"]
    from_library = {}
    for pid, stars in lib_yogini.dhasa_adhipathi_dict.items():
        for star in stars:
            from_library[utils.NAKSHATRAS[star - 1]] = lib_names[pid]
    assert from_library == {nak: graha for nak, (_y, graha) in _CLASSICAL_START.items()}


@pytest.mark.parametrize("nakshatra", list(_CLASSICAL_START))
def test_first_yogini_follows_bphs_for_every_nakshatra(nakshatra):
    """Exhaustive over all 27 nakshatras, through the real dasha module."""
    n = utils.NAKSHATRAS.index(nakshatra)
    snap = _snapshot_with_moon_at(n * _NAK + _NAK / 2)
    first = _yogini_dashas(snap, _BIRTH)[0]
    yogini, graha = _CLASSICAL_START[nakshatra]
    assert first.lord == graha, (
        f"Moon in {nakshatra} must start the {yogini} yogini ({graha}); served {first.lord}"
    )
    assert first.duration_years == _YEARS[yogini]


def test_worked_example_ashwini_balance():
    """Moon exactly half-way through Ashwini (6 deg 40 min).

    By hand: 1 + 3 = 4 -> Bhramari (Mars), 4 years. Half the nakshatra has
    elapsed, so 2 years of Bhramari ran before birth: the first period spans
    birth - 2y .. birth + 2y, then Bhadrika (Mercury, 5y), Ulka (Saturn, 6y)."""
    periods = _yogini_dashas(_snapshot_with_moon_at(_NAK / 2), _BIRTH)
    two_years = datetime.timedelta(days=2 * 365.25)
    assert periods[0].lord == "Mars"
    assert periods[0].start_date == _BIRTH - two_years
    assert periods[0].end_date == _BIRTH + two_years
    assert [p.lord for p in periods[1:3]] == ["Mercury", "Saturn"]
    assert [p.duration_years for p in periods[1:3]] == [5, 6]


def test_worked_example_uttara_ashadha_active_period():
    """Moon at 270.5 deg (Capricorn 0 deg 30 min) lies in Uttara Ashadha
    (266 deg 40 min .. 280 deg). By hand: 21 + 3 = 24, remainder 0 -> Sankata
    (Rahu, 8 years); the period active at birth must be Rahu's, and the next
    yogini after Sankata wraps to Mangala (Moon, 1 year)."""
    snap = _snapshot_with_moon_at(270.5)
    active = get_active_dasha(snap, _BIRTH, system="yogini")
    assert active is not None and active.lord == "Rahu"
    timeline = get_dasha_timeline(snap, _BIRTH, _BIRTH + datetime.timedelta(days=3650),
                                  ["yogini"])
    assert [p.lord for p in timeline[:2]] == ["Rahu", "Moon"]


def test_route_serves_the_bphs_start_for_every_nakshatra():
    """Through POST /v1/chart and POST /v1/dashas: births every twelve hours for
    28 days sweep the Moon through all 27 nakshatras (it moves 12-15 deg a day,
    so one birth a day can step over a 13.3 deg nakshatra). For each,
    the nakshatra comes from the served rasi Moon and the expected lord from the
    hand table; the period that contains the birth must be that lord's."""
    seen = set()
    # One context-managed client, so every request reuses one event loop and its
    # worker threads: an unmanaged client starts a fresh thread per request, and
    # each thread that touches the ephemeris keeps its data files open.
    with TestClient(app, headers={"X-Calc-Service-Token": "test"}) as route:
        for half_day in range(56):
            _check_one_birth(route, half_day, seen)
    assert seen == set(utils.NAKSHATRAS)


def _check_one_birth(route: TestClient, half_day: int, seen: set) -> None:
    birth = datetime.date(2001, 3, 1) + datetime.timedelta(days=half_day // 2)
    clock = datetime.time(12 * (half_day % 2), 0)
    person = {
        "name": "sample", "birth_date": birth.isoformat(), "birth_time": clock.isoformat(),
        "birth_place": "Sample City", "latitude": 12.0, "longitude": 77.0,
        "timezone_offset_hours": 5.5,
    }
    chart = route.post("/v1/chart", json=person)
    assert chart.status_code == 200, chart.text
    moon = next(p for p in chart.json()["rasi"] if p["planet"] == "Moon")
    nakshatra = moon["nakshatra"]
    seen.add(nakshatra)
    r = route.post("/v1/dashas", json={
        **person, "from_date": birth.isoformat(),
        "to_date": (birth + datetime.timedelta(days=30)).isoformat(),
        "systems": ["yogini"],
    })
    assert r.status_code == 200, r.text
    born = datetime.datetime.combine(birth, clock)
    active = [p for p in r.json()
              if datetime.datetime.fromisoformat(p["start_date"]) <= born
              < datetime.datetime.fromisoformat(p["end_date"])]
    assert len(active) == 1, r.json()
    assert active[0]["lord"] == _CLASSICAL_START[nakshatra][1], (
        f"{born}: Moon in {nakshatra} served {active[0]['lord']}"
    )
