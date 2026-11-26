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
* the UTC offset resolved for EACH scanned date from the tz database, with the
  zone's continuing rule applied after the last transition the database lists
  (summer and winter time after 2037, in both hemispheres) and its full history
  before 1902;
* a day whose local noon the zone skipped or repeated refused as a structured
  ``muhurat_limb_error`` naming the ``utc_offset`` limb, never a bare 500;
* the event coordinates held to the globe and to finite values on every route;
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

import json
import time as time_mod
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


def _spy_days(monkeypatch) -> list[tuple[str, float, float, float]]:
    ls = _ls()
    seen: list[tuple[str, float, float, float]] = []
    real = ls.compute_muhurat_for_day

    def spy(place, target_date, *a, **kw):
        seen.append((target_date.isoformat(), place.latitude, place.longitude,
                     place.timezone))
        return real(place, target_date, *a, **kw)

    monkeypatch.setattr(ls, "compute_muhurat_for_day", spy)
    return seen


def test_lagna_scan_reads_each_day_at_the_event_place_on_that_dates_offset(monkeypatch):
    """The day's Rahu Kala, chogadiya and muhurtas the scan scores against are
    computed at the event place, on the offset in force on that date. The scan
    reads one neighbouring day beyond each end of the request (the vaara that
    holds the requested date's pre-dawn hours begins the day before, and the
    requested date's night runs into the day after)."""
    seen = _spy_days(monkeypatch)
    r = client.post("/v1/muhurat/lagna-shuddhi", json={
        **SUMMER_BORN_LONDON, **COLOMBO_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
        "step_seconds": 3600,
    })
    assert r.status_code == 200, r.text
    assert sorted(seen) == [
        (day, COLOMBO[0], COLOMBO[1], 5.5)
        for day in ("2026-12-14", "2026-12-15", "2026-12-16")
    ]


def test_lagna_scan_reads_the_days_either_side_of_a_clock_change_on_their_own_offsets(
    monkeypatch,
):
    """Scanning 29 March 2026 in London reads the 28th (the vaara its pre-dawn
    hours lie in) on GMT, and the 29th and 30th on BST."""
    seen = _spy_days(monkeypatch)
    r = client.post("/v1/muhurat/lagna-shuddhi", json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-03-29", "end_date": "2026-03-29",
        "step_seconds": 3600,
    })
    assert r.status_code == 200, r.text
    assert sorted(seen) == [
        ("2026-03-28", LONDON[0], LONDON[1], 0.0),
        ("2026-03-29", LONDON[0], LONDON[1], 1.0),
        ("2026-03-30", LONDON[0], LONDON[1], 1.0),
    ]


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


def test_family_scan_offers_only_wall_times_every_members_clock_stands_behind(monkeypatch):
    """Members on different clocks (the module accepts a zone per member):
    on 29 March 2026 London's 00:00-01:59 is unusable, New York's is not. A
    New York candidate at 00:30 is still never scored, for any member, because
    London's clock cannot stand behind it."""
    calls = _spy_jd(monkeypatch)
    members = [
        {"name": "a", "lat": LONDON[0], "lon": LONDON[1], "tz_offset": 0.0,
         "tz_name": "Europe/London", "birth_nakshatra": None, "birth_moon_sign": None},
        {"name": "b", "lat": 40.7128, "lon": -74.0060, "tz_offset": -5.0,
         "tz_name": "America/New_York", "birth_nakshatra": None, "birth_moon_sign": None},
    ]
    _ls().scan_family_lagna_shuddhi(
        members, "2026-03-29", "2026-03-29", activity="generic", step_seconds=300,
    )
    assert calls
    assert min(m for _, m, _ in calls) >= 120
    assert {off for _, _, off in calls} == {1.0, -4.0}


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


def test_zone_names_match_without_case_and_take_the_databases_aliases():
    from bphs_core import event_clock
    for name in ("Europe/London", "europe/london", "GB", "US/Eastern"):
        assert event_clock.is_known_zone(name), name
    assert _clock(0.0, "europe/london").offset_for(date(2026, 7, 1)) == 1.0
    # Listed by the tz database but the zone of no place ("local time
    # unknown", offset 0), so it is refused like any other non-zone.
    for name in ("Factory", "factory", "Mars/Olympus_Mons", "../Europe/London", "Europe"):
        assert not event_clock.is_known_zone(name), name


def test_a_wall_time_repeated_after_noon_is_not_usable():
    # Egypt ends summer time at 24:00 on the last Thursday of October, so on
    # 2026-10-29 the hour from 23:00 runs twice - AFTER the noon whose offset
    # (+3) the day is read on. Its earlier reading carries that same offset, so
    # only the one-instant check keeps it out.
    clock = _clock(0.0, "Africa/Cairo")
    thursday = date(2026, 10, 29)
    assert clock.offset_for(thursday) == 3.0
    assert clock.usable(thursday, 22 * 60 + 30)
    assert not clock.usable(thursday, 23 * 60 + 30)


def test_the_hosts_zoneinfo_directory_is_never_read(tmp_path):
    # A host directory holding a wrong Europe/London (Tokyo's rules) must not
    # change the answer: zones come from the locked tzdata package only.
    import zoneinfo
    from importlib import resources

    from bphs_core import event_clock
    tokyo = resources.files("tzdata.zoneinfo.Asia").joinpath("Tokyo").read_bytes()
    (tmp_path / "Europe").mkdir()
    (tmp_path / "Europe" / "London").write_bytes(tokyo)
    event_clock._load_zone.cache_clear()
    zoneinfo.ZoneInfo.clear_cache()
    zoneinfo.reset_tzpath(to=[str(tmp_path)])
    try:
        assert _clock(0.0, "Europe/London").offset_for(date(2026, 7, 1)) == 1.0
    finally:
        zoneinfo.reset_tzpath()
        zoneinfo.ZoneInfo.clear_cache()
        event_clock._load_zone.cache_clear()


def test_zone_clock_refuses_a_name_that_is_no_zone():
    # Request validation refuses these first; the clock refuses them too,
    # without echoing the name.
    from bphs_core import event_clock
    with pytest.raises(ValueError, match="^not an IANA time zone name$"):
        event_clock.ZoneClock("Mars/Olympus_Mons")


@pytest.mark.parametrize("name", ["Factory", "../Europe/London"])
def test_a_name_that_is_no_places_zone_is_rejected_by_the_route(name):
    r = client.post("/v1/muhurat", json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT, "event_timezone": name,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
    })
    assert r.status_code == 422, r.text
    assert any(err["loc"][-1] == "event_timezone" for err in r.json()["detail"]), r.text


# ---------------------------------------------------------------------------
# Every date a scan accepts is on its own zone's clock - not only 1902-2037
# ---------------------------------------------------------------------------
#
# A reader that holds only a fixed table of transitions answers with the last
# entry's offset for every date after it (a northern zone stuck on standard
# time from 2038, a southern one stuck on summer time) and with the first
# entry's for every date before it. A scan may be requested for any date from
# 1800-01-02 to 2399-12-01, so both ends are pinned, in both hemispheres.

SYDNEY = (-33.8688, 151.2093)

SYDNEY_EVENT = {
    "event_latitude": SYDNEY[0],
    "event_longitude": SYDNEY[1],
    "event_timezone": "Australia/Sydney",
}


@pytest.mark.parametrize("zone, day, offset", [
    # North: summer time in July, standard time in December.
    ("Europe/London", date(2038, 7, 1), 1.0),
    ("Europe/London", date(2038, 12, 15), 0.0),
    ("America/New_York", date(2045, 7, 1), -4.0),
    ("America/New_York", date(2045, 12, 15), -5.0),
    # South: the other way round.
    ("Australia/Sydney", date(2038, 7, 1), 10.0),
    ("Australia/Sydney", date(2038, 12, 15), 11.0),
    # The last year a scan may be requested for.
    ("Europe/London", date(2399, 7, 1), 1.0),
    ("Australia/Sydney", date(2399, 7, 1), 10.0),
])
def test_offsets_after_2037_follow_the_zones_continuing_rule(zone, day, offset):
    assert _clock(0.0, zone).offset_for(day) == offset


@pytest.mark.parametrize("zone, day, offset", [
    ("Europe/London", date(1890, 6, 15), 0.0),       # GMT since 1847-12-01
    ("America/New_York", date(1890, 6, 15), -5.0),   # EST since 1883-11-18
])
def test_offsets_before_1902_follow_the_zones_history(zone, day, offset):
    assert _clock(0.0, zone).offset_for(day) == offset


@pytest.mark.parametrize("event, day, sunrise_hour, sunset_hour", [
    (LONDON_EVENT, "2038-07-01", 4, 21),     # BST
    (LONDON_EVENT, "2038-12-15", 8, 15),     # GMT
    (SYDNEY_EVENT, "2038-07-01", 7, 16),     # AEST
    (SYDNEY_EVENT, "2038-12-15", 5, 19),     # AEDT
])
def test_day_panels_after_2037_are_on_that_dates_clock(event, day, sunrise_hour, sunset_hour):
    r = client.post("/v1/muhurat", json={
        **SUMMER_BORN_LONDON, **event, "start_date": day, "end_date": day,
    })
    assert r.status_code == 200, r.text
    panel = r.json()["days"][0]
    assert _hour(panel["sunrise"]) == sunrise_hour, panel["sunrise"]
    assert _hour(panel["sunset"]) == sunset_hour, panel["sunset"]


def test_lagna_scan_after_2037_scores_on_northern_summer_time(monkeypatch):
    calls = _spy_jd(monkeypatch)
    r = client.post("/v1/muhurat/lagna-shuddhi", json={
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2038-07-01", "end_date": "2038-07-01", "step_seconds": 3600,
    })
    assert r.status_code == 200, r.text
    assert calls, "the scan scored nothing"
    assert {off for _, _, off in calls} == {1.0}


def test_family_scan_after_2037_scores_on_southern_winter_time(monkeypatch):
    calls = _spy_jd(monkeypatch)
    r = client.post("/v1/muhurat/family-lagna-shuddhi", json={
        "members": [SUMMER_BORN_LONDON, BORN_COLOMBO], **SYDNEY_EVENT,
        "start_date": "2038-07-01", "end_date": "2038-07-01", "step_seconds": 3600,
    })
    assert r.status_code == 200, r.text
    assert calls, "the scan scored nothing"
    assert {off for _, _, off in calls} == {10.0}


# ---------------------------------------------------------------------------
# A day whose local noon names no single instant is a structured 422
# ---------------------------------------------------------------------------
#
# The day's offset is the one at local noon. Pacific/Apia skipped the whole of
# 2011-12-30 (from UTC-10 straight to UTC+14), so that day has no noon; New
# York left local mean time for EST at 12:03:58 on 1883-11-18, so its noon ran
# twice. Neither may be guessed, and neither may surface as an opaque 500: this
# repo's declared mode for a day it cannot compute is MuhurtaLimbError, served
# as a 422 that names the limb.

APIA = (-13.8333, -171.7667)

APIA_EVENT = {
    "event_latitude": APIA[0],
    "event_longitude": APIA[1],
    "event_timezone": "Pacific/Apia",
}

_SKIPPED_DAY = "2011-12-30"

_SKIPPED_NOON_REQUESTS = [
    ("/v1/muhurat", {
        **SUMMER_BORN_LONDON, **APIA_EVENT,
        "start_date": _SKIPPED_DAY, "end_date": _SKIPPED_DAY,
    }),
    ("/v1/muhurat/lagna-shuddhi", {
        **SUMMER_BORN_LONDON, **APIA_EVENT,
        "start_date": _SKIPPED_DAY, "end_date": _SKIPPED_DAY, "step_seconds": 3600,
    }),
    ("/v1/muhurat/family-lagna-shuddhi", {
        "members": [SUMMER_BORN_LONDON, BORN_COLOMBO], **APIA_EVENT,
        "start_date": _SKIPPED_DAY, "end_date": _SKIPPED_DAY, "step_seconds": 3600,
    }),
]


def test_zone_clock_refuses_a_noon_the_zone_skipped():
    from bphs_core.muhurat import MuhurtaLimbError
    clock = _clock(0.0, "Pacific/Apia")
    assert clock.offset_for(date(2011, 12, 29)) == -10.0
    assert clock.offset_for(date(2011, 12, 31)) == 14.0
    with pytest.raises(MuhurtaLimbError) as exc:
        clock.offset_for(date(2011, 12, 30))
    assert exc.value.limb == "utc_offset"
    assert exc.value.target_date == date(2011, 12, 30)


def test_zone_clock_refuses_a_noon_the_zone_repeated():
    from bphs_core.muhurat import MuhurtaLimbError
    clock = _clock(0.0, "America/New_York")
    assert clock.offset_for(date(1883, 11, 19)) == -5.0
    with pytest.raises(MuhurtaLimbError) as exc:
        clock.offset_for(date(1883, 11, 18))
    assert exc.value.limb == "utc_offset"
    assert exc.value.target_date == date(1883, 11, 18)


@pytest.mark.parametrize("path, body", _SKIPPED_NOON_REQUESTS)
def test_a_skipped_noon_is_a_structured_422_on_every_route(path, body):
    r = client.post(path, json=body)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "muhurat_limb_error", detail
    assert detail["limb"] == "utc_offset", detail
    assert detail["target_date"] == _SKIPPED_DAY, detail


@pytest.mark.parametrize("path, body", _SKIPPED_NOON_REQUESTS[1:])
def test_a_scan_beside_a_skipped_noon_is_refused_naming_that_date(path, body):
    """A scan of 2011-12-31 at Apia reads the day before it -- the vaara the
    31st's pre-dawn hours lie in begins then -- and that day has no noon in
    the zone, so no offset to read it on. The scan is refused as a scan of
    that day itself is, naming it, never scored on a guessed offset."""
    r = client.post(path, json={**body, "start_date": "2011-12-31",
                                "end_date": "2011-12-31"})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "muhurat_limb_error", detail
    assert detail["limb"] == "utc_offset", detail
    assert detail["target_date"] == _SKIPPED_DAY, detail


@pytest.mark.parametrize("kind, body", [
    ("lagna-shuddhi", _SKIPPED_NOON_REQUESTS[1][1]),
    ("family-lagna-shuddhi", _SKIPPED_NOON_REQUESTS[2][1]),
])
def test_a_skipped_noon_ends_an_async_job_naming_the_limb(kind, body):
    submit = client.post(f"/v1/muhurat/{kind}/async", json=body)
    assert submit.status_code == 202, submit.text
    url = f"/v1/muhurat/{kind}/jobs/{submit.json()['job_id']}"
    deadline = time_mod.time() + 30
    job = client.get(url).json()
    while job["status"] not in ("done", "error") and time_mod.time() < deadline:
        time_mod.sleep(0.05)
        job = client.get(url).json()
    assert job["status"] == "error", job
    assert "'utc_offset'" in job["error"], job
    assert _SKIPPED_DAY in job["error"], job


# ---------------------------------------------------------------------------
# The event coordinates are held to the globe and to finite values
# ---------------------------------------------------------------------------
#
# The same bounds tests/test_coord_bounds.py pins for the person's coordinates,
# pinned here for the event's on all three request models. Each rejection must
# come from request validation naming the field - a 422 from anywhere else (a
# limb that could not be computed for an impossible place) is not the guard
# holding - and must say which check refused it: a non-finite value is refused
# as not finite (`finite_number`), not merely as out of range, which the range
# alone would also do.

_EVENT_BOUNDS_REQUESTS = [
    ("/v1/muhurat", {
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15",
    }),
    ("/v1/muhurat/lagna-shuddhi", {
        **SUMMER_BORN_LONDON, **LONDON_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15", "step_seconds": 3600,
    }),
    ("/v1/muhurat/family-lagna-shuddhi", {
        "members": [SUMMER_BORN_LONDON, BORN_COLOMBO], **LONDON_EVENT,
        "start_date": "2026-12-15", "end_date": "2026-12-15", "step_seconds": 3600,
    }),
]

_BAD_EVENT_COORDINATES = [
    (field, literal, check)
    for field, limit in (("event_latitude", 90), ("event_longitude", 180))
    for literal, check in (
        ("NaN", "finite_number"),
        ("Infinity", "finite_number"),
        ("-Infinity", "finite_number"),
        (f"{limit + 0.5}", "less_than_equal"),
        (f"{-limit - 0.5}", "greater_than_equal"),
    )
]


@pytest.mark.parametrize("path, body", _EVENT_BOUNDS_REQUESTS)
@pytest.mark.parametrize("field, literal, check", _BAD_EVENT_COORDINATES)
def test_event_coordinates_outside_the_globe_or_not_finite_are_rejected(
    path, body, field, literal, check
):
    # A raw body, because NaN and Infinity are not JSON a client's json= sends.
    raw = json.dumps({**body, field: "__VALUE__"}).replace('"__VALUE__"', literal)
    r = client.post(path, content=raw.encode(), headers={"Content-Type": "application/json"})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, list), detail
    assert any(err["loc"][-1] == field and err["type"] == check for err in detail), detail
