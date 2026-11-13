"""A candidate instant is scored against the Vedic day -- sunrise to the next
sunrise -- that actually contains it, and every window is placed on the civil
date it falls on.

The defect this pins: the night windows of civil date D (night chogadiya,
Nishita, the night Vijaya muhurta, the night Durmuhurtam) run from D's sunset to
D+1's sunrise, but the engine served them as bare HH:MM and the scan added
their after-midnight minutes as candidates ON D. So "D 02:00" was scored with
the chogadiya of the night that begins on the evening of D, although 02:00 on D
lies in the night that began on the evening of D-1; its hora lord and weekday
were likewise taken from D rather than from the vaara it belongs to. A Varjyam
window that falls on the previous evening was folded onto D the same way.

The classical rules this restores:

* The vaara runs from sunrise to the next sunrise, and the kala-horas are
  counted from the vaara's own sunrise, the first belonging to the vaara lord
  and the rest descending in the Chaldean order (the panchanga convention,
  "udayad udayam vaarah"; the hora order is that of Surya Siddhanta ch. XII,
  the regents of the hours). The engine already counted horas from sunrise; it
  applied the count to the wrong day for an instant before sunrise.
* The Gauri chogadiya divides the day (sunrise to sunset) and the following
  night (sunset to the next sunrise) into eight parts each, the sequence set by
  the vaara -- so a pre-dawn instant takes its chogadiya from the PREVIOUS
  vaara's night.

Every expectation is computed independently: sunrise from ``swe.rise_trans``,
the hora lord from the hand-typed Chaldean order, and the night chogadiya
label from the night it falls in. The data is fictitious: a public city's
coordinates and no birth data.
"""
from __future__ import annotations

import datetime as dt
import functools

from fastapi.testclient import TestClient
from jhora.panchanga import drik

from app.main import app
from bphs_core import lagna_shuddhi as ls
from bphs_core import muhurat, utils
from tests import _panchanga_reference as ref
from tests.conftest import SAMPLE_A

LAT, LON, TZ = 6.9271, 79.8612, 5.5          # Colombo (public city coordinates)
PLACE = utils.make_place("colombo", LAT, LON, TZ)

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

# Minutes either side of a sunrise or hora boundary within which a comparison
# is skipped: the engine renders sunrise to the minute and samples whole
# minutes, so the last minute on either side of a boundary is a rendering
# question, not an attribution one.
_EDGE_MIN = 3.0


def _spy(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    real = ls._score_instant

    def spy(jd, lagna_sign, lagna_lord, day_data, *args, **kwargs):
        score, detail = real(jd, lagna_sign, lagna_lord, day_data, *args, **kwargs)
        calls.append({"jd": jd, "score": score, "detail": detail,
                      "day_data": day_data})
        return score, detail

    monkeypatch.setattr(ls, "_score_instant", spy)
    return calls


def _local(jd: float) -> tuple[dt.date, float]:
    day, minutes = ref.local_from_jd_ut(jd, TZ)
    return day, round(minutes)


def _hhmm(s: str) -> int:
    return int(s[:2]) * 60 + int(s[3:5])


@functools.lru_cache(maxsize=None)
def _night_windows(prev_day: dt.date) -> tuple[dict, ...]:
    return tuple(muhurat.compute_muhurat_for_day(PLACE, prev_day)["chogadiya"][8:])


def _night_label(prev_day: dt.date, day: dt.date, minutes: float) -> str | None:
    """Label of the night chogadiya of *prev_day* containing *day* + *minutes*.

    The night list is the second half of the served sixteen windows; it starts
    at prev_day's sunset and its after-midnight windows wrap the clock. The
    expectation is read off that night only -- the night the instant is in.
    """
    windows = _night_windows(prev_day)
    assert len(windows) == 8
    t = minutes + 1440 * (day - prev_day).days
    carry = 0
    last = None
    for w in windows:
        s, e = _hhmm(w["start"]), _hhmm(w["end"])
        if last is not None and s + carry < last:
            carry += 1440
        s += carry
        e = s + (e - _hhmm(w["start"])) % 1440
        last = s
        if s + 1 <= t < e - 1:
            return w["label"]
    return None


def _assert_vedic_attribution(calls: list[dict]) -> int:
    """Hora lord, weekday and (pre-dawn) chogadiya follow the Vedic day.

    The hora and chogadiya are only filled in for an instant that survives the
    hard vetoes (a Rahu Kala instant is scored 0.0 before either is read), so
    those two are checked on the surviving instants; the vaara handed to the
    scorer is checked on every instant.
    """
    pre_dawn = 0
    for c in calls:
        day, minutes = _local(c["jd"])
        rise = ref.sunrise_minutes(day, LAT, LON, TZ)
        if abs(minutes - rise) < _EDGE_MIN:
            continue
        vaara, _ = ref.vedic_day(day, minutes, LAT, LON, TZ)
        assert c["day_data"]["panchanga"]["vaara"] == vaara.strftime("%A"), (day, minutes)
        if c["detail"]["hard_excluded"]:
            continue
        lord, to_edge = ref.hora_lord_at(day, minutes, LAT, LON, TZ)
        if to_edge >= _EDGE_MIN:
            assert c["detail"]["hora_lord"] == lord, (day, minutes, c["detail"]["hora_lord"], lord)
        if minutes < rise:
            pre_dawn += 1
            want = _night_label(day - dt.timedelta(days=1), day, minutes)
            if want is not None:
                assert c["detail"]["chogadiya_label"] == want, (day, minutes)
    return pre_dawn


def test_scan_attributes_pre_dawn_instants_to_the_previous_vaara(monkeypatch):
    calls = _spy(monkeypatch)
    out = ls.scan_lagna_shuddhi(
        LAT, LON, TZ, None, None, "2026-12-16", "2026-12-18",
        activity="generic", step_seconds=600,
    )
    assert out["best_instant"] is not None
    assert _assert_vedic_attribution(calls) >= 10, "premise: pre-dawn instants scanned"


def test_every_scanned_instant_lies_on_a_requested_civil_date(monkeypatch):
    """A window that crosses midnight contributes its after-midnight minutes to
    the NEXT civil date: a one-day request never yields an instant from the
    night that follows it, and its own pre-dawn hours come from the night
    before it."""
    calls = _spy(monkeypatch)
    ls.scan_lagna_shuddhi(
        LAT, LON, TZ, None, None, "2026-12-16", "2026-12-16",
        activity="generic", step_seconds=600,
    )
    days = {_local(c["jd"])[0] for c in calls}
    assert days == {dt.date(2026, 12, 16)}
    # The night of 12-15 has favourable chogadiya after midnight, so the
    # request's own pre-dawn hours are candidates, labelled from that night.
    assert _assert_vedic_attribution(calls) >= 5


def test_family_scan_attributes_pre_dawn_instants_to_the_previous_vaara(monkeypatch):
    calls = _spy(monkeypatch)
    members = [
        {"name": "a", "lat": LAT, "lon": LON, "tz_offset": TZ,
         "birth_nakshatra": None, "birth_moon_sign": None},
        {"name": "b", "lat": LAT, "lon": LON, "tz_offset": TZ,
         "birth_nakshatra": None, "birth_moon_sign": None},
    ]
    ls.scan_family_lagna_shuddhi(
        members, "2026-12-16", "2026-12-17", activity="generic", step_seconds=600,
    )
    assert _assert_vedic_attribution(calls) >= 10


def test_lagna_shuddhi_route_attributes_pre_dawn_instants(monkeypatch):
    calls = _spy(monkeypatch)
    body = {
        **SAMPLE_A, "latitude": LAT, "longitude": LON, "timezone_offset_hours": TZ,
        "start_date": "2026-12-16", "end_date": "2026-12-17",
        "activity_category": "generic", "step_seconds": 600,
    }
    r = client.post("/v1/muhurat/lagna-shuddhi", json=body)
    assert r.status_code == 200, r.text
    assert _assert_vedic_attribution(calls) >= 10
    # And what is SERVED matches what was scored: each top sample's hora lord
    # is the Vedic one for its instant.
    for s in r.json()["top_samples"]:
        day_s, hhmm = s["instant"].split(" ")
        day = dt.date.fromisoformat(day_s)
        minutes = _hhmm(hhmm)
        lord, to_edge = ref.hora_lord_at(day, minutes, LAT, LON, TZ)
        if to_edge >= _EDGE_MIN:
            assert s["hora_lord"] == lord, s["instant"]


# --------------------------------------------------------------------------- #
# Varjyam lies where the library places it in time, not on the civil date of  #
# the day that computed it.                                                    #
# --------------------------------------------------------------------------- #

_EPOCH = dt.date(2026, 12, 1)


def _varjyam_abs(day: dt.date) -> tuple[float, float, bool]:
    """The library's Varjyam for *day*: (start, end, degenerate), in minutes
    after 2026-12-01 00:00 local.

    On a few days the library returns a zero-width Varjyam; the engine has
    always read a window whose start and end render to the same minute as the
    whole civil day, and still does (fail closed for the surgery veto), so the
    expectation models that reading rather than an empty window.
    """
    jd = utils.swe.julday(day.year, day.month, day.day, 12.0)
    v = drik.varjyam(jd, PLACE)
    base = (day - _EPOCH).days * 1440.0
    s, e = base + v[0] * 60.0, base + v[1] * 60.0
    if e - s < 1.0:
        return base, base + 1440.0, True
    return s, e, False


def _find_previous_evening_varjyam() -> dt.date:
    """A day whose own Varjyam lies wholly on the PREVIOUS evening, and whose
    previous day's Varjyam is a real (non-degenerate) window too."""
    for i in range(3, 28):
        day = _EPOCH + dt.timedelta(days=i)
        s, e, degenerate = _varjyam_abs(day)
        base = i * 1440.0
        if (not degenerate and s < base - 120 and e - s > 60 and e < base
                and not _varjyam_abs(day - dt.timedelta(days=1))[2]):
            return day
    raise AssertionError("no day with a Varjyam wholly on the previous evening")


def test_surgery_scan_places_varjyam_on_the_date_it_falls_on(monkeypatch):
    frame = _find_previous_evening_varjyam()
    prev = frame - dt.timedelta(days=1)
    windows = [_varjyam_abs(prev + dt.timedelta(days=k)) for k in range(-1, 4)]
    calls = _spy(monkeypatch)
    ls.scan_lagna_shuddhi(
        LAT, LON, TZ, None, None, prev.isoformat(), frame.isoformat(),
        activity="surgery", step_seconds=300,
    )
    moved = 0
    for c in calls:
        day, minutes = _local(c["jd"])
        t = (day - _EPOCH).days * 1440.0 + minutes
        if any(abs(t - b) < 2 for s, e, _ in windows for b in (s, e)):
            continue
        hits = [(s, e, deg) for s, e, deg in windows if s <= t < e]
        assert c["detail"]["in_varjyam"] is bool(hits), (day, minutes)
        if hits:
            assert c["score"] == 0.0 and c["detail"]["hard_excluded"]
        # An instant inside the frame day's own Varjyam, which falls on the
        # civil date BEFORE that day: the case the old folding got wrong.
        s_f, e_f, _ = windows[2]
        if s_f <= t < e_f and day == prev:
            moved += 1
    assert moved >= 1, "premise: the previous-evening Varjyam was sampled"
