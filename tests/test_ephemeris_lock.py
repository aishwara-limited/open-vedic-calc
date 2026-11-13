"""Process-wide serialization of Swiss-Ephemeris / pyjhora C-library access.

pyswisseph's ephemeris path and sidereal/ayanamsa mode are THREAD-local
(pyswisseph >= 2.10's thread-local ``swed`` struct — see
``bphs_core/utils.py``), not process-global: every thread must apply them
itself before it computes anything, or it silently runs on the Moshier
fallback with the default Fagan/Bradley ayanamsa (~0.88 deg / 53 arcmin off
Lahiri) instead of raising. ``_ensure_thread_ephemeris_state()`` does that,
and ``serialized_ephemeris`` calls it on every invocation of every
C-library entry point, so the guarantee is structural rather than
remembered.

EPHEMERIS_LOCK exists on top of that for a separate reason: the underlying
Swiss Ephemeris C library is not documented as safe for concurrent
``swe_calc``/``swe_houses`` calls from multiple threads, even once each
thread's own state is correctly configured. Two compute paths run
concurrently in one process: Starlette's per-request thread pool for the
synchronous ``/v1/*`` handlers, and the background scan-job pool in
``app/jobs.py``. Without synchronization the failure mode is not a crash
but a silently wrong chart for one of two concurrent requests — invisible,
and the worst possible defect for a determinism-first engine.

These tests pin the fix: a single process-wide re-entrant lock
(``bphs_core.utils.EPHEMERIS_LOCK``) that every C-library entry point holds
for the duration of its computation, which also guarantees the per-thread
state above is applied before that entry point's body runs.
"""
from __future__ import annotations

import threading
import time as time_mod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time

from bphs_core import lagna_shuddhi, muhurat, profile, transits, utils
from bphs_core.chart import Chart, PersonalData

# Synthetic sample data (mirrors tests/conftest.py — no real personal data).
_PERSON_A = PersonalData(
    name="sample_a",
    birth_date=datetime(1950, 6, 15),
    birth_time=time(6, 0),
    birth_place="Sample City",
    latitude=7.0,
    longitude=80.0,
    timezone_offset_hours=5.5,
)

_PERSON_B = PersonalData(
    name="sample_b",
    birth_date=datetime(1975, 12, 1),
    birth_time=time(12, 30),
    birth_place="Sample City",
    latitude=6.9,
    longitude=79.8,
    timezone_offset_hours=5.5,
)


def test_ephemeris_lock_exists_and_is_reentrant():
    """The lock must be re-entrant: an outer entry point (e.g. a family scan)
    may build member Charts, each of which re-acquires the same lock on the
    same thread."""
    lock = utils.EPHEMERIS_LOCK
    acquired_outer = lock.acquire(timeout=1)
    assert acquired_outer
    try:
        acquired_inner = lock.acquire(timeout=1)
        assert acquired_inner, "EPHEMERIS_LOCK must be an RLock (re-entrant)"
        lock.release()
    finally:
        lock.release()


def test_every_c_library_entry_point_is_serialized():
    """Each INNER compute path that enters pyswisseph/pyjhora carries the
    ``_holds_ephemeris_lock`` marker set by the ``serialized_ephemeris``
    decorator. The lock is held at inner (millisecond-bounded) granularity —
    one chart, one day, one instant, one JD conversion — never across a whole
    scan, so interactive routes and async submits stay responsive while a
    scan runs. This list pins the currently-known entry points; the standing
    convention for NEW paths lives in CLAUDE.md (Engine conventions)."""
    entry_points = [
        Chart._compute,
        muhurat.compute_muhurat_for_day,
        # The tithi/karana/yoga at each candidate instant -- both of its Sun
        # and Moon reads under one hold.
        muhurat.panchanga_at_instant,
        lagna_shuddhi._jd_for_local,
        lagna_shuddhi.compute_lagna_at_jd,
        lagna_shuddhi._score_instant,
        transits.get_current_transits,
        transits.get_sade_sati_info,
        # Reached UNDECORATED from profile.sade_sati_lifetime's quarterly
        # sweep (the sync /v1/profile route) — must hold the lock per call.
        transits._transit_longitude,
        transits._jd_from_date,
        # The graha-name -> swisseph-body boundary: every per-body position
        # in the electional/transit paths now routes through this single
        # entry point (see the id-space rationale in bphs_core/utils.py).
        utils.graha_sidereal_longitude,
        # /healthz's Swiss/Moshier probe (CALC-1) -- called directly by the
        # route handler, not nested inside another decorated entry point.
        utils.probe_ephemeris_source,
    ]
    for fn in entry_points:
        assert getattr(fn, "_holds_ephemeris_lock", False), (
            f"{fn.__qualname__} enters the C library but does not hold "
            "EPHEMERIS_LOCK (missing @serialized_ephemeris)"
        )


def test_scan_entry_points_are_not_serialized_wholesale():
    """The OUTER scan functions must NOT hold EPHEMERIS_LOCK for their full
    duration: a whole-scan hold (seconds to minutes at the API's range caps)
    would block every interactive chart route AND the async submit path
    (which builds a natal chart at submit time) for the scan's remaining
    duration — reversing the accepted async-scan design's "submissions never
    wait on scan compute" property. Scans serialize through their inner
    per-instant entry points instead."""
    for fn in (
        lagna_shuddhi.scan_lagna_shuddhi,
        lagna_shuddhi.scan_family_lagna_shuddhi,
        # The ~320-step quarterly lifetime sweep behind /v1/profile: the
        # profile route must acquire only per-call bounded holds.
        profile.sade_sati_lifetime,
        profile.compute_profile,
    ):
        assert not getattr(fn, "_holds_ephemeris_lock", False), (
            f"{fn.__qualname__} must not hold EPHEMERIS_LOCK for the whole "
            "scan — serialize the inner entry points it calls instead"
        )


def test_long_scan_does_not_block_concurrent_chart_compute():
    """Behavioural proof of the granularity: while a multi-second scan runs
    on a background thread, a concurrent Chart build (the same lock use as an
    async submit's natal-Moon extraction) completes in bounded time by
    interleaving between the scan's millisecond lock holds — it does not wait
    for the scan to finish."""
    # Warm-up so imports/ephemeris init don't inflate the timing below.
    Chart(_PERSON_A)

    scan_started = threading.Event()
    scan_finished_at: dict[str, float] = {}

    def _run_scan() -> None:
        scan_started.set()
        lagna_shuddhi.scan_lagna_shuddhi(
            lat=7.0,
            lon=80.0,
            tz_offset=5.5,
            birth_nakshatra="Ashwini",
            birth_moon_sign="Aries",
            start_date="2026-06-01",
            end_date="2026-06-12",
            activity="generic",
            step_seconds=600,
        )
        scan_finished_at["t"] = time_mod.monotonic()

    t = threading.Thread(target=_run_scan, daemon=True)
    t.start()
    assert scan_started.wait(5)
    time_mod.sleep(0.1)  # let the scan get into its sampling loop

    t0 = time_mod.monotonic()
    Chart(_PERSON_B)
    chart_done_at = time_mod.monotonic()
    chart_elapsed = chart_done_at - t0

    t.join(timeout=120)
    assert "t" in scan_finished_at, "scan never finished"

    # The scan (~3 s at 12 days / 600 s steps) must still have been
    # running when the chart completed — i.e. the chart interleaved with it.
    assert scan_finished_at["t"] > chart_done_at, (
        "scan finished before the concurrent chart — timing assertion vacuous; "
        "increase the scan range"
    )
    # A warm chart is ~ms; anything approaching the scan's duration means the
    # chart waited for the whole scan (whole-scan lock hold).
    assert chart_elapsed < 1.5, (
        f"concurrent Chart build took {chart_elapsed:.2f}s while a scan was "
        "running — the scan is holding EPHEMERIS_LOCK for its full duration"
    )


def test_chart_compute_actually_blocks_on_the_lock():
    """Behavioural proof the marker means something: while another thread
    holds EPHEMERIS_LOCK, constructing a Chart must block until release."""
    # Warm-up so imports/ephemeris init don't inflate the timing below.
    Chart(_PERSON_A)

    entered = threading.Event()
    finished = threading.Event()

    def _compute_in_thread() -> None:
        entered.set()
        Chart(_PERSON_B)
        finished.set()

    with utils.EPHEMERIS_LOCK:
        t = threading.Thread(target=_compute_in_thread, daemon=True)
        t.start()
        assert entered.wait(5)
        # A warm Chart computes in well under this window; if the thread
        # finishes while we still hold the lock, _compute never acquired it.
        assert not finished.wait(2.0), (
            "Chart._compute completed while another thread held "
            "EPHEMERIS_LOCK — the compute path is not serialized"
        )
    assert finished.wait(30), "Chart._compute never completed after release"
    t.join(timeout=30)


def test_concurrent_charts_match_serial_reference():
    """Determinism regression: N concurrent chart computations for two
    different people must each equal their single-threaded reference."""
    ref_a = Chart(_PERSON_A).snapshot()
    ref_b = Chart(_PERSON_B).snapshot()

    def _one(person: PersonalData):
        return Chart(person).snapshot()

    people = [_PERSON_A, _PERSON_B] * 4
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_one, people))

    for person, snap in zip(people, results):
        ref = ref_a if person is _PERSON_A else ref_b
        assert snap.rasi_chart == ref.rasi_chart, (
            f"concurrent chart for {person.name} diverged from its serial reference"
        )
