"""``utils._ThreadEphemerisFiles``: a thread's data files are closed by that thread only.

The end-to-end consequence (short-lived threads answering exactly like the
main thread once the file limit is tight) is pinned by
tests/test_response_determinism.py::test_short_lived_threads_answer_exactly_like_the_main_thread.
These two pin the mechanism: the closer is registered by the per-thread
initialiser and fires on the owning thread as it ends, and a finalizer that
somehow runs on a different thread refuses to close, because ``swe.close()``
would reset THAT thread's path and ayanamsa instead.
"""
from __future__ import annotations

import logging
import threading

import pytest

from bphs_core import utils


def test_the_owning_thread_closes_its_files_when_it_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_on: list[int] = []
    monkeypatch.setattr(
        utils._ThreadEphemerisFiles, "_close",
        staticmethod(lambda: closed_on.append(threading.get_ident())),
    )
    box: dict[str, int] = {}

    def target() -> None:
        utils.probe_ephemeris_source()  # a serialized entry point initialises the thread
        box["ident"] = threading.get_ident()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    assert closed_on.count(box["ident"]) == 1, (
        f"the thread that computed ({box['ident']}) ended without closing its "
        f"Swiss Ephemeris files (closes seen on: {closed_on})"
    )


def test_a_finalizer_on_another_thread_refuses_to_close(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        utils._ThreadEphemerisFiles, "_close", staticmethod(lambda: calls.append(1)),
    )
    box: dict[str, object] = {}
    thread = threading.Thread(target=lambda: box.update(files=utils._ThreadEphemerisFiles()))
    thread.start()
    thread.join()
    with caplog.at_level(logging.WARNING, logger="bphs_core.utils"):
        del box["files"]  # the last reference goes here, on this test's thread
    assert calls == []
    assert "ephemeris_files_not_closed" in caplog.text
