"""Unit contract for the vaara machinery the scans use (no ephemeris needed).

* ``compute_hora_lord`` -- exhaustive over the small domain: all seven vaara
  lords x all twenty-four horas, against the classical rule typed out here
  (horas counted from the vaara's sunrise, the first belonging to the vaara
  lord, the rest descending in the Chaldean order Saturn, Jupiter, Mars, Sun,
  Venus, Mercury, Moon -- Surya Siddhanta ch. XII vv. 78-79, Burgess 1860).
* ``_place_day_windows`` -- each window is put on the date its definition puts
  it on, which its bare HH:MM cannot say.
* ``_ScanDays`` -- an instant is handed the vaara that contains it, with the
  civil-date flags of its own date.

Synthetic day payloads only; no birth data.
"""
from __future__ import annotations

import datetime as dt

import pytest

from bphs_core import lagna_shuddhi as ls
from bphs_core import muhurat

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
        muhurat.VARJYAM_HOURS_KEY: (14.0, 15.5),
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
               **{muhurat.VARJYAM_HOURS_KEY: hours})
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
               **{muhurat.VARJYAM_HOURS_KEY: (13.641, 13.641)})
    assert _placed(day, "inauspicious_periods") == [(1440, 2880, "Varjyam")]


def _stub_days(monkeypatch, eclipse_on: dt.date):
    def fake(place, d, *a, **k):
        return {
            "date": d.isoformat(), "sunrise": "06:00",
            "panchanga": {"vaara": d.strftime("%A")},
            "auspicious_muhurtas": [
                {"start": "23:30", "end": "00:30", "label": "Nishita Muhurtha"},
            ],
            "chogadiya": [], "inauspicious_periods": [],
            "is_eclipse_day": d == eclipse_on, "is_adhik_maasa": False,
            muhurat.VARJYAM_HOURS_KEY: (14.0, 15.0),
        }
    monkeypatch.setattr(ls, "compute_muhurat_for_day", fake)


def test_scan_days_hand_an_instant_its_vaara_and_its_own_dates_flags(monkeypatch):
    first = last = dt.date(2026, 12, 16)
    _stub_days(monkeypatch, eclipse_on=first)
    days = ls._ScanDays.build(None, first, last, None, None)
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
    days = ls._ScanDays.build(None, first, last, None, None)
    vaara = days.vaaras[first]
    assert vaara.views[0]["is_eclipse_day"] is False
    assert vaara.views[1]["is_eclipse_day"] is True
    with pytest.raises(LookupError):
        days.locate("2026-12-18", 600)
