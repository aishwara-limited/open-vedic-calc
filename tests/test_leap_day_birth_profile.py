"""A birth on 29 February gets a profile, whatever its eightieth year.

THE DEFECT THIS CLOSED
----------------------
The lifetime Sade Sati sweep behind ``POST /v1/profile`` runs from the birth
date to a horizon eighty years on. The horizon used to be built as the calendar
anniversary -- the birth day and month in the birth year plus eighty. That date
does not exist for a 29 February birth whose eightieth year is not a leap year,
and the construction raised, uncaught: the whole profile (avkahada, kalsarp,
Sade Sati, numerology, mangal dosha) answered 500. Inside the served span that
is every 29 February birth of 1820, 2020, 2120 and 2220 -- the years whose
eightieth anniversary falls in 1900, 2100, 2200 and 2300.

THE RULE
--------
The horizon is eighty years of 365.25 days counted from the birth date -- the
year every dasha period in this engine is projected with
(``bphs_core/dashas.py::vimshottari_mahadashas``). A day count exists for every
birth date, so the sweep cannot fail on the calendar.

WHAT IS PINNED
--------------
* ``POST /v1/profile`` answers 200 for each of those four birth dates.
* Every 29 February birth whose sweep stays inside the shipped data completes,
  and its sweep ends at the last quarterly step inside the eighty-year horizon.
* The horizon is exactly eighty of the dasha projection's own years, measured
  from the dasha output rather than from a constant restated here.
* No birth date that already worked changes: over every date in the served
  span, the sweep to the old calendar anniversary and the sweep to the new
  horizon take the same number of quarterly steps, so they read the same
  instants and serve the same periods.

Synthetic charts only; no personal data.
"""
from __future__ import annotations

import calendar
import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import MAX_EPHEMERIS_DATE, MIN_EPHEMERIS_DATE
from bphs_core import dashas, profile, transits
from bphs_core.chart import Chart, PersonalData

_PERSON = {
    "name": "sample", "birth_time": "06:00:00", "birth_place": "Sample City",
    "latitude": 7.0, "longitude": 80.0, "timezone_offset_hours": 5.5,
}
_HORIZON_YEARS = 80
_STEP_DAYS = profile._SADE_SATI_SCAN_STEP_DAYS


@pytest.fixture(scope="module")
def client():
    """One context-managed client for the module (one event loop, one set of
    worker threads). Server exceptions are returned as responses, so a defect
    reads as the 500 a caller would see."""
    with TestClient(
        app, headers={"X-Calc-Service-Token": "test"}, raise_server_exceptions=False
    ) as c:
        yield c


@pytest.fixture(scope="module")
def snapshot():
    """One synthetic natal chart; the sweep only reads its Moon sign."""
    return Chart(PersonalData(
        name="sample", birth_date=datetime.datetime(1990, 6, 15),
        birth_time=datetime.time(6, 0), birth_place="Sample City",
        latitude=7.0, longitude=80.0, timezone_offset_hours=5.5,
    )).snapshot()


def _dasha_year_days(snapshot) -> float:
    """Length of one dasha year in days, read off the dasha projection itself:
    nine consecutive Vimshottari mahadashas are one full cycle of 120 years."""
    periods = dashas.vimshottari_mahadashas(snapshot, datetime.datetime(1990, 6, 15, 6, 0))
    cycle = periods[8].end_date - periods[0].start_date
    assert sum(p.duration_years for p in periods[:9]) == 120
    return cycle / datetime.timedelta(days=1) / 120


# Every 29 February in the served birth-date span.
_ALL_LEAP_DAY_BIRTHS = [
    datetime.date(year, 2, 29)
    for year in range(MIN_EPHEMERIS_DATE.year, MAX_EPHEMERIS_DATE.year + 1)
    if calendar.isleap(year)
    and MIN_EPHEMERIS_DATE <= datetime.date(year, 2, 29) <= MAX_EPHEMERIS_DATE
]
# The ones whose calendar anniversary does not exist: eightieth year not leap.
_NO_ANNIVERSARY = [
    d for d in _ALL_LEAP_DAY_BIRTHS if not calendar.isleap(d.year + _HORIZON_YEARS)
]


def test_the_affected_birth_dates_are_the_four_century_cases():
    """The failing set is derived from the calendar, and it is these four."""
    assert [d.isoformat() for d in _NO_ANNIVERSARY] == [
        "1820-02-29", "2020-02-29", "2120-02-29", "2220-02-29",
    ]
    assert len(_ALL_LEAP_DAY_BIRTHS) == 145


@pytest.mark.parametrize("birth", _NO_ANNIVERSARY, ids=lambda d: d.isoformat())
def test_profile_serves_a_leap_day_birth_whose_eightieth_year_is_not_leap(client, birth):
    r = client.post("/v1/profile", json={**_PERSON, "birth_date": birth.isoformat()})
    assert r.status_code == 200, r.text
    periods = r.json()["sade_sati_lifetime"]
    # Eighty years hold more than two Saturn revolutions, so at least two Sade
    # Sati windows -- an empty list here would be a sweep that did not run.
    assert len(periods) >= 2
    horizon = birth + datetime.timedelta(days=_HORIZON_YEARS * 365.25)
    for period in periods:
        start = datetime.date.fromisoformat(period["start"])
        end = datetime.date.fromisoformat(period["end"])
        assert birth <= start <= end <= horizon
        assert period["phase"] in {"rising", "peak", "setting", "multi"}


@pytest.mark.parametrize(
    "birth",
    ["2016-02-29", "2024-02-29", "1920-02-29", "2000-02-29", "2020-02-28", "2020-03-01"],
)
def test_profile_still_serves_the_neighbouring_births(client, birth):
    r = client.post("/v1/profile", json={**_PERSON, "birth_date": birth})
    assert r.status_code == 200, r.text
    assert len(r.json()["sade_sati_lifetime"]) >= 2


def _swept_instants(monkeypatch, snapshot, birth: datetime.date) -> list[datetime.datetime]:
    """Run the real sweep and return every instant it asked the ephemeris about.

    The real Julian-Day helper still runs; the wrapper only records its argument.
    """
    seen: list[datetime.datetime] = []
    real = transits._jd_from_date

    def recording(dt):
        seen.append(dt)
        return real(dt)

    with monkeypatch.context() as patch:
        patch.setattr(transits, "_jd_from_date", recording)
        periods = profile.sade_sati_lifetime(snapshot, birth)
    assert isinstance(periods, list)
    return seen


# The sweep reads Saturn at every step, so a birth whose horizon runs past the
# shipped data is answered partly from the fallback engine. That is a separate
# matter from the calendar defect this module pins; the exhaustive run below is
# bounded to the births whose whole sweep stays inside the data, and says so.
_SWEEP_INSIDE_DATA = [
    d for d in _ALL_LEAP_DAY_BIRTHS
    if d + datetime.timedelta(days=_HORIZON_YEARS * 365.25) <= MAX_EPHEMERIS_DATE
]


def test_every_leap_day_birth_completes_its_sweep(monkeypatch, snapshot):
    """Exhaustive over the 29 February births whose sweep stays inside the data."""
    assert len(_SWEEP_INSIDE_DATA) == 125
    assert set(_NO_ANNIVERSARY) <= set(_SWEEP_INSIDE_DATA)
    horizon = datetime.timedelta(days=_HORIZON_YEARS * _dasha_year_days(snapshot))
    step = datetime.timedelta(days=_STEP_DAYS)
    for birth in _SWEEP_INSIDE_DATA:
        start = datetime.datetime(birth.year, birth.month, birth.day)
        seen = _swept_instants(monkeypatch, snapshot, birth)
        assert seen[0] == start, birth
        assert all(b - a == step for a, b in zip(seen, seen[1:])), birth
        # The last step taken is the last one inside the horizon.
        assert seen[-1] <= start + horizon < seen[-1] + step, birth


def test_the_horizon_is_eighty_of_the_dasha_projections_own_years(monkeypatch, snapshot):
    """Eighty years of the length the dasha projection uses. Worked by hand:
    80 x 365.25 d = 29220 d; the quarterly step is 91 d; 29220 = 321 x 91 + 9,
    so the sweep takes steps 0..321 (322 instants) and its last step falls nine
    days short of the horizon."""
    assert _dasha_year_days(snapshot) == 365.25
    assert _STEP_DAYS == 91
    for birth in (datetime.date(2020, 2, 29), datetime.date(1990, 6, 15)):
        seen = _swept_instants(monkeypatch, snapshot, birth)
        start = datetime.datetime(birth.year, birth.month, birth.day)
        assert len(seen) == 322
        assert seen[-1] - start == datetime.timedelta(days=29211)
        assert start + datetime.timedelta(days=29220) - seen[-1] == datetime.timedelta(days=9)


def test_no_birth_date_that_already_worked_changes_its_sweep():
    """Exhaustive over the served span: wherever the old calendar anniversary
    exists, a sweep to it and a sweep to the new horizon take the same number of
    quarterly steps -- the same instants read, the same periods served."""
    new_steps = 29220 // _STEP_DAYS
    assert new_steps == 321
    day = MIN_EPHEMERIS_DATE
    one_day = datetime.timedelta(days=1)
    checked = without_anniversary = 0
    while day <= MAX_EPHEMERIS_DATE:
        try:
            anniversary = day.replace(year=day.year + _HORIZON_YEARS)
        except ValueError:
            without_anniversary += 1
        else:
            assert (anniversary - day).days // _STEP_DAYS == new_steps, day
            checked += 1
        day += one_day
    assert without_anniversary == len(_NO_ANNIVERSARY) == 4
    assert checked == (MAX_EPHEMERIS_DATE - MIN_EPHEMERIS_DATE).days + 1 - 4
