"""Bhava-Chalit house: a graha is in the house whose cusp interval holds it.

THE RULE
--------
The chalit cusps served in ``bhava_chalit_cusps`` are the sidereal starts of the
twelve houses (cusp 1 = the ascendant degree). A graha at longitude L is in
house i when it lies on the arc from cusp i forward to cusp i + 1, i.e. when
(L - cusp_i) mod 360 < (cusp_{i+1} - cusp_i) mod 360.

THE DEFECT THIS CLOSED
----------------------
The engine used to walk the cusps from the 12th downward and return the first
cusp the graha was less than 180 degrees past. The 12th cusp is checked first and
is less than 180 degrees behind every graha in chalit houses 12, 1, 2, 3, 4 and 5,
so all of them were served as house 12 and houses 1 to 5 were never served.

The expected houses here come from the interval rule applied to cusps that were
read independently (the swisseph house call made in the test itself, or the
served cusps), never from the function under test.
"""
from __future__ import annotations

import datetime
import random
from collections import Counter

import pytest
import swisseph as swe
from fastapi.testclient import TestClient

from app.main import app
from bphs_core import utils
from bphs_core.chart import _compute_house

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

# Uneven, wrapping cusps (cusp 10 crosses 0 deg) -- the sidereal Placidus cusps of
# the worked example below, rounded to 0.1 deg.
_CUSPS = [94.3, 122.6, 153.6, 185.9, 216.8, 245.9, 274.3, 302.6, 333.6, 5.9, 36.8, 65.9]


def _interval_house(lon: float, cusps: list[float]) -> int:
    for i in range(12):
        if (lon - cusps[i]) % 360 < (cusps[(i + 1) % 12] - cusps[i]) % 360:
            return i + 1
    raise AssertionError((lon, cusps))


@pytest.mark.parametrize("house", range(1, 13))
def test_every_house_is_reachable(house):
    """Exhaustive over the 12 houses: the middle of each cusp interval, the
    cusp itself, and a point just before the next cusp are all in that house."""
    start, end = _CUSPS[house - 1], _CUSPS[house % 12]
    span = (end - start) % 360
    for lon in (start, (start + span / 2) % 360, (start + span - 1e-6) % 360):
        assert _compute_house(lon, _CUSPS) == house, (house, lon)


def test_just_past_the_first_cusp_is_house_one():
    """By hand: 106.5 deg is 12.2 deg past cusp 1 (94.3) and short of cusp 2
    (122.6), so house 1 -- it is also ~40.6 deg past cusp 12 (65.9), which is
    what the old walk answered."""
    assert _compute_house(106.5, _CUSPS) == 1
    assert _compute_house(94.29, _CUSPS) == 12
    assert _compute_house(0.0, _CUSPS) == 9      # cusp 9 at 333.6, cusp 10 at 5.9


def test_a_longitude_on_no_interval_fails_closed():
    """A NaN longitude lies on no arc; the function must refuse rather than
    hand back a plausible house (the old walk returned 1)."""
    with pytest.raises(ValueError):
        _compute_house(float("nan"), _CUSPS)


def test_worked_example_ketu_in_house_one():
    """1990-05-15 10:30 at UTC+5:30, 6.93 N 79.86 E (fictitious). The sidereal
    Placidus cusps and Ketu are computed here straight from the ephemeris
    (Lahiri, true node), independently of the chart module: Ketu sits ~12 deg
    past cusp 1 and well short of cusp 2, so its chalit house is 1."""
    jd_ut = swe.julday(1990, 5, 15, 5.0)          # 10:30 local - 5:30
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    cusps, _ascmc = swe.houses_ex(jd_ut, 6.93, 79.86, b"P", swe.FLG_SIDEREAL)
    rahu = swe.calc_ut(jd_ut, swe.TRUE_NODE, swe.FLG_SIDEREAL)[0][0]
    ketu = (rahu + 180.0) % 360
    assert _interval_house(ketu, list(cusps)) == 1

    r = client.post("/v1/chart", json={
        "name": "sample", "birth_date": "1990-05-15", "birth_time": "10:30:00",
        "birth_place": "Sample City", "latitude": 6.93, "longitude": 79.86,
        "timezone_offset_hours": 5.5,
    })
    assert r.status_code == 200, r.text
    served = {p["planet"]: p["chalit_house"] for p in r.json()["rasi"]}
    assert served["Ketu"] == 1


def test_route_chalit_house_agrees_with_the_served_cusps():
    """Through POST /v1/chart on 40 fictitious births: every graha's served
    chalit_house is the interval house under the served cusps, and houses 1 to 5
    are actually served (the old walk never returned them)."""
    rng = random.Random(4)
    seen: Counter[int] = Counter()
    # One context-managed client reuses one event loop's worker threads; an
    # unmanaged client starts a fresh thread per request (see the Yogini sweep).
    with TestClient(app, headers={"X-Calc-Service-Token": "test"}) as route:
        bodies = [_random_chart(route, rng) for _ in range(40)]
    for day, body in bodies:
        cusps = body["bhava_chalit_cusps"]
        for p in body["rasi"]:
            lon = utils.SIGNS.index(p["sign"]) * 30 + p["degrees"]
            if min(min((lon - c) % 360, (c - lon) % 360) for c in cusps) < 1e-3:
                continue  # served values are rounded; skip a graha sitting on a cusp
            assert p["chalit_house"] == _interval_house(lon, cusps), (day, p["planet"])
            seen[p["chalit_house"]] += 1
    assert all(seen[h] for h in range(1, 6)), seen


def _random_chart(route: TestClient, rng: random.Random) -> tuple[datetime.date, dict]:
    day = datetime.date(1940, 1, 1) + datetime.timedelta(days=rng.randrange(0, 365 * 80))
    r = route.post("/v1/chart", json={
        "name": "sample", "birth_date": day.isoformat(),
        "birth_time": f"{rng.randrange(24):02d}:{rng.randrange(60):02d}:00",
        "birth_place": "Sample City", "latitude": round(rng.uniform(-55, 55), 2),
        "longitude": round(rng.uniform(-180, 180), 2), "timezone_offset_hours": 0.0,
    })
    assert r.status_code == 200, r.text
    return day, r.json()
