"""FR-MED-21 — the async JobStore must not grow without bound.

``submit()`` used to insert into ``self._jobs`` and nothing ever removed an
entry (``get()`` only reads), so a long-lived container fielding a steady
trickle of scan submissions would grow the dict -- and every completed job's
retained result/error payload -- forever, eventually OOM-killing the process.
``JobStore`` now caps itself at ``max_jobs`` entries, evicting the oldest
terminal (``done``/``error``) jobs first once the cap is exceeded.
"""
import importlib
import time as time_mod

from app.jobs import JobStore

# Every job carries a kind (tests/test_scan_job_kind.py); one is enough here.
_KIND = "scan"


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.01) -> bool:
    deadline = time_mod.time() + timeout
    while time_mod.time() < deadline:
        if predicate():
            return True
        time_mod.sleep(interval)
    return False


def test_job_store_never_exceeds_cap_after_many_submissions():
    """Submitting far more jobs than the cap must leave the dict bounded."""
    store = JobStore(max_workers=2, max_jobs=5)
    job_ids = [store.submit(lambda: "ok", kind=_KIND) for _ in range(50)]

    def _all_terminal() -> bool:
        return all(
            (job := store.get(jid, kind=_KIND)) is None or job.status in ("done", "error")
            for jid in job_ids
        )

    assert _wait_until(_all_terminal), "jobs never reached a terminal state"
    assert len(store._jobs) <= 5, (
        f"job store grew past its cap: {len(store._jobs)} entries retained"
    )


def test_job_store_evicts_oldest_terminal_job_first():
    """Once at capacity, the newest submission evicts the oldest *completed*
    entry, not an arbitrary one -- an LRU-style bound, not random pruning."""
    store = JobStore(max_workers=1, max_jobs=3)
    ids = [store.submit(lambda: "ok", kind=_KIND) for _ in range(3)]
    assert _wait_until(lambda: all(store.get(i, kind=_KIND).status == "done" for i in ids))
    assert len(store._jobs) == 3

    newest = store.submit(lambda: "ok", kind=_KIND)
    assert _wait_until(lambda: (j := store.get(newest, kind=_KIND)) is not None and j.status == "done")

    assert len(store._jobs) <= 3
    assert store.get(ids[0], kind=_KIND) is None, "oldest completed job should have been evicted"
    assert store.get(newest, kind=_KIND) is not None, "the job that triggered eviction must survive"


def test_job_store_reports_error_jobs_as_evictable_too():
    """A job that raised is still a terminal state and must be evictable,
    not pinned forever because it errored rather than succeeded."""
    store = JobStore(max_workers=1, max_jobs=2)

    def _boom():
        raise RuntimeError("synthetic failure")

    err_id = store.submit(_boom, kind=_KIND)
    assert _wait_until(lambda: store.get(err_id, kind=_KIND).status == "error")

    ok_id_1 = store.submit(lambda: "ok", kind=_KIND)
    ok_id_2 = store.submit(lambda: "ok", kind=_KIND)
    assert _wait_until(lambda: all(store.get(i, kind=_KIND).status == "done" for i in (ok_id_1, ok_id_2)))

    assert len(store._jobs) <= 2
    assert store.get(err_id, kind=_KIND) is None, "the errored job should have been evicted as terminal"


def test_job_store_get_returns_none_for_unknown_id():
    store = JobStore(max_workers=1, max_jobs=5)
    assert store.get("does-not-exist", kind=_KIND) is None


def test_default_max_jobs_reads_env_override(monkeypatch):
    monkeypatch.setenv("JOB_STORE_MAX_JOBS", "42")
    from app import jobs as jobs_mod
    reloaded = importlib.reload(jobs_mod)
    try:
        assert reloaded.DEFAULT_MAX_JOBS == 42
    finally:
        monkeypatch.delenv("JOB_STORE_MAX_JOBS", raising=False)
        importlib.reload(jobs_mod)
