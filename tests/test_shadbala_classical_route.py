"""Classical Shadbala and Bhavabala through the real /v1/strength route.

These assert properties BPHS chapter 27 (Santhanam) fixes for every chart,
so they hold whichever ephemeris runtime serves the positions:

* the required minimums (BPHS 27.32-33) are reachable: a classical Shadbala
  puts some grahas above them, where the simplified one put every graha of
  every chart below;
* the Sun's cheshta bala is his ayana bala (BPHS 27.18), which is zero only
  with the sayana Sun exactly on the southern solstice, so it is positive;
* naisargika bala is exactly k/7 rupa (BPHS 27.14);
* each served component stays inside its classical range;
* a house's Bhavabala is its lord's Shadbala plus the bhava digbala (0 to 1
  rupa, BPHS 27.28) plus the bhava drishti bala (BPHS 27.29), all in rupas,
  with no unscaled occupant term;
* where the Sun neither rises nor sets the classical value does not exist,
  and the route says so with a structured 422 instead of a number.

All births are synthetic.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CALC_SERVICE_TOKEN", "test")
os.environ.setdefault("PUBLIC_SOURCE_URL", "https://example.com")

from app.main import app  # noqa: E402

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

# Twelve synthetic births across two centuries, both hemispheres, day and
# night, every season.
_BIRTHS = [
    ("1918-10-16", "14:22:16", 13.0, 77.58, 5.5),
    ("1950-06-15", "06:00:00", 7.0, 80.0, 5.5),
    ("1962-02-04", "23:40:00", 28.6, 77.2, 5.5),
    ("1975-12-01", "12:30:00", 6.9, 79.8, 5.5),
    ("1984-09-21", "03:15:00", 51.5, -0.1, 1.0),
    ("1991-03-11", "18:05:00", -33.9, 151.2, 11.0),
    ("1999-07-28", "09:50:00", 40.7, -74.0, -4.0),
    ("2003-01-17", "16:20:00", -23.5, -46.6, -2.0),
    ("2008-11-05", "01:05:00", 35.7, 139.7, 9.0),
    ("2012-05-20", "21:45:00", 19.1, 72.9, 5.5),
    ("2019-08-02", "11:11:00", 55.8, 37.6, 3.0),
    ("2024-04-08", "05:30:00", -1.3, 36.8, 3.0),
]

_SEVENTHS = {"Saturn": 1, "Mars": 2, "Mercury": 3, "Jupiter": 4,
             "Venus": 5, "Moon": 6, "Sun": 7}


def _person(date, time, lat, lon, tz):
    return {
        "name": "synthetic", "birth_date": date, "birth_time": time,
        "birth_place": "Synthetic", "latitude": lat, "longitude": lon,
        "timezone_offset_hours": tz,
    }


@pytest.fixture(scope="module")
def served():
    bodies = []
    for birth in _BIRTHS:
        r = client.post("/v1/strength", json=_person(*birth))
        assert r.status_code == 200, r.text
        bodies.append(r.json())
    return bodies


def test_required_minimums_are_reachable(served):
    """Finding calc:2: the simplified Shadbala put every graha of every chart
    below its BPHS 27.32-33 minimum. Over twelve charts, classical Shadbala
    puts a real share of them at or above it."""
    rows = [item for body in served for item in body["shadbala"]]
    assert len(rows) == 84
    meeting = [item for item in rows if not item["is_below_minimum"]]
    assert len(meeting) >= 10, (
        f"only {len(meeting)} of 84 grahas reach their minimum Shadbala")
    for item in rows:
        assert item["is_below_minimum"] == (item["total_bala"] < item["minimum_bala"])


def test_sun_cheshta_is_his_ayana_bala(served):
    """BPHS 27.18: the Sun's cheshta bala is his ayana bala, never a flat 0."""
    for body in served:
        sun = next(i for i in body["shadbala"] if i["planet"] == "Sun")
        assert 0.0 < sun["cheshta_bala"] <= 1.0


def test_naisargika_is_exact_sevenths(served):
    for body in served:
        for item in body["shadbala"]:
            want = round(_SEVENTHS[item["planet"]] / 7.0, 3)
            assert item["naisargika_bala"] == want


def test_components_inside_classical_ranges(served):
    """Sthana at most 480 virupas (uchcha 60 + saptavargaja 315 + ojayugma
    30 + kendradi 60 + drekkana 15); dig and cheshta at most 60."""
    for body in served:
        for item in body["shadbala"]:
            assert 0.0 <= item["sthana_bala"] <= 8.0
            assert 0.0 <= item["dig_bala"] <= 1.0
            assert 0.0 <= item["cheshta_bala"] <= 1.0


def test_dig_bala_is_continuous_not_per_house(served):
    """BPHS 27.7 measures the arc from a cardinal point, divided by three: a
    continuous value, not a whole-sign house count in steps of 10."""
    values = {item["dig_bala"] for body in served for item in body["shadbala"]}
    steps = {round(k / 6.0, 3) for k in range(7)}
    assert not values <= steps, sorted(values)


def test_bhavabala_is_lord_plus_digbala_plus_drishti_in_rupas(served):
    """BPHS 27.26-29: bhavadhipati (the lord's Shadbala) + bhava digbala (0 to
    60 virupas) + bhava drishti bala, all in rupas. The drishti bala lies
    between -60 virupas (a quarter of the full aspect of each of the Sun,
    Mars, Saturn and a waning Moon; a malefic Mercury's quarter is outweighed
    by his full aspect, added on top) and +180 (a quarter of Venus and a
    waxing Moon, a quarter plus the whole of Jupiter and of Mercury)."""
    for body in served:
        totals = {i["planet"]: i["total_bala"] for i in body["shadbala"]}
        for house in body["bhavabala"]:
            dig = house["bala_total"] - house["bhava_adhipathi_bala"] - house["bhava_drik"]
            assert -0.002 <= dig <= 1.002, house
            assert -60 / 60 - 0.001 <= house["bhava_drik"] <= 180 / 60 + 0.001, house
            assert house["bhava_adhipathi_bala"] in {round(t, 3) for t in totals.values()}


def test_polar_day_has_no_classical_shadbala():
    """At 78 N on midsummer the Sun does not set: tribhaga, hora and vara
    bala (BPHS 27.12-13) have no day frame, so no classical value exists.
    The route refuses with a structured 422 rather than serve a number."""
    r = client.post("/v1/strength", json=_person("2000-06-21", "12:00:00", 78.2, 15.6, 2.0))
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "strength_undefined"
