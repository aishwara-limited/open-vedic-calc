"""Unit contract for the vaara machinery the scans use (no ephemeris needed).

* ``compute_hora_lord`` -- exhaustive over the small domain: all seven vaara
  lords x all twenty-four horas, against the classical rule typed out here
  (horas counted from the vaara's sunrise, the first belonging to the vaara
  lord, the rest descending in the Chaldean order Saturn, Jupiter, Mars, Sun,
  Venus, Mercury, Moon -- Surya Siddhanta ch. XII vv. 78-79, Burgess 1860).
* ``_place_day_windows`` -- each window is put on the date its definition puts
  it on, which its bare HH:MM cannot say.
* ``_ScanDays`` -- an instant is handed the vaara that contains it, with the
  civil-date flags of its own date (the eclipse AND the Adhika Maasa flag); a
  vaara ends at the NEXT date's sunrise, so when sunrise moves from one day to
  the next no instant is scored twice and none is dropped; a day is read on
  the offset of its own date, and the scan's minute axis is absolute time, so
  a vaara that spans a clock change keeps its windows and its count from
  sunrise on its own clock; and days are computed lazily, as the scan reaches
  the vaaras that need them, never all up front.

Synthetic day payloads only; no birth data.
"""
from __future__ import annotations

import datetime as dt

import pytest

from bphs_core import event_clock, muhurat
from bphs_core import lagna_shuddhi as ls

_CHALDEAN = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]
# 2026-12-06 is a Sunday; the next six dates run Monday .. Saturday.
_WEEK = [(dt.date(2026, 12, 6) + dt.timedelta(days=i)) for i in range(7)]
_LORD = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]


@pytest.mark.parametrize("w", range(7))
@pytest.mark.parametrize("n", range(24))
def test_every_hora_of_every_vaara(w, n):
    sunrise = "06:17"
    minute = 6 * 60 + 17 + 60 * n + 30
    want = _CHALDEAN[(_CHALDEAN.index(_LORD[w]) + n) % 7]
    assert ls.compute_hora_lord(_WEEK[w].isoformat(), minute, sunrise) == want


def test_the_24th_hora_runs_on_to_the_next_sunrise():
    # Sunday: the 24th hora (n = 23) is Mercury's; a minute past 24 h after
    # sunrise is still before a later next sunrise and stays in it.
    day = _WEEK[0].isoformat()
    assert ls.compute_hora_lord(day, 377 + 23 * 60, "06:17") == "Mercury"
    assert ls.compute_hora_lord(day, 377 + 24 * 60 + 1, "06:17") == "Mercury"


def test_a_minute_before_the_vaara_sunrise_is_refused():
    with pytest.raises(ValueError, match="previous vaara"):
        ls.compute_hora_lord(_WEEK[0].isoformat(), 300, "06:17")


def _day(**over) -> dict:
    d = {
        "date": "2026-12-16", "sunrise": "06:17",
        "auspicious_muhurtas": [], "chogadiya": [], "inauspicious_periods": [],
        muhurat.VARJYAM_HOURS_KEY: ((14.0, 15.5),),
    }
    d.update(over)
    return d


def _placed(day, key):
    return [(s, e, w["label"]) for s, e, w in ls._place_day_windows(day, 1440)[key]]


def test_brahma_muhurta_precedes_its_own_sunrise():
    day = _day(auspicious_muhurtas=[
        {"start": "04:38", "end": "05:28", "label": "Brahma Muhurtha"},
    ])
    assert _placed(day, "auspicious_muhurtas") == [
        (1440 + 278, 1440 + 328, "Brahma Muhurtha"),
    ]
    # A sunrise near 01:00 puts the Brahma muhurta before midnight.
    early = _day(sunrise="01:10", auspicious_muhurtas=[
        {"start": "23:30", "end": "00:20", "label": "Brahma Muhurtha"},
    ])
    assert _placed(early, "auspicious_muhurtas") == [
        (1440 - 30, 1440 + 20, "Brahma Muhurtha"),
    ]


def test_night_windows_after_midnight_belong_to_the_next_date():
    day = _day(
        chogadiya=[
            {"start": "06:17", "end": "07:44", "label": "Labh (Auspicious)"},
            {"start": "22:33", "end": "00:06", "label": "Chara (Auspicious)"},
            {"start": "00:06", "end": "01:39", "label": "Rog (Inauspicious)"},
            {"start": "04:45", "end": "06:18", "label": "Udveg (Inauspicious)"},
        ],
        auspicious_muhurtas=[
            {"start": "23:41", "end": "00:31", "label": "Nishita Muhurtha"},
            {"start": "01:05", "end": "01:55", "label": "Nishita Muhurtha"},
        ],
    )
    assert _placed(day, "chogadiya") == [
        (1440 + 377, 1440 + 464, "Labh (Auspicious)"),
        (1440 + 1353, 1440 + 1446, "Chara (Auspicious)"),
        (1440 + 1446, 1440 + 1539, "Rog (Inauspicious)"),
        (1440 + 1725, 1440 + 1818, "Udveg (Inauspicious)"),
    ]
    assert _placed(day, "auspicious_muhurtas") == [
        (1440 + 1421, 1440 + 1471, "Nishita Muhurtha"),
        (1440 + 1505, 1440 + 1555, "Nishita Muhurtha"),
    ]


@pytest.mark.parametrize("hours, start", [
    ((-3.2, -1.5), 1440 - 192),          # the previous evening, 20:48
    ((14.0, 15.5), 1440 + 840),          # the day itself
    ((25.25, 26.9), 1440 + 1440 + 75),   # after the coming midnight, 01:15
    ((23.99999, 25.6), 1440 + 1440),     # renders 00:00, belongs to next date
])
def test_varjyam_is_placed_from_its_float_hours(hours, start):
    s = muhurat.float_hours_to_hhmm(hours[0])
    e = muhurat.float_hours_to_hhmm(hours[1])
    day = _day(inauspicious_periods=[{"start": s, "end": e, "label": "Varjyam"}],
               **{muhurat.VARJYAM_HOURS_KEY: (hours,)})
    [(got_s, got_e, _)] = _placed(day, "inauspicious_periods")
    assert got_s == start
    assert got_e - got_s == (ls._hhmm_to_mins(e) - ls._hhmm_to_mins(s)) % 1440


def test_a_varjyam_without_float_hours_cannot_be_placed():
    day = _day(inauspicious_periods=[{"start": "20:48", "end": "22:30", "label": "Varjyam"}])
    del day[muhurat.VARJYAM_HOURS_KEY]
    with pytest.raises(ValueError, match="Varjyam"):
        ls._place_day_windows(day, 0)


def test_a_zero_width_window_keeps_its_whole_day_reading():
    # The engine has always read start == end as the whole clock; for the
    # surgery Varjyam veto that is the fail-closed reading, and it is kept.
    day = _day(inauspicious_periods=[{"start": "13:38", "end": "13:38", "label": "Varjyam"}],
               **{muhurat.VARJYAM_HOURS_KEY: ((13.641, 13.641),)})
    assert _placed(day, "inauspicious_periods") == [(1440, 2880, "Varjyam")]


# A public city's coordinates (Colombo); the stubbed days ignore them, the
# scorer's real ephemeris reads them.
_LAT, _LON = 6.9271, 79.8612


def _fixed(offset: float = 5.5) -> event_clock.EventClock:
    return event_clock.FixedOffsetClock(offset)


def _scan_days(first, last, clock=None) -> ls._ScanDays:
    return ls._ScanDays("t", _LAT, _LON, clock or _fixed(), first, last, None, None)


def _rise(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _stub_days(monkeypatch, eclipse_on: dt.date | None = None,
               adhik_on: dt.date | None = None, sunrise=lambda d: 360,
               cover_all: bool = False) -> list[dt.date]:
    """Replace compute_muhurat_for_day; returns the dates it was asked for.

    *sunrise* maps a date to its sunrise in minutes after local midnight.
    *cover_all* serves two favourable chogadiya windows that together cover
    the whole vaara (sunrise to 18:00, 18:00 to the next sunrise), so every
    minute is a candidate; otherwise one Nishita window 23:30-00:30.
    """
    computed: list[dt.date] = []

    def fake(place, d, *a, **k):
        computed.append(d)
        nxt = d + dt.timedelta(days=1)
        if cover_all:
            choga = [
                {"start": _rise(sunrise(d)), "end": "18:00",
                 "label": "Amrit (Highly Auspicious)"},
                {"start": "18:00", "end": _rise(sunrise(nxt)),
                 "label": "Labh (Auspicious)"},
            ]
            nishita = []
        else:
            choga = []
            nishita = [{"start": "23:30", "end": "00:30", "label": "Nishita Muhurtha"}]
        return {
            "date": d.isoformat(), "sunrise": _rise(sunrise(d)),
            "panchanga": {"vaara": d.strftime("%A")},
            "auspicious_muhurtas": nishita,
            "chogadiya": choga, "inauspicious_periods": [],
            "is_eclipse_day": d == eclipse_on, "is_adhik_maasa": d == adhik_on,
            muhurat.VARJYAM_HOURS_KEY: ((14.0, 15.0),),
        }
    monkeypatch.setattr(ls, "compute_muhurat_for_day", fake)
    return computed


def test_scan_days_hand_an_instant_its_vaara_and_its_own_dates_flags(monkeypatch):
    first = last = dt.date(2026, 12, 16)
    _stub_days(monkeypatch, eclipse_on=first)
    days = _scan_days(first, last)
    # 00:15 on the 16th: Nishita of the 15th's vaara, eclipse flag of the 16th.
    view, m = days.locate("2026-12-16", 15)
    assert view["date"] == "2026-12-15" and m == 1440 + 15
    assert view["panchanga"]["vaara"] == "Tuesday"
    assert view["is_eclipse_day"] is True
    # 23:45 on the 16th: its own vaara, before midnight.
    view, m = days.locate("2026-12-16", 23 * 60 + 45)
    assert view["date"] == "2026-12-16" and m == 23 * 60 + 45
    assert view["is_eclipse_day"] is True
    # The candidates are the Nishita minutes on the 16th only: the end of the
    # 15th's Nishita after midnight and the start of the 16th's before it.
    got = days.candidates(first, last, 15)
    assert got == {("2026-12-16", 0), ("2026-12-16", 15),
                   ("2026-12-16", 1410), ("2026-12-16", 1425)}


def test_scan_days_flag_after_midnight_follows_the_next_date(monkeypatch):
    first = last = dt.date(2026, 12, 16)
    _stub_days(monkeypatch, eclipse_on=dt.date(2026, 12, 17))
    days = _scan_days(first, last)
    vaara = days.vaara(first)
    assert vaara.views[0]["is_eclipse_day"] is False
    assert vaara.views[1]["is_eclipse_day"] is True
    with pytest.raises(LookupError):
        days.locate("2026-12-18", 600)


def test_scan_days_adhik_maasa_after_midnight_follows_the_next_date(monkeypatch):
    """An intercalary month that the day panchanga reports from the 17th: the
    instants of the 17th before its sunrise lie in the 16th's vaara, and still
    carry the 17th's Adhika Maasa flag -- the marriage veto reads it there."""
    first, last = dt.date(2026, 5, 16), dt.date(2026, 5, 17)
    _stub_days(monkeypatch, adhik_on=last)
    days = _scan_days(first, last)
    vaara = days.vaara(first)
    assert vaara.views[0]["is_adhik_maasa"] is False
    assert vaara.views[1]["is_adhik_maasa"] is True
    view, m = days.locate("2026-05-17", 15)
    assert view["date"] == "2026-05-16" and m == 1440 + 15
    assert view["is_adhik_maasa"] is True
    view, _ = days.locate("2026-05-16", 23 * 60 + 45)
    assert view["is_adhik_maasa"] is False
    # The marriage veto reads it: the same instant, scored against the view
    # before midnight (the 16th's flag), is not excluded.
    after, before = vaara.views[1], vaara.views[0]
    jd = 2461177.5
    assert ls._score_instant(jd, "Aries", "Mars", after, 1440 + 15, "marriage")[1][
        "hard_excluded"] is True
    assert ls._score_instant(jd, "Aries", "Mars", before, 1440 + 15, "marriage")[1][
        "hard_excluded"] is False


# Sunrise on the 9th, 10th, 11th and 12th of a fictitious March: moving later
# by 20 minutes a day, and moving earlier.
_RISES = [(360, 380, 400, 420), (420, 400, 380, 360)]


@pytest.mark.parametrize("rises", _RISES)
def test_a_vaara_ends_at_the_next_dates_sunrise(monkeypatch, rises):
    """Vaara D runs to D+1's sunrise, not to D's own sunrise a day later."""
    d0 = dt.date(2027, 3, 10)
    _stub_days(monkeypatch, sunrise=lambda d: rises[(d - d0).days + 1])
    first = last = d0
    days = _scan_days(first, last)
    prev, today = days.vaara(d0 - dt.timedelta(days=1)), days.vaara(d0)
    assert prev.next_sunrise == today.sunrise
    assert today.sunrise - prev.sunrise == 1440 + rises[1] - rises[0]
    assert today.next_sunrise - today.sunrise == 1440 + rises[2] - rises[1]
    # Either side of the 10th's sunrise (rises[1]), a minute apart.
    view, m = days.locate(d0.isoformat(), rises[1] - 1)
    assert view["date"] == "2027-03-09" and m == 1440 + rises[1] - 1
    view, m = days.locate(d0.isoformat(), rises[1])
    assert view["date"] == "2027-03-10" and m == rises[1]


@pytest.mark.parametrize("rises", _RISES)
def test_the_scan_scores_every_instant_once_when_sunrise_moves(monkeypatch, rises):
    """Every 10-minute mark of the requested date is scored exactly once, in
    the vaara that holds it, however far sunrise moves from one day to the
    next. Ending a vaara at its own sunrise a day later scores the minutes
    between the two sunrises twice (sunrise moving earlier) or never (later)."""
    d0 = dt.date(2027, 3, 10)
    _stub_days(monkeypatch, sunrise=lambda d: rises[(d - d0).days + 1],
               cover_all=True)
    scored: list[tuple[str, int, str]] = []
    real_score = ls._score_instant

    def spy(jd, lagna_sign, lagna_lord, day_data, time_mins, *a, **k):
        scored.append((day_data["date"], time_mins))
        return real_score(jd, lagna_sign, lagna_lord, day_data, time_mins, *a, **k)

    jds: list[tuple[str, int]] = []
    real_jd = ls._jd_for_local

    def jd_spy(date_str, time_mins, tz_offset):
        jds.append((date_str, time_mins))
        return real_jd(date_str, time_mins, tz_offset)

    monkeypatch.setattr(ls, "_score_instant", spy)
    monkeypatch.setattr(ls, "_jd_for_local", jd_spy)
    ls.scan_lagna_shuddhi(_LAT, _LON, 5.5, None, None, d0.isoformat(),
                          d0.isoformat(), "generic", step_seconds=600)
    assert jds == [(d0.isoformat(), m) for m in range(0, 1440, 10)]
    for (civil, minute), (vaara, vaara_mins) in zip(jds, scored):
        if minute < rises[1]:
            assert (vaara, vaara_mins) == ("2027-03-09", 1440 + minute)
        else:
            assert (vaara, vaara_mins) == ("2027-03-10", minute)


def test_the_solo_scan_computes_its_days_as_it_reaches_them(monkeypatch):
    """A 12-day scan computes the days of a vaara when it reaches that vaara:
    by the first scored instant (00:00 on the 1st) only the four days the
    vaaras either side of it read exist (30 November to 3 December), and no
    instant is scored with a day computed more than two days past it.
    Computing every day up front starves a concurrent chart request of the
    ephemeris lock (tests/test_ephemeris_lock.py)."""
    first, last = dt.date(2026, 12, 1), dt.date(2026, 12, 12)
    computed = _stub_days(monkeypatch, cover_all=True)
    seen: list[tuple[int, dt.date]] = []
    real_score = ls._score_instant
    real_jd = ls._jd_for_local
    civil: list[dt.date] = []

    def jd_spy(date_str, time_mins, tz_offset):
        civil.append(dt.date.fromisoformat(date_str))
        return real_jd(date_str, time_mins, tz_offset)

    def spy(*a, **k):
        seen.append((len(computed), max(computed)))
        return real_score(*a, **k)

    monkeypatch.setattr(ls, "_jd_for_local", jd_spy)
    monkeypatch.setattr(ls, "_score_instant", spy)
    ls.scan_lagna_shuddhi(_LAT, _LON, 5.5, None, None, first.isoformat(),
                          last.isoformat(), "generic", step_seconds=6 * 3600)
    assert len(seen) == 12 * 4
    assert seen[0] == (4, first + dt.timedelta(days=2))
    for (n, latest), day in zip(seen, civil):
        assert latest <= day + dt.timedelta(days=2), (day, latest)
    assert sorted(computed) == [
        first + dt.timedelta(days=k) for k in range(-1, 13)
    ]


class _SpringForward:
    """A clock that moves from UTC+0 to UTC+1 at 01:00 on *day*: earlier
    dates are read on +0, *day* and later on +1, and *day*'s wall times
    before 02:00 are not usable (the same rule as event_clock.ZoneClock)."""

    def __init__(self, day: dt.date):
        self.day = day

    def offset_for(self, d: dt.date) -> float:
        return 1.0 if d >= self.day else 0.0

    def usable(self, d: dt.date, minute: int) -> bool:
        return not (d == self.day and minute < 120)


def test_a_vaara_across_a_clock_change_is_read_on_its_own_dates_clock(monkeypatch):
    """Clocks go forward an hour in the night after the 28th. The 28th is read
    on +0 and the 29th and 30th on +1. The 29th's sunrise is 06:00 on +1,
    05:00 on the 28th's clock, so that vaara lasts 23 hours of its own clock;
    03:00 on the 29th (+1) is 02:00 on the 28th's clock, 26:00 on its extended
    clock. The 28th's night window 01:30-03:30 (+0) is 02:30-04:30 on the
    29th's clock, and is offered there; read on a wall-clock axis it would be
    offered at 01:30-03:30 and its first half-hour dropped as pre-change."""
    change = dt.date(2026, 3, 29)
    computed: list[tuple[dt.date, float]] = []

    def fake(place, d, *a, **k):
        computed.append((d, place.timezone))
        night = [{"start": "01:30", "end": "03:30", "label": "Labh (Auspicious)"}]
        return {
            "date": d.isoformat(), "sunrise": "06:00",
            "panchanga": {"vaara": d.strftime("%A")},
            "auspicious_muhurtas": [], "inauspicious_periods": [],
            "chogadiya": night if d == change - dt.timedelta(days=1) else [],
            "is_eclipse_day": False, "is_adhik_maasa": False,
            muhurat.VARJYAM_HOURS_KEY: ((14.0, 15.0),),
        }

    monkeypatch.setattr(ls, "compute_muhurat_for_day", fake)
    days = _scan_days(change, change, clock=_SpringForward(change))
    prev = days.vaara(change - dt.timedelta(days=1))
    assert prev.next_sunrise - prev.sunrise == 23 * 60
    view, m = days.locate(change.isoformat(), 180)
    assert view["date"] == "2026-03-28" and m == 1440 + 120
    assert sorted(computed) == [
        (dt.date(2026, 3, 28), 0.0), (dt.date(2026, 3, 29), 1.0),
        (dt.date(2026, 3, 30), 1.0),
    ]
    got = days.candidates(change, change, 30)
    assert got == {("2026-03-29", m) for m in (150, 180, 210, 240)}
