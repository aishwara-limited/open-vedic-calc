"""A scan job is polled on the route of its own kind, or it is not found.

THE DEFECT THIS CLOSED
----------------------
The two async scans share one job store, and each has its own poll route with
its own response model. A poll route looked a job up by id alone, so a finished
family job polled on the single-chart route was handed to the single-chart
response model, failed response validation, and came back as a 500 -- and the
same the other way round. While such a job was still pending the wrong route
answered 200 with its status, so the same request changed from 200 to 500 as
the job completed.

THE RULE
--------
Every job carries the kind it was submitted as, and a poll route asks the store
for a job OF ITS KIND. A job of another kind is unknown to that route: 404, the
same answer as an id that was never issued, in every state the job can be in.

WHAT IS PINNED
--------------
* Through the real submit and poll routes, both directions: a finished job
  answers 200 on its own route and 404 on the other.
* The 404 does not depend on the job's state: pending, running, done or error.
* The store itself: ``submit`` cannot be called without a kind, and ``get``
  returns nothing for a job of another kind.
"""
from __future__ import annotations

import threading
import time as time_mod

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.jobs import JobStore
from app.main import app
from tests.conftest import SAMPLE_A, SAMPLE_B

_SOLO = "/v1/muhurat/lagna-shuddhi"
_FAMILY = "/v1/muhurat/family-lagna-shuddhi"
_SCAN = {
    "start_date": "2026-05-26", "end_date": "2026-05-26",
    "activity_category": "generic", "step_seconds": 3600,
}
_SOLO_REQ = {**SAMPLE_A, **_SCAN}
_FAMILY_REQ = {"members": [SAMPLE_A, SAMPLE_B], **_SCAN}
_NOT_FOUND = {"detail": "Job not found"}


@pytest.fixture(scope="module")
def client():
    """Server exceptions are returned as responses, so a defect reads as the
    500 a caller would see."""
    with TestClient(
        app, headers={"X-Calc-Service-Token": "test"}, raise_server_exceptions=False
    ) as c:
        yield c


def _poll_until_terminal(client, url: str, timeout: float = 60.0) -> dict:
    deadline = time_mod.time() + timeout
    while time_mod.time() < deadline:
        r = client.get(url)
        assert r.status_code == 200, r.text
        if r.json()["status"] in ("done", "error"):
            return r.json()
        time_mod.sleep(0.05)
    raise AssertionError(f"{url} never reached a terminal state")


def _submit(client, route: str, body: dict) -> str:
    r = client.post(f"{route}/async", json=body)
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


# ---------------------------------------------------------------------------
# Finished jobs, through the real routes
# ---------------------------------------------------------------------------

def test_a_finished_family_job_is_not_found_on_the_solo_route(client):
    job_id = _submit(client, _FAMILY, _FAMILY_REQ)
    done = _poll_until_terminal(client, f"{_FAMILY}/jobs/{job_id}")
    assert done["status"] == "done" and done["result"] is not None

    r = client.get(f"{_SOLO}/jobs/{job_id}")
    assert r.status_code == 404, r.text
    assert r.json() == _NOT_FOUND
    # ... and it is still there, intact, on its own route.
    assert client.get(f"{_FAMILY}/jobs/{job_id}").json() == done


def test_a_finished_solo_job_is_not_found_on_the_family_route(client):
    job_id = _submit(client, _SOLO, _SOLO_REQ)
    done = _poll_until_terminal(client, f"{_SOLO}/jobs/{job_id}")
    assert done["status"] == "done" and done["result"] is not None

    r = client.get(f"{_FAMILY}/jobs/{job_id}")
    assert r.status_code == 404, r.text
    assert r.json() == _NOT_FOUND
    assert client.get(f"{_SOLO}/jobs/{job_id}").json() == done


def test_an_id_that_was_never_issued_is_the_same_404_on_both_routes(client):
    for route in (_SOLO, _FAMILY):
        r = client.get(f"{route}/jobs/does-not-exist")
        assert r.status_code == 404
        assert r.json() == _NOT_FOUND


# ---------------------------------------------------------------------------
# The answer does not change as the job moves through its states
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "own,other,own_kind_attr",
    [
        (_SOLO, _FAMILY, "_JOB_KIND_LAGNA_SHUDDHI"),
        (_FAMILY, _SOLO, "_JOB_KIND_FAMILY_LAGNA_SHUDDHI"),
    ],
    ids=["solo-job", "family-job"],
)
def test_the_wrong_route_is_404_while_the_job_is_still_running(
    client, own, other, own_kind_attr
):
    """A job held open on purpose: it is submitted to the real store under the
    kind the real submit route uses, and blocks until released."""
    release = threading.Event()
    started = threading.Event()

    def held_open():
        started.set()
        assert release.wait(timeout=30)
        raise RuntimeError("released")

    job_id = main_mod.job_store.submit(held_open, kind=getattr(main_mod, own_kind_attr))
    try:
        assert started.wait(timeout=30)
        running = client.get(f"{own}/jobs/{job_id}")
        assert running.status_code == 200, running.text
        assert running.json()["status"] == "running"
        wrong = client.get(f"{other}/jobs/{job_id}")
        assert wrong.status_code == 404, wrong.text
        assert wrong.json() == _NOT_FOUND
    finally:
        release.set()

    # Finished in the error state: still its own route's job and nobody else's.
    failed = _poll_until_terminal(client, f"{own}/jobs/{job_id}")
    assert failed["status"] == "error" and failed["error"] == "released"
    wrong = client.get(f"{other}/jobs/{job_id}")
    assert wrong.status_code == 404, wrong.text
    assert wrong.json() == _NOT_FOUND


def test_the_two_routes_use_two_different_kinds():
    assert main_mod._JOB_KIND_LAGNA_SHUDDHI != main_mod._JOB_KIND_FAMILY_LAGNA_SHUDDHI


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def _wait_done(store: JobStore, job_id: str, kind: str) -> None:
    deadline = time_mod.time() + 5.0
    while time_mod.time() < deadline:
        job = store.get(job_id, kind=kind)
        if job is not None and job.status == "done":
            return
        time_mod.sleep(0.01)
    raise AssertionError("job never finished")


def test_the_store_returns_a_job_only_to_its_own_kind():
    store = JobStore(max_workers=1, max_jobs=5)
    job_id = store.submit(lambda: "ok", kind="alpha")
    _wait_done(store, job_id, "alpha")
    job = store.get(job_id, kind="alpha")
    assert job is not None and job.kind == "alpha" and job.result == "ok"
    assert store.get(job_id, kind="beta") is None
    assert store.get(job_id, kind="") is None


def test_a_job_cannot_be_submitted_or_read_without_a_kind():
    store = JobStore(max_workers=1, max_jobs=5)
    with pytest.raises(TypeError):
        store.submit(lambda: "ok")
    job_id = store.submit(lambda: "ok", kind="alpha")
    with pytest.raises(TypeError):
        store.get(job_id)
