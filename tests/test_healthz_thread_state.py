"""``/healthz`` and ``/source`` must answer correctly on a thread that never computed.

pyswisseph keeps the ephemeris path and the sidereal mode per THREAD (see the
rationale above ``_THREAD_EPHEMERIS_STATE`` in ``bphs_core/utils.py``). A
thread that has not applied that state silently computes on the built-in
Moshier fallback. If the health probe ran on such a thread while the
calculation routes ran on configured ones, ``/healthz`` would report
``degraded`` / ``ephe_loaded: false`` while every served chart was correctly
Swiss-backed — a false alarm that a deploy gate would act on.

That cannot happen today, because ``utils.probe_ephemeris_source`` carries
``@utils.serialized_ephemeris`` and so applies the calling thread's state
itself. Measured at this module's base commit, with the Swiss data files
present: the probe on a brand-new ``threading.Thread`` returned retflag 65602
(FLG_SWIEPH) for both the Sun and the Moon, and 400 concurrent ``/healthz``
requests against a real ``uvicorn`` process, interleaved with chart and
muhurat requests, reported ``ephe_loaded: false`` zero times.

What was missing is a test that drives the REAL probe through the REAL route
handlers on an uninitialised thread. Every ``/healthz`` test in
``tests/test_ephemeris_baked.py`` patches the probe out (deliberately — it
pins the status/flag mapping), and the per-thread tests in
``tests/test_swiss_ephemeris.py`` exercise a decorated helper of their own,
not the probe. So nothing here would notice the health path losing the
per-thread initialisation the calculation path keeps. This module pins that.

Every test first asserts that its thread is genuinely uninitialised, because a
"fresh thread" that had already applied the state would make every assertion
below pass whatever the probe does.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import swisseph as swe

from app import main
from bphs_core import utils


def _thread_is_initialised() -> bool:
    return bool(getattr(utils._THREAD_EPHEMERIS_STATE, "initialised", False))


def _on_fresh_thread(fn: Callable[[], Any]) -> tuple[bool, Any]:
    """Run ``fn`` on a brand-new ``threading.Thread``.

    Returns whether the thread had applied ephemeris state BEFORE ``fn`` ran,
    and what ``fn`` returned.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["before"] = _thread_is_initialised()
            box["result"] = fn()
        except BaseException as exc:  # re-raised on the calling thread
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["before"], box["result"]


def _on_unused_pool_worker(fn: Callable[[], Any]) -> tuple[bool, Any]:
    """Run ``fn`` as the FIRST task of a thread-pool worker.

    This is the shape of a request-pool worker whose first request is the
    health probe: it has served no calculation, so nothing has configured it.
    """
    def task() -> tuple[bool, Any]:
        return _thread_is_initialised(), fn()

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(task).result()


_RUNNERS = {
    "fresh_thread": _on_fresh_thread,
    "unused_pool_worker": _on_unused_pool_worker,
}


@utils.serialized_ephemeris
def _calculation_retflag() -> int:
    """The retflag a calculation-path entry point gets on the calling thread."""
    jd = swe.julday(2000, 1, 1, 12.0)
    _values, retflag = swe.calc_ut(jd, swe.SUN, swe.FLG_SWIEPH | swe.FLG_SIDEREAL)
    return int(retflag)


def _calculation_is_swiss() -> bool:
    retflag = _calculation_retflag()
    return bool(retflag & swe.FLG_SWIEPH) and not bool(retflag & swe.FLG_MOSEPH)


def _assert_uninitialised(before: bool) -> None:
    assert before is False, (
        "the test thread had already applied ephemeris state before the probe "
        "ran, so this test cannot tell a correct probe from one that skips the "
        "per-thread initialisation"
    )


@pytest.mark.parametrize("runner", sorted(_RUNNERS))
def test_healthz_on_an_uninitialised_thread_agrees_with_the_calculation_path(
    runner: str,
) -> None:
    """Both runtimes: the health signal follows what a calculation would use.

    A RELATIONSHIP, not a constant, so it holds with or without the data files:
    with them, both sides must say Swiss; without them, both must say fallback.
    """
    before, body = _RUNNERS[runner](main.healthz)
    _assert_uninitialised(before)

    calc_before, calculation_is_swiss = _RUNNERS[runner](_calculation_is_swiss)
    _assert_uninitialised(calc_before)
    assert body["ephe_loaded"] is calculation_is_swiss, (
        f"/healthz on an uninitialised {runner} reported ephe_loaded="
        f"{body['ephe_loaded']!r} while a calculation-path entry point on the "
        f"same kind of thread computed with swiss={calculation_is_swiss!r} — the "
        "health probe and the calculation path disagree about the ephemeris"
    )
    assert body["status"] == ("ok" if calculation_is_swiss else "degraded")


@pytest.mark.parametrize("runner", sorted(_RUNNERS))
def test_healthz_on_an_uninitialised_thread_reports_swiss_data(
    runner: str, swiss_ephemeris: int
) -> None:
    """With the data present, a never-used thread must not report ``degraded``."""
    before, body = _RUNNERS[runner](main.healthz)
    _assert_uninitialised(before)
    assert body == {"status": "ok", "ephe_loaded": True}, (
        f"/healthz on an uninitialised {runner} answered {body!r} while the "
        "Swiss data files are present and in use — the probe ran on the Moshier "
        "fallback because it did not apply the thread's ephemeris state"
    )


@pytest.mark.parametrize("runner", sorted(_RUNNERS))
def test_source_on_an_uninitialised_thread_reports_swiss_data(
    runner: str, swiss_ephemeris: int
) -> None:
    """``/source`` carries the same signal for deploy gates, so pin it the same way."""
    before, info = _RUNNERS[runner](main.source)
    _assert_uninitialised(before)
    assert info.ephe_loaded is True
    assert info.ephemeris_source == "swiss", (
        f"/source on an uninitialised {runner} reported "
        f"ephemeris_source={info.ephemeris_source!r} while the Swiss data files "
        "are present and in use"
    )


def test_the_probe_initialises_the_thread_it_runs_on() -> None:
    """Mechanism: the probe itself must leave its thread configured.

    Guards the cause rather than the symptom, under both runtimes: a probe that
    stopped applying the per-thread state would leave the flag unset here even
    when the data files are absent and every value above happens to agree.
    """
    def probe_then_read_flag() -> bool:
        utils.probe_ephemeris_source()
        return _thread_is_initialised()

    before, after = _on_fresh_thread(probe_then_read_flag)
    _assert_uninitialised(before)
    assert after is True, (
        "probe_ephemeris_source ran on a fresh thread without applying that "
        "thread's ephemeris path and ayanamsa"
    )
