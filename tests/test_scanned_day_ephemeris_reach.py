"""A scanned day does not merely look up the day it was asked about.

``tests/test_date_field_ephemeris_range.py`` bounds every date field to the span
the shipped Swiss files cover for a POINT lookup. That is the right bound for
``birth_date`` and ``at_date``, which read the instant they name. It is not the
right bound for the three electional ``start_date``/``end_date`` pairs, because
``compute_muhurat_for_day`` reaches well outside the day it is scanning: the
lunar-month and yoga limbs search for events that are, by construction, not on
that day.

WHAT REACHES HOW FAR — MEASURED, per limb
-----------------------------------------
Each ``drik`` entry point ``compute_muhurat_for_day`` calls was driven over 702
probes (117 scanned days spanning three synodic months plus a spread across a
year, x 6 timezone corners), recording the furthest Julian Day its
``swe.calc_ut`` calls touch, as days from the scanned date's 00:00 UT::

    drik.lunar_month  (via _is_adhik_maasa)   +31.834 d      -2025.746 d
    drik.yogam                                +24.859 d          -0.083 d
    drik.nakshatra / varjyam / amrita_gadiya
      / panchaka_rahitha                       +2.543 d          -1.398 d
    drik.tithi / karana                        +1.998 d          -0.083 d

``drik.yogam``, ``drik.nakshatra``, ``drik.varjyam`` and ``drik.amrita_gadiya``
are no longer called: the four panchanga end times and the nakshatra span
behind Varjyam and Amrita Gadiya are solved by bisection
(``bphs_core.muhurat._solve_crossing``), whose brackets were measured reaching
-1.283 d / +2.2 d over latitudes -66..66 x four timezone corners x 13 dates --
inside the rows above. The forward ceiling is still ``lunar_month``'s.

Re-measured at the LOW edge (scanned days 1800-01-02..1806-07-30, 8 timezone
corners), driving ``compute_muhurat_for_day`` whole, the forward ceiling is
unchanged: **+31.835 d**, at 1800-01-25 and again at 1804-02-11. The forward
reach is therefore a property of the lunar month, not of the era, which is what
makes one constant safe to derive from it.

TWO CORRECTIONS TO WHAT THIS REPO PREVIOUSLY RECORDED
-----------------------------------------------------
1. ``drik.tithi``'s next-day search was named as a primary cause of the
   end-of-range residual. Measured, it is the SMALLEST of the out-of-day
   reaches (+1.998 d). The limb that actually reaches furthest forward after
   ``lunar_month`` is ``drik.yogam``, at +24.859 d, which no note in this
   repository mentioned.
2. The earlier measurement used a spy declared ``def spy(jd, planet, flags,
   *a, **k)``. pyjhora calls ``swe.calc_ut(jd_utc, planet, flags=flags)`` by
   KEYWORD on the ``sidereal_longitude`` path, so that spy survives only because
   its third parameter happens to be spelled ``flags``; renaming it raises
   TypeError and the probe silently records nothing. The spy here takes
   ``*args, **kwargs`` and proves its own liveness against BOTH spellings before
   any count is read, because a zero has to mean absence and not a broken probe.

WHY THE REACH IS BOUNDED AND THE BOUND IS NOT ARBITRARY
-------------------------------------------------------
``_is_adhik_maasa`` asks whether the amanta month containing the scanned day is
intercalary, which requires the new moons bracketing it. The furthest of those
is at most one synodic month away (max ~29.83 d), plus the scanned day itself
and the timezone span (up to 0.583 d at tz=+14) — a ceiling near 31.4 d, against
the 31.835 d measured. The upper bound is set so that ceiling clears the end of
the data with margin, and the margin is asserted below rather than asserted to
exist.

WHAT THIS MODULE DOES NOT CLAIM
-------------------------------
The lower bound is NOT narrowed, and that is a measured decision rather than an
omission. ``drik.lunar_month`` also searches BACKWARD, to an anchor rather than
through a window: from 1800-01-02 it reaches -540.974 d, landing on 1798-07-10,
and the distance grows day by day because the anchor stays put. It resets
periodically — measured across 1800-01-02..1806-07-30 the backward reach is a
sawtooth with an amplitude up to -1605.399 d (at 1805-10-03) that falls back to
-17.475 d (at 1806-07-30). Bounding that away would cost roughly four and a half
years of the served range.

It is not narrowed because the measurement says it would buy nothing. The
question that decides it is not "does the search leave the files" — it does —
but "does the engine STAY on the fallback afterwards", as it does for a read past
the END of the files. Measured, it does not: after ``_is_adhik_maasa`` runs at
the extremes of that sawtooth, and after a FULL low-edge day compute, an in-span
lookup still answers from Swiss data. The stickiness ``_is_eclipse_day`` had to
restore around is not symmetric, so no restore was added and no bound was moved.
That asymmetry is asserted in ``tests/test_muhurat_edge_probe_engine.py``, not
here — it is the evidence for a decision NOT to change something, which is
exactly the kind of claim that has to stay falsifiable.
"""
import datetime
import os
import threading

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("CALC_SERVICE_TOKEN", "test")
os.environ.setdefault("PUBLIC_SOURCE_URL", "https://example.com")

import swisseph as swe
from jhora.panchanga import drik

from app.schemas import MAX_EPHEMERIS_DATE, MIN_EPHEMERIS_DATE, MuhurtRequest
from bphs_core import muhurat, utils
from tests.conftest import SAMPLE_A

_ONE_DAY = datetime.timedelta(days=1)

# Every legal timezone offset corner, plus interior values. The bound is a LOCAL
# date while the ephemeris is read at a UTC INSTANT, so one offset is not a
# measurement of the field.
_TZ_CORNERS = (-12.0, -8.0, -5.0, 0.0, 5.5, 9.0, 12.0, 14.0)

_PLACE_LAT, _PLACE_LON = 7.0, 80.0


# ---------------------------------------------------------------------------
# The shipped files' real extent, BISECTED here rather than restated
# ---------------------------------------------------------------------------
# A Julian Day literal copied out of a previous measurement is a hand-typed
# number that nothing rechecks; if the pinned data ever moves, it would keep
# certifying the old boundary. These derive it from the files actually present.

def _swiss_at(jd: float, body: int) -> bool:
    utils.restore_ephemeris_state()
    active, _retflag = utils.probe_ephemeris_source(jd, body)
    return active


def _bisect(lo: float, hi: float, body: int, want_lo_swiss: bool) -> float:
    """Refine the boundary between a Swiss-answering JD and a non-Swiss one."""
    assert _swiss_at(lo, body) is want_lo_swiss
    assert _swiss_at(hi, body) is not want_lo_swiss
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if _swiss_at(mid, body) is want_lo_swiss:
            lo = mid
        else:
            hi = mid
        if abs(hi - lo) < 1e-6:
            break
    return lo


@pytest.fixture(scope="module")
def files_span(swiss_ephemeris: int) -> tuple[float, float]:
    """(first, last) Julian Day the shipped Sun/Moon data actually answers."""
    last = _bisect(swe.julday(2400, 1, 9, 0.0), swe.julday(2400, 1, 12, 0.0),
                   swe.SUN, want_lo_swiss=True)
    first = _bisect(swe.julday(1800, 1, 5, 0.0), swe.julday(1799, 12, 1, 0.0),
                    swe.SUN, want_lo_swiss=True)
    assert first < last
    return first, last


# ---------------------------------------------------------------------------
# The instrument
# ---------------------------------------------------------------------------

_records: list[float] = []
_lock = threading.Lock()
_real_calc_ut = swe.calc_ut


def _spy(*args, **kwargs):
    """Records every call's Julian Day, however the call was spelled."""
    jd = args[0] if args else kwargs["jd"]
    values, retflag = _real_calc_ut(*args, **kwargs)
    with _lock:
        _records.append(jd)
    return values, retflag


def test_the_spy_sees_both_call_spellings(swiss_ephemeris: int) -> None:
    """A zero in the tests below must mean absence, not a blind probe.

    pyjhora calls ``swe.calc_ut`` positionally in some places and with
    ``flags=`` in others. A spy with a fixed positional signature raises
    TypeError on the keyword form; the predecessor of this instrument survived
    that only because its parameter happened to be spelled ``flags``.
    """
    global _records
    with _lock:
        _records = []
    _spy(swe.julday(2300, 1, 1, 12.0), swe.SUN, utils.POSITION_FLAGS)
    _spy(swe.julday(2300, 1, 1, 12.0), swe.MOON, flags=utils.POSITION_FLAGS)
    with _lock:
        seen = len(_records)
    assert seen == 2, (
        f"the spy recorded {seen} of 2 call spellings. Every reach count in this "
        "module is measured through it, so a blind spelling makes those counts "
        "silently understate the reach."
    )


def _jds_touched(day: datetime.date, tz: float) -> list[float]:
    """Every Julian Day one scanned day's compute reads."""
    global _records
    place = drik.Place("probe", _PLACE_LAT, _PLACE_LON, tz)
    utils.restore_ephemeris_state()
    with _lock:
        _records = []
    swe.calc_ut = _spy
    try:
        muhurat.compute_muhurat_for_day(place, day)
    finally:
        swe.calc_ut = _real_calc_ut
    with _lock:
        seen = list(_records)
    assert seen, "no swe.calc_ut call was observed — the spy did not take effect"
    return seen


# ---------------------------------------------------------------------------
# The bound the service ADVERTISES, discovered rather than restated
# ---------------------------------------------------------------------------

def _scan_field_accepts(day: datetime.date) -> bool:
    """Does the muhurat request model accept *day* as a scanned day?"""
    body = {**SAMPLE_A, "start_date": day.isoformat(), "end_date": day.isoformat()}
    try:
        MuhurtRequest(**body)
    except Exception:  # noqa: BLE001 - any refusal is a refusal
        return False
    return True


@pytest.fixture(scope="module")
def advertised_scan_bounds() -> tuple[datetime.date, datetime.date]:
    """The (first, last) scanned day the schema actually accepts.

    Discovered by asking the validator, never read from a constant, so this
    module measures the served contract rather than agreeing with it by
    construction.
    """
    last = MAX_EPHEMERIS_DATE
    for _ in range(400):
        if _scan_field_accepts(last):
            break
        last -= _ONE_DAY
    else:  # pragma: no cover - would mean the field refuses a 400-day window
        pytest.fail("no accepted scanned day found below MAX_EPHEMERIS_DATE")

    first = MIN_EPHEMERIS_DATE
    for _ in range(3000):
        if _scan_field_accepts(first):
            break
        first += _ONE_DAY
    else:  # pragma: no cover
        pytest.fail("no accepted scanned day found above MIN_EPHEMERIS_DATE")
    assert first < last
    return first, last


# ---------------------------------------------------------------------------
# THE PROPERTY: an accepted scanned day never reads past the end of the data
# ---------------------------------------------------------------------------

def test_a_scan_at_the_upper_bound_never_reads_past_the_shipped_files(
    swiss_ephemeris: int,
    files_span: tuple[float, float],
    advertised_scan_bounds: tuple[datetime.date, datetime.date],
) -> None:
    """The upper bound must clear the end of the data by the scan's own reach.

    This is the whole point of a separate scanned-day bound. A day lookup that
    reaches +31.8 d forward cannot be bounded by the same date as a point
    lookup: at ``MAX_EPHEMERIS_DATE`` the lunar-month and yoga searches run off
    the end of the files, swisseph answers them from Moshier and KEEPS that
    fallback, and the rest of the day's limbs — reading Julian Days the files DO
    cover — answer analytically too.
    """
    _first_jd, last_jd = files_span
    _first_day, last_day = advertised_scan_bounds

    failures: list[str] = []
    for offset in (0, 1, 2, 3, 5, 8, 13, 21):
        day = last_day - datetime.timedelta(days=offset)
        for tz in _TZ_CORNERS:
            past = [jd for jd in _jds_touched(day, tz) if jd > last_jd]
            if past:
                overshoot = max(past) - last_jd
                failures.append(
                    f"{day} (bound-{offset}d) tz={tz:+g}: {len(past)} calls past "
                    f"the end of the data, furthest by {overshoot:.3f} d"
                )
    assert not failures, (
        "an ACCEPTED scanned day read past the end of the shipped Swiss files:\n"
        + "\n".join(f"  - {f}" for f in failures)
        + "\n\nEvery such read is answered from the Moshier fallback, and swisseph "
        "keeps that fallback for the in-span lookups that follow. Narrow the "
        "scanned-day upper bound; do not relax this test."
    )


def test_a_scan_at_the_upper_bound_loses_no_accuracy_to_the_fallback(
    swiss_ephemeris: int,
    files_span: tuple[float, float],
    advertised_scan_bounds: tuple[datetime.date, datetime.date],
) -> None:
    """The consequence of the property above, asserted directly.

    ``in-span fallback`` is the count that means accuracy was LOST: a call at a
    Julian Day the files DO cover that nonetheless answered from Moshier. A
    Moshier answer outside the files is not a defect — there is nothing else to
    answer with — so this counts only the calls that had data available and did
    not use it.
    """
    global _records
    first_jd, last_jd = files_span
    _first_day, last_day = advertised_scan_bounds

    failures: list[str] = []
    for offset in (0, 1, 2, 3, 5, 8, 13, 21):
        day = last_day - datetime.timedelta(days=offset)
        for tz in _TZ_CORNERS:
            place = drik.Place("probe", _PLACE_LAT, _PLACE_LON, tz)
            utils.restore_ephemeris_state()
            with _lock:
                _records = []
            observed: list[tuple[float, int]] = []
            real = swe.calc_ut

            def spy(*args, **kwargs):
                jd = args[0] if args else kwargs["jd"]
                values, retflag = real(*args, **kwargs)
                observed.append((jd, retflag))
                return values, retflag

            swe.calc_ut = spy
            try:
                muhurat.compute_muhurat_for_day(place, day)
            finally:
                swe.calc_ut = real
            assert observed, "the spy did not take effect"
            in_span = [
                jd for jd, rf in observed
                if (rf & swe.FLG_MOSEPH) and first_jd <= jd <= last_jd
            ]
            if in_span:
                failures.append(
                    f"{day} (bound-{offset}d) tz={tz:+g}: {len(in_span)} of "
                    f"{len(observed)} calls answered from MOSHIER at a Julian Day "
                    "the shipped files DO cover"
                )
    assert not failures, (
        "an ACCEPTED scanned day lost accuracy to the Moshier fallback on a "
        "Julian Day the shipped files cover:\n"
        + "\n".join(f"  - {f}" for f in failures)
        + "\n\nThis is the served-accuracy consequence of the reach test above."
    )


def test_the_upper_bound_is_tight_not_merely_safe(
    swiss_ephemeris: int,
    files_span: tuple[float, float],
    advertised_scan_bounds: tuple[datetime.date, datetime.date],
) -> None:
    """A bound narrowed to any small interval would satisfy the tests above.

    Two independent floors, so neither a runaway narrowing nor a silently
    widened data set passes: the accepted upper bound must sit within a bounded
    distance of the point-lookup bound, and a scanned day above it must
    demonstrably read past the files — otherwise the narrowing bought nothing.
    """
    _first_jd, last_jd = files_span
    _first_day, last_day = advertised_scan_bounds

    gap = (MAX_EPHEMERIS_DATE - last_day).days
    assert 0 < gap <= 60, (
        f"the scanned-day upper bound ({last_day}) sits {gap} days below "
        f"MAX_EPHEMERIS_DATE ({MAX_EPHEMERIS_DATE}). The measured forward reach "
        "of a scanned day is ~31.8 d, so a gap of zero cannot be right and a gap "
        "of months is needlessly narrow — re-measure before moving it."
    )

    leaked = False
    for tz in _TZ_CORNERS:
        if any(jd > last_jd for jd in _jds_touched(MAX_EPHEMERIS_DATE, tz)):
            leaked = True
            break
    assert leaked, (
        f"a scan at MAX_EPHEMERIS_DATE ({MAX_EPHEMERIS_DATE}) no longer reads past "
        "the end of the shipped files at any timezone corner, so the separate, "
        "narrower scanned-day bound is buying nothing. Either the shipped data "
        "now reaches further or the scan's reach shrank — re-measure and widen "
        "the scanned-day bound deliberately."
    )


def test_the_scanned_day_span_sits_inside_the_point_lookup_span() -> None:
    """Structural: the scan span may narrow the ephemeris span, never widen it."""
    from app.schemas import MAX_SCANNED_DATE, MIN_SCANNED_DATE

    assert MIN_EPHEMERIS_DATE <= MIN_SCANNED_DATE, (
        "the scanned-day lower bound is below the span the data covers at all"
    )
    assert MAX_SCANNED_DATE <= MAX_EPHEMERIS_DATE, (
        "the scanned-day upper bound is above the point-lookup bound, which "
        "cannot be right: a scan reads everything a point lookup reads and more"
    )
    assert MIN_SCANNED_DATE < MAX_SCANNED_DATE
