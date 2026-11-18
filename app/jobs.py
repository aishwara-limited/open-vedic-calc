"""In-process async job store for the scan-class electional endpoints (CR-4).

The service runs as a single, GIL-bound worker; a wide date-range scan (up to
``MAX_LAGNA_SHUDDHI_DAYS`` days, both solo and multi-member) can occupy a
request's thread -- and the caller's open HTTP connection -- for the full
scan duration, which starves concurrent interactive chart requests behind
it and risks the caller's own connection/proxy timeout. This module gives
those scan endpoints an ADDITIVE async submit/poll variant: submit hands
back a job id immediately and the scan itself runs on a small dedicated
background thread pool, decoupled from the submitting request's lifecycle,
so the HTTP call that kicks it off returns right away.

This is intentionally the simplest mechanism available that needs no new
infrastructure: an in-memory dict guarded by a lock, plus a stdlib
``ThreadPoolExecutor``. No queue, no Redis, no second process. Job state is
process-local and does not survive a restart -- acceptable here because the
existing synchronous ``/v1/*`` endpoints remain fully intact as the
canonical, durable path; this store only backs the additive async variant.

FR-MED-21: ``submit()`` used to insert into ``self._jobs`` and nothing ever
removed an entry -- ``get()`` only reads. A long-lived container fielding a
steady trickle of scan submissions would grow the dict (and the completed
job's ``result``/``error`` payload it holds) without bound until the process
is OOM-killed. ``JobStore`` is now capped at ``max_jobs`` entries: each
``submit()`` prunes the oldest terminal (``done``/``error``) jobs first, and
falls back to dropping the oldest entry outright if the cap is still
exceeded (which only happens if more jobs are in flight than the cap allows,
an already-pathological case for a 4-worker pool). Both endpoints are
authenticated (trusted caller), so this is a memory-hygiene bound, not an
abuse control.

DESIGN NOTE: This module solves the caller-connection-timeout problem for
long-running scans but does NOT eliminate GIL contention between CPU-bound
scans and sync handlers. The full accepted trade-off rationale (what it solves,
residual contention behavior, why it is acceptable, and when the decision would
reverse) is recorded in CLAUDE.md → "Async scanning design".
"""
from __future__ import annotations

import os
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

JobStatus = Literal["pending", "running", "done", "error"]

# Upper bound on how many jobs (any status) the store retains at once. Sized
# generously above realistic in-flight/recently-polled job counts for a
# 4-worker pool -- this is a memory-hygiene ceiling, not a throughput knob.
DEFAULT_MAX_JOBS = int(os.environ.get("JOB_STORE_MAX_JOBS", "1000"))


@dataclass
class Job:
    id: str
    # Which scan this job runs, as named by the route that submitted it. The
    # store is shared by scans whose results have different shapes, and a job's
    # result is only meaningful to the poll route of its own kind.
    kind: str
    status: JobStatus = "pending"
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class JobStore:
    """Thread-safe in-memory job registry with its own small worker pool.

    The pool is deliberately separate from FastAPI/Starlette's own request
    thread pool: a burst of scan submissions must not be able to exhaust the
    threads that serve ordinary request handling. ``max_workers`` is small
    on purpose -- these are CPU-bound scans on a GIL-bound process, so
    running many of them "concurrently" would not add real throughput, only
    contention; a small bound simply lets a handful of scans queue and run
    to completion without blocking submission of new jobs or polling of
    existing ones (both of which only touch the lock-protected dict).

    ``max_jobs`` bounds the dict itself (FR-MED-21): without it, a
    long-lived container fielding a steady stream of submissions grows
    ``self._jobs`` -- and every completed job's retained result/error --
    without bound, since nothing ever removed a completed entry.
    """

    def __init__(self, max_workers: int = 4, max_jobs: int = DEFAULT_MAX_JOBS) -> None:
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()
        self._max_jobs = max_jobs
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="calc-scan-job"
        )

    def _evict_over_capacity_locked(self) -> None:
        """Bound ``self._jobs`` to ``max_jobs``. Caller must hold ``self._lock``.

        Oldest terminal (``done``/``error``) jobs are dropped first, since
        those are the ones nothing needs any more -- a caller that hasn't
        polled a finished job yet is not this store's problem to hold onto
        indefinitely. If the store is still over capacity after that pass
        (only possible if more jobs are simultaneously pending/running than
        the cap allows), the oldest entries are dropped regardless: the
        bound must never be exceeded, and a dropped pending/running job just
        means a subsequent poll sees 404 (unknown job) instead of its status
        -- acceptable for this additive convenience path (see module
        docstring), not acceptable for the dict to grow forever.
        """
        if len(self._jobs) <= self._max_jobs:
            return
        for job_id, job in list(self._jobs.items()):
            if len(self._jobs) <= self._max_jobs:
                return
            if job.status in ("done", "error"):
                del self._jobs[job_id]
        while len(self._jobs) > self._max_jobs:
            self._jobs.popitem(last=False)

    def submit(self, fn: Callable[[], Any], *, kind: str) -> str:
        """Register a new job and hand its execution to the background pool.

        Returns the job id immediately; ``fn`` has not necessarily started
        running yet by the time this call returns (it may still be queued
        behind other jobs in the pool) -- that is the point: submission is
        O(1) and never waits on the scan itself.

        ``kind`` names the scan and is required: ``get`` hands a job back only
        to a caller asking for that kind.
        """
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, kind=kind)
        with self._lock:
            self._jobs[job_id] = job
            self._evict_over_capacity_locked()

        def _run() -> None:
            with self._lock:
                job.status = "running"
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - reported via poll, never re-raised
                with self._lock:
                    job.status = "error"
                    job.error = str(exc)
                return
            with self._lock:
                job.status = "done"
                job.result = result

        self._executor.submit(_run)
        return job_id

    def get(self, job_id: str, *, kind: str) -> Job | None:
        """Return a point-in-time snapshot of the job, or None if unknown.

        A job of another ``kind`` is unknown to this caller, in every state it
        can be in. Each poll route has its own response model; a finished job
        looked up by id alone and handed to the other route's model failed
        response validation and surfaced as a 500, while the same request
        answered 200 for as long as the job was still running.

        A copy is returned (rather than the live object) so a caller can
        never observe or mutate a torn/partial write from the worker thread.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.kind != kind:
                return None
            return Job(
                id=job.id,
                kind=job.kind,
                status=job.status,
                result=job.result,
                error=job.error,
                created_at=job.created_at,
            )


# Process-wide singleton. Job state is intentionally process-local (see the
# module docstring); this is acceptable because the synchronous /v1/*
# endpoints remain the durable, canonical computation path -- this store
# only ever backs the additive async convenience variant.
job_store = JobStore()
