"""The muhurat timings that are solved from the ephemeris rather than read from
the library: Varjyam (tyajya), Amrita Gadiya, both Mula Varjyam windows, the
four panchanga end times, Tuesday's night Durmuhurtam, and Abhijit on a
Wednesday.

THE RULES THESE TESTS STATE
---------------------------
* Varjyam and Amrita Gadiya are slices of the NAKSHATRA, not of the day: the
  star is taken as 60 ghatis long (its actual length, from the Moon's entry into
  it to its exit), the tyajya period begins after a fixed number of those
  ghatis and lasts four. The starting ghatis below are typed from the published
  Nakshatra Thyajyam table (Drik Panchang, "Nakshatra Thyajyam", which lists
  each window as ghatis N+1 to N+4, so the window starts after N); for Mula,
  which that table gives a single window (after 56 ghatis), both windows of
  the table the engine has always used are typed (20 and 56). The Amrita
  starting ghatis are typed from the table in Karanam Ramakumar, "Panchangam
  Calculations". Both tables are typed here, not imported, so a change to the
  engine's copy reds the exhaustive table tests.
* A tithi ends when the Moon-Sun elongation reaches the next multiple of 12
  degrees, a karana at the next multiple of 6, a yoga when the sidereal
  Sun+Moon sum reaches the next multiple of 13 deg 20 min, and a nakshatra when
  the Moon's sidereal longitude does (Surya Siddhanta II.64-69, Burgess 1860).
* The night is divided into 15 muhurtas from sunset to the next sunrise, so
  the 7th night muhurta -- Tuesday's second Durmuhurtam -- is one fifteenth of
  the NIGHT long.
* Abhijit (the 8th day muhurta) is not served as auspicious on a Wednesday,
  whose Durmuhurtam is that same 8th day muhurta.

THE INDEPENDENT REFERENCE
-------------------------
Every expected instant is computed here from ``swe.calc_ut`` directly (sidereal
Lahiri, geometric positions -- the convention the engine serves) and from
``swe.rise_trans`` for the day frame, by a bisection written in this file. None
of it goes through ``bphs_core``'s panchanga helpers or the library's panchanga
functions. The places are public city coordinates; no birth data.
"""
from __future__ import annotations

import datetime as dt
import functools

import pytest
import swisseph as swe

from bphs_core import lagna_shuddhi as ls
from bphs_core import muhurat, utils

COLOMBO = (6.9271, 79.8612, 5.5)
NEW_YORK = (40.7128, -74.0060, -5.0)
LONDON = (51.5074, -0.1278, 0.0)

_FLAGS = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_TRUEPOS
_SPAN = 360.0 / 27.0

# Ghatis elapsed in the star before its Varjyam begins (Drik Panchang's table,
# first listed ghati minus one), in nakshatra order Ashwini .. Revati. Mula:
# both windows.
CLASSICAL_VARJYAM_GHATIS = [
    (50,), (24,), (30,), (40,), (14,), (21,), (30,), (20,), (32,),
    (30,), (20,), (18,), (21,), (20,), (14,), (14,), (10,), (14,),
    (20, 56), (24,), (20,), (10,), (10,), (18,), (16,), (24,), (30,),
]
# Ghatis elapsed in the star before its Amrita Gadiya begins (Ramakumar).
CLASSICAL_AMRITA_GHATIS = [
    42, 48, 54, 52, 38, 35, 54, 44, 56,
    54, 44, 42, 45, 44, 38, 38, 34, 38,
    44, 48, 44, 34, 34, 42, 40, 48, 54,
]


# --------------------------------------------------------------------------- #
# Independent reference                                                        #
# --------------------------------------------------------------------------- #

def _sid(jd_ut: float, body: int) -> float:
    utils.probe_ephemeris_source()      # this thread's ephemeris path
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    return swe.calc_ut(jd_ut, body, _FLAGS)[0][0] % 360.0


def _moon(jd):
    return _sid(jd, swe.MOON)


def _elong(jd):
    return (_sid(jd, swe.MOON) - _sid(jd, swe.SUN)) % 360.0


def _sum(jd):
    return (_sid(jd, swe.MOON) + _sid(jd, swe.SUN)) % 360.0


def _cross(angle, target, lo, hi):
    def side(j):
        return (angle(j) - target + 180.0) % 360.0 - 180.0
    assert side(lo) < 0.0 <= side(hi)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if side(mid) < 0.0 else (lo, mid)
    return hi


def _midnight_ut(day: dt.date, tz: float) -> float:
    return swe.julday(day.year, day.month, day.day, 0.0) - tz / 24.0


def _event_ut(day, place, flag):
    lat, lon, tz = place
    utils.probe_ephemeris_source()
    _, tret = swe.rise_trans(_midnight_ut(day, tz), swe.SUN,
                             flag | swe.BIT_HINDU_RISING, (lon, lat, 0.0))
    return tret[0]


@functools.lru_cache(maxsize=None)
def _ref_star_windows(day: dt.date, place: tuple) -> tuple:
    """(1-based star, varjyam windows, amrita window) in hours from local
    midnight, for the star the Moon occupies at local noon."""
    tz = place[2]
    mid = _midnight_ut(day, tz)
    noon = mid + 0.5
    n = int(_moon(noon) // _SPAN)
    start = _cross(_moon, n * _SPAN, noon - 1.5, noon)
    end = _cross(_moon, ((n + 1) * _SPAN) % 360.0, noon, noon + 1.5)
    dur = end - start

    def window(g):
        return ((start + g / 60.0 * dur - mid) * 24.0,
                (start + (g + 4) / 60.0 * dur - mid) * 24.0)

    return (n + 1, tuple(window(g) for g in CLASSICAL_VARJYAM_GHATIS[n]),
            window(CLASSICAL_AMRITA_GHATIS[n]))


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _clock_diff(served: str, hours: float) -> float:
    """Minutes between a served HH:MM and a float hour, on the 24 h circle."""
    return abs((_mins(served) - hours * 60.0 + 720.0) % 1440.0 - 720.0)


# A served HH:MM is the minute the instant falls in, so it sits up to one
# minute below the instant; the slack covers that plus a solver tolerance.
_TOL_MIN = 1.5


def _served(day, place):
    return muhurat.compute_muhurat_for_day(utils.make_place("p", *place), day)


def _varjyam(out):
    return [w for w in out["inauspicious_periods"] if "Varjyam" in w["label"]]


# --------------------------------------------------------------------------- #
# The tables                                                                   #
# --------------------------------------------------------------------------- #

def test_the_varjyam_table_is_the_classical_one_for_all_27_stars():
    assert len(muhurat.VARJYAM_GHATIS) == 27
    for i, want in enumerate(CLASSICAL_VARJYAM_GHATIS):
        assert tuple(muhurat.VARJYAM_GHATIS[i]) == want, utils.NAKSHATRAS[i]


def test_the_amrita_table_is_the_classical_one_for_all_27_stars():
    assert len(muhurat.AMRITA_GHATIS) == 27
    for i, want in enumerate(CLASSICAL_AMRITA_GHATIS):
        assert muhurat.AMRITA_GHATIS[i] == want, utils.NAKSHATRAS[i]


def test_every_window_lasts_four_ghatis_of_a_sixty_ghati_star():
    assert (muhurat.WINDOW_GHATIS, muhurat.STAR_GHATIS) == (4, 60)


# --------------------------------------------------------------------------- #
# Varjyam and Amrita: worked examples                                          #
# --------------------------------------------------------------------------- #

def test_varjyam_colombo_2026_01_02_is_the_mrigashira_tyajya():
    """Worked example. The Moon enters Mrigashira (53 deg 20 min) at about
    22:48 on 2026-01-01 and leaves at about 20:04 on 01-02, 21.26 h. Its tyajya
    begins 14 ghatis in and lasts 4: 21.26 * 14/60 = 4.96 h after entry, so
    03:46, for 21.26 * 4/60 = 1.42 h, to 05:11. The library served 11:11-14:03
    (171 minutes) because it took the star's start as -22.81 h."""
    out = _served(dt.date(2026, 1, 2), COLOMBO)
    vj = _varjyam(out)
    assert [(w["start"], w["end"]) for w in vj] == [("03:46", "05:11")]
    n, ref_vj, ref_am = _ref_star_windows(dt.date(2026, 1, 2), COLOMBO)
    assert n == 5
    assert _clock_diff(vj[0]["start"], ref_vj[0][0]) <= _TOL_MIN
    assert _clock_diff(vj[0]["end"], ref_vj[0][1]) <= _TOL_MIN
    # Amrita Gadiya: 38 ghatis in -> 21.26 * 38/60 = 13.46 h after 22:48.
    am = out["amrita_periods"]
    assert [w["label"] for w in am] == ["Amrita Gadiya"]
    assert _clock_diff(am[0]["start"], ref_am[0]) <= _TOL_MIN
    assert _clock_diff(am[0]["end"], ref_am[1]) <= _TOL_MIN
    assert am[0]["start"] in ("12:16", "12:17")


def test_a_mula_day_serves_both_varjyam_windows():
    """2027-01-06, Colombo: the noon star is Mula, whose tyajya falls at 20 AND
    56 ghatis. The library returned both and the engine served only the first
    (12:07-13:55); the second, 04:20-06:08 on the next morning, was dropped."""
    out = _served(dt.date(2027, 1, 6), COLOMBO)
    n, ref_vj, _ = _ref_star_windows(dt.date(2027, 1, 6), COLOMBO)
    assert n == 19
    vj = _varjyam(out)
    assert len(vj) == 2
    for w, (s, e) in zip(vj, ref_vj):
        assert w["label"] == "Varjyam"
        assert _clock_diff(w["start"], s) <= _TOL_MIN
        assert _clock_diff(w["end"], e) <= _TOL_MIN
    assert [w["start"] for w in vj] == ["12:07", "04:20"]
    # The scan is handed one float pair per served window, in served order.
    hours = out[muhurat.VARJYAM_HOURS_KEY]
    assert len(hours) == 2
    for (s, e), (rs, re_) in zip(hours, ref_vj):
        assert abs(s - rs) * 60 <= _TOL_MIN and abs(e - re_) * 60 <= _TOL_MIN
    assert hours[1][0] > 24.0       # the second window is on the next morning


@pytest.mark.parametrize("place", [COLOMBO, NEW_YORK], ids=["colombo", "new_york"])
def test_varjyam_and_amrita_match_the_ephemeris_through_the_year(place):
    """Every 9th day of 2026 at two places. Measured on the library-based code
    at Colombo over the 365 days: the Varjyam start was off by more than an hour
    on 198 days and the Amrita start on 174."""
    bad = []
    for k in range(0, 365, 9):
        day = dt.date(2026, 1, 1) + dt.timedelta(days=k)
        out = _served(day, place)
        _, ref_vj, ref_am = _ref_star_windows(day, place)
        vj = _varjyam(out)
        if len(vj) != len(ref_vj):
            bad.append((day, "count", len(vj)))
            continue
        for w, (s, e) in zip(vj, ref_vj):
            if max(_clock_diff(w["start"], s), _clock_diff(w["end"], e)) > _TOL_MIN:
                bad.append((day, "varjyam", w["start"], w["end"]))
        am = out["amrita_periods"][0]
        if max(_clock_diff(am["start"], ref_am[0]),
               _clock_diff(am["end"], ref_am[1])) > _TOL_MIN:
            bad.append((day, "amrita", am["start"], am["end"]))
    assert bad == []


# --------------------------------------------------------------------------- #
# The scan vetoes BOTH Mula windows                                            #
# --------------------------------------------------------------------------- #

def test_a_surgery_scan_vetoes_the_second_mula_window(monkeypatch):
    lat, lon, tz = COLOMBO
    calls = []
    real = ls._score_instant

    def spy(jd, *args, **kwargs):
        score, detail = real(jd, *args, **kwargs)
        calls.append((jd, score, detail))
        return score, detail

    monkeypatch.setattr(ls, "_score_instant", spy)
    ls.scan_lagna_shuddhi(lat, lon, tz, None, None, "2027-01-07", "2027-01-07",
                          activity="surgery", step_seconds=300)
    _, ref_vj, _ = _ref_star_windows(dt.date(2027, 1, 6), COLOMBO)
    s2, e2 = ref_vj[1]
    mid = _midnight_ut(dt.date(2027, 1, 6), tz)
    inside = 0
    for jd, score, detail in calls:
        h = (jd - mid) * 24.0
        if s2 + 0.05 <= h <= e2 - 0.05:
            inside += 1
            assert detail["in_varjyam"] is True, h
            assert score == 0.0 and detail["hard_excluded"], h
    assert inside >= 1, "premise: the second Mula window was sampled"


def _mula_day(hours):
    return {
        "date": "2027-01-06", "sunrise": "06:27",
        "auspicious_muhurtas": [], "chogadiya": [],
        "inauspicious_periods": [
            {"start": "12:07", "end": "13:55", "label": "Varjyam"},
            {"start": "04:20", "end": "06:08", "label": "Varjyam"},
        ],
        muhurat.VARJYAM_HOURS_KEY: hours,
    }


def test_each_varjyam_window_is_placed_from_its_own_float_pair():
    day = _mula_day(((12.129, 13.93), (28.339, 30.14)))
    placed = [(s, e) for s, e, _ in ls._place_day_windows(day, 0)["inauspicious_periods"]]
    assert placed == [(727, 835), (1440 + 260, 1440 + 368)]


def test_a_varjyam_count_that_disagrees_with_its_float_pairs_raises():
    with pytest.raises(ValueError, match="Varjyam"):
        ls._place_day_windows(_mula_day(((12.129, 13.93),)), 0)


# --------------------------------------------------------------------------- #
# Panchanga end times                                                          #
# --------------------------------------------------------------------------- #

def _ref_ends(day: dt.date, place) -> dict[str, float]:
    """End of each limb in force at sunrise, hours after local midnight."""
    tz = place[2]
    mid = _midnight_ut(day, tz)
    rise = _event_ut(day, place, swe.CALC_RISE)
    e, s = _elong(rise), _sum(rise)
    out = {}
    for key, fn, part, value in (
        ("tithi", _elong, 12.0, e), ("karana", _elong, 6.0, e),
        ("yogam", _sum, _SPAN, s), ("nakshatra", _moon, _SPAN, _moon(rise)),
    ):
        target = ((int(value // part) + 1) * part) % 360.0
        out[key] = (_cross(fn, target, rise - 0.1, rise + 1.5) - mid) * 24.0
    return out


def test_tithi_end_colombo_2026_07_18_is_the_elongation_crossing():
    """Worked example. At sunrise on 2026-07-18 the elongation is in the 5th
    part of 12 degrees (Shukla Panchami); it reaches 60 degrees at about 03:43
    on the next morning (27.73 h after this date's midnight). The library's
    speed projection put the end at 03:23, 20 minutes early."""
    out = _served(dt.date(2026, 7, 18), COLOMBO)
    p = out["panchanga"]
    assert p["tithi"] == "Shukla Panchami"
    ref = _ref_ends(dt.date(2026, 7, 18), COLOMBO)
    assert 27.6 < ref["tithi"] < 27.8
    assert _clock_diff(p["tithi_end"], ref["tithi"]) <= _TOL_MIN
    assert p["tithi_end"] in ("03:43", "03:44")


@pytest.mark.parametrize("place", [COLOMBO, LONDON], ids=["colombo", "london"])
def test_panchanga_end_times_match_the_ephemeris(place):
    """Every 5th day from 2026-03-01 for 200 days. Measured on the library-based
    end times at Colombo: tithi up to 17.9 minutes off and more than 5 minutes
    off on a third of days; yoga up to 17.4."""
    bad = []
    for k in range(0, 200, 5):
        day = dt.date(2026, 3, 1) + dt.timedelta(days=k)
        p = _served(day, place)["panchanga"]
        ref = _ref_ends(day, place)
        for key, hours in ref.items():
            served = p[f"{key}_end"]
            if served is None or _clock_diff(served, hours) > _TOL_MIN:
                bad.append((day, key, served, round(hours, 3)))
    assert bad == []


# --------------------------------------------------------------------------- #
# Tuesday's night Durmuhurtam                                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("day", [dt.date(2026, 12, 8), dt.date(2026, 6, 16)])
def test_tuesday_night_durmuhurtam_is_the_7th_night_muhurta(day):
    """London, two Tuesdays. The night is cut into 15 muhurtas from sunset to
    the next sunrise; the 7th runs from 6/15 to 7/15 of it. The library ended
    it one DAY muhurta after its start: 22:15-22:46 in December (the muhurta is
    22:15-23:20) and 23:15-00:21 in June (the muhurta is 23:15-23:46)."""
    assert day.weekday() == 1
    tz = LONDON[2]
    mid = _midnight_ut(day, tz)
    sunset = _event_ut(day, LONDON, swe.CALC_SET)
    next_rise = _event_ut(day + dt.timedelta(days=1), LONDON, swe.CALC_RISE)
    night = next_rise - sunset
    want_s = (sunset + night * 6 / 15 - mid) * 24.0
    want_e = (sunset + night * 7 / 15 - mid) * 24.0
    out = _served(day, LONDON)
    p2 = [w for w in out["inauspicious_periods"] if w["label"] == "Durmuhurtam Period 2"]
    assert len(p2) == 1
    assert _clock_diff(p2[0]["start"], want_s) <= _TOL_MIN
    assert _clock_diff(p2[0]["end"], want_e) <= _TOL_MIN
    # ... and it is the served 7th night muhurta (index 15 + 6).
    m7 = out["all_muhurtas"][21]
    assert (p2[0]["start"], p2[0]["end"]) == (m7["start"], m7["end"])


def test_the_tuesday_day_durmuhurtam_is_unchanged():
    """Period 1 on a Tuesday is the 4th DAY muhurta, and stays the library's."""
    out = _served(dt.date(2026, 12, 8), LONDON)
    p1 = [w for w in out["inauspicious_periods"] if w["label"] == "Durmuhurtam Period 1"]
    m4 = out["all_muhurtas"][3]
    assert (p1[0]["start"], p1[0]["end"]) == (m4["start"], m4["end"])


# --------------------------------------------------------------------------- #
# Abhijit is not auspicious on the day it is Durmuhurtam                       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("offset", range(7))
def test_abhijit_is_served_on_every_weekday_but_wednesday(offset):
    day = dt.date(2026, 12, 6) + dt.timedelta(days=offset)    # Sunday ..
    out = _served(day, COLOMBO)
    labels = [w["label"] for w in out["auspicious_muhurtas"]]
    assert ("Abhijit Muhurta" in labels) is (day.weekday() != 2), day
    durm = {(w["start"], w["end"]) for w in out["inauspicious_periods"]
            if "Durmuhurt" in w["label"]}
    abhijit = {(w["start"], w["end"]) for w in out["auspicious_muhurtas"]
               if w["label"] == "Abhijit Muhurta"}
    assert not durm & abhijit, day


def test_wednesday_2026_12_09_colombo_serves_no_abhijit():
    """Worked example from the audit: Abhijit 11:39-12:25 was served as
    auspicious while Durmuhurtam Period 1 was the same 11:39-12:25."""
    out = _served(dt.date(2026, 12, 9), COLOMBO)
    assert "Abhijit Muhurta" not in [w["label"] for w in out["auspicious_muhurtas"]]
    assert ("11:39", "12:25") in [
        (w["start"], w["end"]) for w in out["inauspicious_periods"]
        if w["label"] == "Durmuhurtam Period 1"
    ]
