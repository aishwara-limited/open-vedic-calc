"""The electional scan reads the tithi, karana and yoga AT THE CANDIDATE INSTANT,
and the served day panchanga is the one prevailing at SUNRISE.

The defect this pins: ``compute_muhurat_for_day`` evaluated every panchanga
limb at local noon, and ``_score_instant`` then read those day-level names for
every candidate minute of the civil day. A karana lasts about half a day, so a
Vishti (Bhadra) karana beginning in the afternoon was not vetoed for marriage
that evening, while a day whose NOON karana was Vishti was vetoed all day long,
hours after Vishti had ended. The Rikta/Amavasya tithi and avoided-yoga
penalties carried the same error, and the day panchanga served to the caller
was the noon one rather than the sunrise one every printed panchanga uses.

The classical rules:

* A tithi, karana or yoga prevails over an instant when the Moon-Sun
  elongation (tithi, karana) or the sidereal Sun+Moon sum (yoga) at THAT
  instant lies in its span -- Surya Siddhanta ch. II vv. 64-69 (Burgess 1860).
  There is no day-level karana: the limb changes whenever the longitudes cross
  a bucket edge, at any time of day.
* Bhadra (the Vishti karana) is avoided for marriage and other auspicious
  beginnings -- Muhurta Chintamani, ch. 1 (Shubhashubha Prakarana), the
  Bhadra verses. This file does not change that rule; it changes WHEN the
  karana it reads is evaluated.
* The day's panchanga is the one prevailing at sunrise (the udaya-tithi
  convention every printed panchanga follows); a limb that ends during the day
  is reported with its end time.

Every expected value below is computed independently, from the ephemeris
(``swe.calc_ut`` / ``swe.rise_trans``) and the hand-typed classical tables in
``tests/_panchanga_reference.py`` -- never from the engine's own helpers. The
data is fictitious: a public city's coordinates and no birth data.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bphs_core import lagna_shuddhi as ls
from bphs_core import muhurat, utils
from tests import _panchanga_reference as ref
from tests.conftest import SAMPLE_A

LAT, LON, TZ = 6.9271, 79.8612, 5.5          # Colombo (public city coordinates)
PLACE = utils.make_place("colombo", LAT, LON, TZ)

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})


def _spy_scores(monkeypatch) -> list[dict]:
    """Record every (instant, score, detail) the REAL scorer produces."""
    calls: list[dict] = []
    real = ls._score_instant

    def spy(jd, *args, **kwargs):
        score, detail = real(jd, *args, **kwargs)
        calls.append({"jd": jd, "score": score, "detail": detail})
        return score, detail

    monkeypatch.setattr(ls, "_score_instant", spy)
    return calls


def _scan(monkeypatch, activity: str, start: str, end: str, step: int = 600):
    calls = _spy_scores(monkeypatch)
    out = ls.scan_lagna_shuddhi(
        LAT, LON, TZ, None, None, start, end, activity=activity,
        step_seconds=step,
    )
    return out, calls


def _local(jd: float) -> tuple[dt.date, int]:
    day, minutes = ref.local_from_jd_ut(jd, TZ)
    return day, round(minutes)


# --------------------------------------------------------------------------- #
# The rule itself, exhaustively, as a pure function of the two longitudes.    #
# --------------------------------------------------------------------------- #

class TestPanchangaFromLongitudesIsExhaustive:
    """All 30 tithis, all 60 karanas and all 27 yogas, each at mid-span."""

    @pytest.mark.parametrize("i", range(30))
    def test_every_tithi(self, i):
        sun = 123.0
        p = muhurat.panchanga_from_longitudes(sun, (sun + 12.0 * i + 6.0) % 360)
        assert p.tithi == ref.TITHI_NAMES_30[i]

    @pytest.mark.parametrize("k", range(60))
    def test_every_karana(self, k):
        sun = 271.5
        p = muhurat.panchanga_from_longitudes(sun, (sun + 6.0 * k + 3.0) % 360)
        assert p.karana == ref.KARANA_NAMES_60[k]

    @pytest.mark.parametrize("j", range(27))
    def test_every_yoga(self, j):
        total = ref.NAKSHATRA_SPAN * j + ref.NAKSHATRA_SPAN / 2
        sun = 200.0
        p = muhurat.panchanga_from_longitudes(sun, (total - sun) % 360)
        assert p.yoga == ref.YOGA_NAMES_27[j]

    def test_elongation_wraps_through_zero(self):
        # Moon 10 deg, Sun 350 deg: elongation 20 deg -> Shukla Dwitiya, and
        # the 4th karana (Kaulava). The sum is 360 deg -> 0 -> the first yoga.
        p = muhurat.panchanga_from_longitudes(350.0, 10.0)
        assert p.tithi == "Shukla Dwitiya"
        assert p.karana == "Kaulava"
        assert p.yoga == "Vishkumbha"

    def test_a_moon_a_hair_behind_the_sun_is_new_moon(self):
        # (moon - sun) is -1.8e-15 here, which `% 360` rounds to exactly 360.0.
        p = muhurat.panchanga_from_longitudes(10.0, 10.0 - 1e-15)
        assert (10.0 - 1e-15 - 10.0) % 360.0 == 360.0
        assert p.tithi == "Shukla Prathama"
        assert p.karana == "Kimstughna"

    def test_instant_helper_matches_the_ephemeris(self):
        """The JD helper applies the rule to the engine's own longitudes."""
        checked = 0
        for hours in range(0, 48, 3):
            jd = ref.local_jd_ut(dt.date(2026, 12, 29), hours * 60.0, TZ)
            p = muhurat.panchanga_at_instant(jd)
            for got, want in (
                (p.tithi, ref.tithi_at(jd)),
                (p.karana, ref.karana_at(jd)),
                (p.yoga, ref.yoga_at(jd)),
            ):
                if want is not None:
                    assert got == want, (hours, got, want)
                    checked += 1
        assert checked >= 40


# --------------------------------------------------------------------------- #
# Worked example 1: a Vishti that begins in the AFTERNOON of a day whose noon  #
# karana is not Vishti. 2026-12-29, Colombo: Vanija at noon, Vishti from about #
# 13:30 local to about 01:00 the next morning -- asserted below from the       #
# ephemeris, not assumed.                                                      #
# --------------------------------------------------------------------------- #

def test_premise_vishti_begins_after_noon_on_2026_12_29():
    day = dt.date(2026, 12, 29)
    assert ref.karana_at(ref.local_jd_ut(day, 12 * 60, TZ)) == "Vanija"
    assert ref.karana_at(ref.local_jd_ut(day, 15 * 60, TZ)) == "Vishti"
    assert ref.karana_at(ref.local_jd_ut(day, 23 * 60, TZ)) == "Vishti"


def test_marriage_scan_vetoes_every_instant_inside_an_afternoon_vishti(monkeypatch):
    _, calls = _scan(monkeypatch, "marriage", "2026-12-29", "2026-12-29")
    in_vishti = [c for c in calls if ref.karana_at(c["jd"]) == "Vishti"]
    assert len(in_vishti) >= 5, "premise: the scan sampled the Vishti interval"
    leaked = [
        (_local(c["jd"]), c["score"]) for c in in_vishti
        if c["score"] != 0.0 or not c["detail"]["hard_excluded"]
    ]
    assert leaked == [], f"Vishti instants scored for marriage: {leaked[:5]}"


# --------------------------------------------------------------------------- #
# Worked example 2: a day whose NOON karana is Vishti but whose Vishti ENDS in #
# the afternoon. 2026-12-07, Colombo: Vishti from about 02:30 to about 15:20.  #
# --------------------------------------------------------------------------- #

def test_marriage_scan_does_not_veto_after_vishti_has_ended(monkeypatch):
    day = dt.date(2026, 12, 7)
    assert ref.karana_at(ref.local_jd_ut(day, 12 * 60, TZ)) == "Vishti"
    assert ref.karana_at(ref.local_jd_ut(day, 17 * 60, TZ)) not in ("Vishti", None)
    dd = muhurat.compute_muhurat_for_day(PLACE, day)
    assert dd["is_eclipse_day"] is False and dd["is_adhik_maasa"] is False

    _, calls = _scan(monkeypatch, "marriage", "2026-12-07", "2026-12-07")
    clear = []
    for c in calls:
        d = c["detail"]
        if d["in_rahu_kala"] or d["in_yamaganda"] or d["in_gulika"]:
            continue
        k = ref.karana_at(c["jd"])
        if k is None or k == "Vishti":
            continue
        clear.append(c)
    assert len(clear) >= 5, "premise: instants after Vishti were sampled"
    wrongly_vetoed = [_local(c["jd"]) for c in clear if c["score"] == 0.0]
    assert wrongly_vetoed == [], f"vetoed with no Vishti in force: {wrongly_vetoed[:5]}"


# --------------------------------------------------------------------------- #
# The tithi and yoga a sample carries -- and is scored on -- are the ones at   #
# its instant. 2026-12-16 changes yoga at about 13:45 and tithi at about 22:51.#
# --------------------------------------------------------------------------- #

def test_each_sample_carries_the_tithi_and_yoga_of_its_instant(monkeypatch):
    _, calls = _scan(monkeypatch, "generic", "2026-12-16", "2026-12-16")
    seen_tithis, seen_yogas, checked = set(), set(), 0
    for c in calls:
        want_t, want_y = ref.tithi_at(c["jd"]), ref.yoga_at(c["jd"])
        if want_t is not None:
            assert c["detail"]["tithi"] == want_t, (_local(c["jd"]), c["detail"]["tithi"])
            seen_tithis.add(want_t)
            checked += 1
        if want_y is not None:
            assert c["detail"]["yoga"] == want_y, (_local(c["jd"]), c["detail"]["yoga"])
            seen_yogas.add(want_y)
    assert checked >= 20
    assert len(seen_tithis) >= 2 and len(seen_yogas) >= 2, (
        "premise: the day's tithi and yoga each change inside the scanned candidates"
    )


def test_panchanga_suitability_follows_the_instant(monkeypatch):
    """Rikta/Amavasya/avoided-yoga suitability is judged on the instant's limbs.

    At Colombo, Shukla Navami -- a Rikta tithi -- runs to about 23:00 on
    2026-12-18 and Dashami follows, so the Rikta penalty must lift part-way
    through the vaara that began at Navami's sunrise."""
    _, calls = _scan(monkeypatch, "generic", "2026-12-18", "2026-12-19")
    judged = set()
    rikta_seen = after_rikta = False
    for c in calls:
        d = c["detail"]
        if d["hard_excluded"]:
            continue
        t, y = ref.tithi_at(c["jd"]), ref.yoga_at(c["jd"])
        if t is None or y is None:
            continue
        unsuitable = (
            any(r in t for r in ("Chaturthi", "Navami", "Chaturdashi"))
            or "Amavasya" in t
            or y in {"Vishkumbha", "Atiganda", "Shula", "Ganda", "Vyaghata",
                     "Vajra", "Vyatipata", "Parigha", "Vaidhriti"}
        )
        assert d["panchanga_suitable"] is (not unsuitable), (_local(c["jd"]), t, y)
        judged.add(unsuitable)
        rikta_seen |= "Navami" in t
        after_rikta |= "Dashami" in t and c["detail"]["tithi"] == t
    assert judged == {True, False}, "premise: both verdicts occur in the window"
    assert rikta_seen and after_rikta, "premise: both sides of Navami's end judged"


# --------------------------------------------------------------------------- #
# Through the HTTP route: the served samples carry their own instant's limbs, #
# and no served or scored instant inside Vishti escapes the marriage veto.    #
# --------------------------------------------------------------------------- #

def test_lagna_shuddhi_route_serves_instant_limbs_and_vetoes_vishti(monkeypatch):
    calls = _spy_scores(monkeypatch)
    body = {
        **SAMPLE_A, "latitude": LAT, "longitude": LON, "timezone_offset_hours": TZ,
        "start_date": "2026-12-29", "end_date": "2026-12-29",
        "activity_category": "marriage", "step_seconds": 600,
    }
    r = client.post("/v1/muhurat/lagna-shuddhi", json=body)
    assert r.status_code == 200, r.text
    assert any(ref.karana_at(c["jd"]) == "Vishti" for c in calls)
    for c in calls:
        if ref.karana_at(c["jd"]) == "Vishti":
            assert c["score"] == 0.0, _local(c["jd"])
    samples = r.json()["top_samples"]
    assert samples
    for s in samples:
        day_s, hhmm = s["instant"].split(" ")
        h, m = map(int, hhmm.split(":"))
        jd = ref.local_jd_ut(dt.date.fromisoformat(day_s), h * 60 + m, TZ)
        if ref.tithi_at(jd) is not None:
            assert s["tithi"] == ref.tithi_at(jd), s["instant"]
        if ref.yoga_at(jd) is not None:
            assert s["yoga"] == ref.yoga_at(jd), s["instant"]
        if ref.karana_at(jd) == "Vishti":
            assert s["score"] == 0.0, s["instant"]


# --------------------------------------------------------------------------- #
# The served DAY panchanga is the sunrise one.                                 #
# --------------------------------------------------------------------------- #

_DAYS = [dt.date(2026, 12, 1) + dt.timedelta(days=i) for i in range(30)]
_LIMBS = (("tithi", ref.tithi_at), ("karana", ref.karana_at),
          ("yogam", ref.yoga_at), ("nakshatra", ref.nakshatra_at))


def _sunrise_jd(day: dt.date) -> float:
    return ref.local_jd_ut(day, ref.sunrise_minutes(day, LAT, LON, TZ), TZ)


def test_day_panchanga_is_the_one_prevailing_at_sunrise():
    differs_from_noon = {key: 0 for key, _ in _LIMBS}
    for day in _DAYS:
        served = muhurat.compute_muhurat_for_day(PLACE, day)["panchanga"]
        jd_rise = _sunrise_jd(day)
        jd_noon = ref.local_jd_ut(day, 12 * 60, TZ)
        for key, fn in _LIMBS:
            want = fn(jd_rise)
            if want is not None:
                assert served[key] == want, (day, key, served[key], want)
                if fn(jd_noon) not in (None, want):
                    differs_from_noon[key] += 1
    # Premise: on this window every limb changes between sunrise and noon on at
    # least one day, so the noon value cannot pass this test by coincidence.
    assert all(n >= 1 for n in differs_from_noon.values()), differs_from_noon


# The library's end times are a speed-based estimate. Measured at sunrise over
# December 2026 at three cities (UTC+5:30, +9 and -5) against the instant the
# limb actually changes: tithi within 19.9 min, yoga 14.0, karana 4.7,
# nakshatra 0.3. The tolerances sit just above those, and far below the hours
# by which the end of the NOON limb misses the end of the sunrise one.
_END_TOLERANCE_MIN = {"tithi": 25.0, "yogam": 20.0, "karana": 8.0, "nakshatra": 2.0}
_BUCKETS = {
    "tithi": lambda jd: int(ref.elongation(jd) // 12.0),
    "karana": lambda jd: int(ref.elongation(jd) // 6.0),
    "yogam": lambda jd: int(ref.sidereal_sum(jd) // ref.NAKSHATRA_SPAN),
    "nakshatra": lambda jd: ref.nakshatra_index(jd),
}


def _change_after(jd0: float, bucket) -> float:
    """UT JD at which *bucket* first changes after *jd0* (bisection)."""
    start, lo, hi = bucket(jd0), jd0, jd0
    while bucket(hi) == start:
        lo, hi = hi, hi + 1.0 / 96.0
        assert hi - jd0 < 2.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        lo, hi = (mid, hi) if bucket(mid) == start else (lo, mid)
    return hi


def test_day_panchanga_end_times_belong_to_the_sunrise_limbs():
    far_off = 0
    for day in _DAYS:
        served = muhurat.compute_muhurat_for_day(PLACE, day)["panchanga"]
        jd_rise = _sunrise_jd(day)
        midnight = ref.local_jd_ut(day, 0.0, TZ)
        for key, fn in _LIMBS:
            end = served[f"{key}_end"]
            if end is None or fn(jd_rise) is None:
                continue
            true_min = (_change_after(jd_rise, _BUCKETS[key]) - midnight) * 1440.0
            served_min = int(end[:2]) * 60 + int(end[3:5])
            diff = abs((served_min - true_min + 720.0) % 1440.0 - 720.0)
            assert diff <= _END_TOLERANCE_MIN[key], (day, key, end, round(true_min))
            far_off += diff > 60
    assert far_off == 0


def test_muhurat_route_serves_the_sunrise_panchanga():
    body = {
        **SAMPLE_A, "latitude": LAT, "longitude": LON, "timezone_offset_hours": TZ,
        "start_date": "2026-12-01", "end_date": "2026-12-30",
    }
    r = client.post("/v1/muhurat", json=body)
    assert r.status_code == 200, r.text
    days = r.json()["days"]
    assert len(days) == 30
    for served in days:
        day = dt.date.fromisoformat(served["date"])
        jd_rise = _sunrise_jd(day)
        for key, fn in _LIMBS:
            want = fn(jd_rise)
            if want is not None:
                assert served["panchanga"][key] == want, (day, key)
