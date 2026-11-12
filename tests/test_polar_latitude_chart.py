"""A birth beyond the polar circles gets a chart, on the documented fallback.

THE DEFECT THIS CLOSED
----------------------
Placidus is undefined above about 66.6 degrees of latitude, and the chart module
already had the fallback for that: catch the Placidus failure, use the equal-house
call instead and say so in ``house_system``. It never ran on a real polar input.
The planet positions were taken from the library's rasi-chart call, which also
computes the library's OWN Placidus ascendant -- a value the engine then threw
away -- and that call raised first, so every route returned 500 for a birth at
67 degrees or beyond. The planets now come from the library's position call
alone; the ascendant was always computed separately, with the fallback.

WHAT IS PINNED
--------------
* POST /v1/chart at 67, 70, 89.9 and 90 degrees, north and south, is 200 with
  ``house_system == "equatorial"`` and twelve cusps.
* 66 degrees still computes Placidus (the fallback is not taken early).
* Graha longitudes are geocentric, so they cannot depend on the latitude: a
  polar birth's rasi chart equals the same instant's chart at 60 degrees.
* The other chart-built routes answer too (dashas, yogas), and the muhurat
  route reaches its own polar-night handling (a structured 422) instead of
  failing in the natal chart first.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    """One context-managed client for the module, so every request reuses one
    event loop and its worker threads (an unmanaged client starts a fresh
    thread per request, and each thread that computes keeps its own ephemeris
    data files open)."""
    with TestClient(app, headers={"X-Calc-Service-Token": "test"}) as c:
        yield c

_PERSON = {
    "name": "sample", "birth_date": "1990-06-15", "birth_time": "10:30:00",
    "birth_place": "Sample City", "longitude": 18.96, "timezone_offset_hours": 1.0,
}
_POLAR = [67.0, 70.0, 89.9, 90.0, -67.0, -70.0, -89.9, -90.0]


def _chart(client: TestClient, lat: float):
    return client.post("/v1/chart", json={**_PERSON, "latitude": lat})


@pytest.mark.parametrize("lat", _POLAR)
def test_polar_birth_takes_the_equal_house_fallback(client, lat):
    r = _chart(client, lat)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["house_system"] == "equatorial"
    assert len(body["bhava_chalit_cusps"]) == 12
    assert len(body["rasi"]) == 9
    assert all(1 <= p["chalit_house"] <= 12 for p in body["rasi"])


def test_just_inside_the_polar_circle_is_still_placidus(client):
    r = _chart(client, 66.0)
    assert r.status_code == 200, r.text
    assert r.json()["house_system"] == "placidus"


@pytest.mark.parametrize("lat", [70.0, -90.0])
def test_polar_graha_positions_equal_the_same_instant_elsewhere(client, lat):
    polar, reference = _chart(client, lat), _chart(client, 60.0)
    assert polar.status_code == 200 and reference.status_code == 200

    def positions(r):
        return {p["planet"]: (p["sign"], p["degrees"], p["nakshatra"]) for p in r.json()["rasi"]}
    assert positions(polar) == positions(reference)


@pytest.mark.parametrize("lat", [70.0, -70.0])
def test_other_chart_routes_answer_for_a_polar_birth(client, lat):
    person = {**_PERSON, "latitude": lat}
    r = client.post("/v1/dashas", json={**person, "from_date": "2000-01-01",
                                         "to_date": "2010-01-01",
                                         "systems": ["vimshottari", "yogini"]})
    assert r.status_code == 200, r.text
    assert r.json()
    r = client.post("/v1/yogas", json=person)
    assert r.status_code == 200, r.text


def test_polar_night_muhurat_is_the_structured_limb_error(client):
    """The muhurat route builds the natal chart first, so a polar birth used to
    500 before the day scan ran. Now the scan runs, and a day with no sunrise
    (78.2 N in December) answers the structured 422 the handler promises."""
    r = client.post("/v1/muhurat", json={**_PERSON, "latitude": 78.2,
                                          "start_date": "2026-12-20",
                                          "end_date": "2026-12-21"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "muhurat_limb_error"
