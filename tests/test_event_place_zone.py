"""The muhurat scans are computed for the EVENT's place, in the EVENT's zone.

A muhurat is a time for an event: its sunrise, Rahu Kala, chogadiya and rising
sign belong to where and when the event is held, not to where the person was
born. And a clock offset is a property of a date, not of a person: London is
UTC+1 in July and UTC+0 in December, so one fixed offset cannot be right for a
July birth chart and a December event at once.

These tests pin, through the real routes and the real scan module:

* an optional event place (``event_latitude`` / ``event_longitude``) and IANA
  zone (``event_timezone``) on every muhurat request, kept separate from the
  natal person, whose own fixed offset still places the birth moment;
* the UTC offset resolved for EACH scanned date from the tz database;
* on a clock-change day, no candidate instant whose local wall time does not
  exist, is ambiguous, or sits on the other side of the change from the day's
  own offset;
* in the family scan, every member scored at the same absolute instant, at the
  one event place, while each member's natal Moon still comes from their own
  birth chart;
* a request without the event fields behaves exactly as before.

All data below is fictitious.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

LONDON = (51.5074, -0.1278)
COLOMBO = (6.9271, 79.8612)

# Born in London in July: the offset in force at the birth moment is +1 (BST).
SUMMER_BORN_LONDON = {
    "name": "fixture_a",
    "birth_date": "1990-07-04",
    "birth_time": "14:20:00",
    "birth_place": "Fixture City A",
    "latitude": LONDON[0],
    "longitude": LONDON[1],
    "timezone_offset_hours": 1.0,
}

# Born in Colombo: a different zone from the event's.
BORN_COLOMBO = {
    "name": "fixture_b",
    "birth_date": "1988-01-10",
    "birth_time": "07:45:00",
    "birth_place": "Fixture City B",
    "latitude": COLOMBO[0],
    "longitude": COLOMBO[1],
    "timezone_offset_hours": 5.5,
}

LONDON_EVENT = {
    "event_latitude": LONDON[0],
    "event_longitude": LONDON[1],
    "event_timezone": "Europe/London",
}

COLOMBO_EVENT = {
    "event_latitude": COLOMBO[0],
    "event_longitude": COLOMBO[1],
    "event_timezone": "Asia/Colombo",
}


def _hour(hhmm: str) -> int:
    return int(hhmm.split(":")[0])


def _minute_of_day(instant: str) -> int:
    hh, mm = instant.split(" ")[1].split(":")
    return int(hh) * 60 + int(mm)


def _ls():
    from bphs_core import lagna_shuddhi
    return lagna_shuddhi


def _spy_jd(monkeypatch) -> list[tuple[str, int, float]]:
    calls: list[tuple[str, int, float]] = []
    ls = _ls()
    real = ls._jd_for_local

    def spy(date_str, time_mins, tz_offset):
        calls.append((date_str, time_mins, tz_offset))
        return real(date_str, time_mins, tz_offset)

    monkeypatch.setattr(ls, "_jd_for_local", spy)
    return calls


# ---------------------------------------------------------------------------
# /v1/muhurat - the day panels
# ---------------------------------------------------------------------------

def test_december_day_uses_december_offset_not_the_summer_birth_offset():
    """A July-born London chart scanned for 15 December: sunrise is about 08:06
    GMT. The birth offset (+1) would put it at 09:06."""
    r = client.post("/v1/muhurat", json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
    })
    assert r.status_code == 200, r.text
    day = r.json()["days"][0]
    assert _hour(day["sunrise"]) == 8, day["sunrise"]
    assert _hour(day["sunset"]) == 15, day["sunset"]


def test_each_scanned_date_gets_its_own_offset_across_a_clock_change():
    """One request spanning the 2026 spring clock change in London: 28 March is
    GMT (sunrise about 05:4x), 29 March is BST (sunrise about 06:4x)."""
    r = client.post("/v1/muhurat", json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-03-28", "end_date": "2026-03-29",
    })
    assert r.status_code == 200, r.text
    before, after = r.json()["days"]
    assert _hour(before["sunrise"]) == 5, before["sunrise"]
    assert _hour(after["sunrise"]) == 6, after["sunrise"]


def test_event_place_not_birthplace_sets_the_sky():
    """A London-born person holding the event in Colombo gets Colombo's sunrise
    on Colombo's clock (about 06:1x), not London's."""
    r = client.post("/v1/muhurat", json={
        **SUMMER_BORN_LONDON, **COLOMBO_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
    })
    assert r.status_code == 200, r.text
    day = r.json()["days"][0]
    assert _hour(day["sunrise"]) == 6, day["sunrise"]
    assert _hour(day["sunset"]) == 17, day["sunset"]


def test_request_without_event_fields_is_unchanged():
    """No event fields: the birth place and the birth offset, as before."""
    r = client.post("/v1/muhurat", json={
        **SUMMER_BORN_LONDON,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
    })
    assert r.status_code == 200, r.text
    assert _hour(r.json()["days"][0]["sunrise"]) == 9


# ---------------------------------------------------------------------------
# Request validation - the event fields travel together and the zone is real
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/v1/muhurat", "/v1/muhurat/lagna-shuddhi",
])
def test_unknown_zone_is_rejected(path):
    r = client.post(path, json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT, "event_timezone": "Mars/Olympus_Mons",
        "start_date": "2026-12-15", "end_date": "2026-12-15", "step_seconds": 3600,
    })
    assert r.status_code == 422


@pytest.mark.parametrize("drop", ["event_latitude", "event_longitude", "event_timezone"])
def test_partial_event_place_is_rejected(drop):
    body = {
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
    }
    body.pop(drop)
    assert client.post("/v1/muhurat", json=body).status_code == 422


def test_family_partial_event_place_is_rejected():
    body = {
        "members": [SUMMER_BORN_LONDON, BORN_COLOMBO],
        "event_latitude": LONDON[0], "event_longitude": LONDON[1],
        "start_date": "2026-12-15", "end_date": "2026-12-15", "step_seconds": 3600,
    }
    assert client.post("/v1/muhurat/family-lagna-shuddhi", json=body).status_code == 422


# ---------------------------------------------------------------------------
# /v1/muhurat/lagna-shuddhi - the electional scan
# ---------------------------------------------------------------------------

def test_lagna_scan_scores_on_the_event_dates_offset(monkeypatch):
    """The December London scan from a July-born chart scores every instant on
    the December offset (0), at the event place."""
    calls = _spy_jd(monkeypatch)
    r = client.post("/v1/muhurat/lagna-shuddhi", json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
        "step_seconds": 900,
    })
    assert r.status_code == 200, r.text
    assert calls
    assert {off for _, _, off in calls} == {0.0}


def test_lagna_scan_reads_each_day_at_the_event_place_on_that_dates_offset(monkeypatch):
    """The day's Rahu Kala, chogadiya and muhurtas the scan scores against are
    computed at the event place, on the offset in force on that date."""
    ls = _ls()
    seen: list[tuple[float, float, float]] = []
    real = ls.compute_muhurat_for_day

    def spy(place, target_date, *a, **kw):
        seen.append((place.latitude, place.longitude, place.timezone))
        return real(place, target_date, *a, **kw)

    monkeypatch.setattr(ls, "compute_muhurat_for_day", spy)
    r = client.post("/v1/muhurat/lagna-shuddhi", json={
        **SUMMER_BORN_LONDON, **COLOMBO_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
        "step_seconds": 3600,
    })
    assert r.status_code == 200, r.text
    assert seen == [(COLOMBO[0], COLOMBO[1], 5.5)]


def test_lagna_scan_never_offers_a_wall_time_the_clock_change_breaks(monkeypatch):
    """On 29 March 2026 London clocks go from 01:00 GMT to 02:00 BST. 00:00-00:59
    is still GMT and 01:00-01:59 does not exist, so no candidate before 02:00
    may be scored, and every scored instant uses the day's own offset (+1)."""
    calls = _spy_jd(monkeypatch)
    r = client.post("/v1/muhurat/lagna-shuddhi", json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-03-29", "end_date": "2026-03-29",
        "step_seconds": 60,
    })
    assert r.status_code == 200, r.text
    assert calls, "the scan scored nothing"
    assert {off for _, _, off in calls} == {1.0}
    assert min(m for _, m, _ in calls) >= 120


def test_lagna_scan_skips_the_repeated_hour_when_clocks_go_back(monkeypatch):
    """On 25 October 2026 London's 01:00-01:59 happens twice; a time that names
    two different instants is never recommended, and the day's offset is 0."""
    calls = _spy_jd(monkeypatch)
    r = client.post("/v1/muhurat/lagna-shuddhi", json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-10-25", "end_date": "2026-10-25",
        "step_seconds": 60,
    })
    assert r.status_code == 200, r.text
    assert calls
    assert {off for _, _, off in calls} == {0.0}
    assert not [m for _, m, _ in calls if m < 120]


# ---------------------------------------------------------------------------
# /v1/muhurat/family-lagna-shuddhi - one place, one instant, every member
# ---------------------------------------------------------------------------

def test_family_members_born_in_different_zones_are_scored_at_one_instant_and_place(monkeypatch):
    calls = _spy_jd(monkeypatch)
    body = {
        "members": [SUMMER_BORN_LONDON, BORN_COLOMBO],
        **LONDON_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
        "activity_category": "generic", "step_seconds": 900,
    }
    r = client.post("/v1/muhurat/family-lagna-shuddhi", json=body)
    assert r.status_code == 200, r.text
    got = r.json()
    # Every member's instants are converted with the event date's offset.
    assert calls
    assert {off for _, _, off in calls} == {0.0}
    assert got["instant"] is not None
    per_member = got["per_member"]
    assert len(per_member) == 2
    # One absolute instant at one place: the rising sign and hora are the same
    # for every member; only the natal-Moon-relative strengths may differ.
    assert len({m["lagna_sign"] for m in per_member}) == 1
    assert len({m["hora_lord"] for m in per_member}) == 1


def test_family_scan_never_offers_a_wall_time_the_clock_change_breaks(monkeypatch):
    """The family scan, like the solo one, scores nothing before 02:00 on the
    London spring clock-change day, and every instant on the day's offset."""
    calls = _spy_jd(monkeypatch)
    r = client.post("/v1/muhurat/family-lagna-shuddhi", json={
        "members": [SUMMER_BORN_LONDON, BORN_COLOMBO],
        **LONDON_EVENT,
        "start_date": "2026-03-29", "end_date": "2026-03-29",
        "step_seconds": 60,
    })
    assert r.status_code == 200, r.text
    assert calls
    assert {off for _, _, off in calls} == {1.0}
    assert min(m for _, m, _ in calls) >= 120


def test_family_scan_keeps_each_members_own_natal_moon(monkeypatch):
    ls = _ls()
    seen: list[dict] = []
    real = ls.scan_family_lagna_shuddhi

    def spy(members, **kw):
        seen.extend(members)
        return real(members, **kw)

    monkeypatch.setattr(ls, "scan_family_lagna_shuddhi", spy)
    body = {
        "members": [SUMMER_BORN_LONDON, BORN_COLOMBO],
        **LONDON_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15", "step_seconds": 3600,
    }
    assert client.post("/v1/muhurat/family-lagna-shuddhi", json=body).status_code == 200

    from app.main import _natal_moon
    from app.schemas import FamilyMember
    own = [_natal_moon(FamilyMember(**p)) for p in (SUMMER_BORN_LONDON, BORN_COLOMBO)]
    assert [(m["birth_nakshatra"], m["birth_moon_sign"]) for m in seen] == own
    assert own[0] != own[1]
    assert {(m["lat"], m["lon"], m.get("tz_name")) for m in seen} == {
        (LONDON[0], LONDON[1], "Europe/London")
    }


# ---------------------------------------------------------------------------
# The clock itself
# ---------------------------------------------------------------------------

def _clock(tz_offset, tz_name):
    from bphs_core import event_clock
    return event_clock.make_clock(tz_offset=tz_offset, tz_name=tz_name)


def test_zone_clock_offsets_and_usable_wall_times():
    clock = _clock(0.0, "Europe/London")
    assert clock.offset_for(date(2026, 7, 1)) == 1.0
    assert clock.offset_for(date(2026, 12, 15)) == 0.0
    spring = date(2026, 3, 29)
    assert not clock.usable(spring, 30)      # 00:30 is still GMT
    assert not clock.usable(spring, 90)      # 01:30 does not exist
    assert clock.usable(spring, 600)         # 10:00 BST
    autumn = date(2026, 10, 25)
    assert not clock.usable(autumn, 90)      # 01:30 happens twice
    assert clock.usable(autumn, 600)


def test_fixed_clock_is_the_legacy_behaviour():
    clock = _clock(5.5, None)
    assert clock.offset_for(date(2026, 7, 1)) == 5.5
    assert clock.offset_for(date(2026, 12, 15)) == 5.5
    assert clock.usable(date(2026, 3, 29), 90)


def test_half_hour_and_historical_zones_resolve_from_the_tz_database():
    # Colombo was UTC+6:00 from 1996 to 2006 and is UTC+5:30 now.
    clock = _clock(0.0, "Asia/Colombo")
    assert clock.offset_for(date(2000, 6, 15)) == 6.0
    assert clock.offset_for(date(2026, 6, 15)) == 5.5
