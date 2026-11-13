"""The same request must return byte-identical data from any process, on any thread.

Two separate defects broke that, and each is pinned here through the real
route handlers, in a fresh child process, because neither can be seen from
inside one long-lived test process.

1. A thread's Swiss Ephemeris data files were never closed when the thread
   ended. pyswisseph keeps its open data files in THREAD-local state, and
   nothing closed them at thread exit, so every worker thread that computed and
   then ended (the request pool retires idle workers) leaked its file handles.
   Once the process ran out, every NEW thread failed to open the data files and
   swisseph silently answered from its built-in Moshier fallback - no error,
   plausible numbers, a different answer. Measured on the base commit, Windows,
   default C-runtime stream limit (512): one fresh thread after another, each
   probing the Moon and the Sun, the first 254 threads read the Swiss files
   (retflag 65602) and every thread from the 255th on read Moshier (65604), 746
   of 1000. The fix is ``bphs_core.utils._ThreadEphemerisFiles``: the thread
   that initialised the ephemeris state closes its own files when it ends.

   The child lowers its open-file limit so a handful of thread lifetimes is
   enough to exhaust it (``_setmaxstdio`` on Windows, ``RLIMIT_NOFILE`` on
   POSIX), takes reference answers on its main thread, then runs the same
   requests again on short-lived threads, several at once and each wave in a
   different order, and reports every answer that differs. Under the fallback
   engine (no data files) nothing is opened, so the comparison holds trivially
   there; the ``swiss-ephemeris`` CI job is where it bites, and the test refuses
   to pass vacuously in that job.

2. The Parivartana Yoga description and the order of its entries depended on
   ``PYTHONHASHSEED``: the detector iterated a ``set`` of graha names, whose
   order changes from one interpreter start to the next. Each child process
   here starts with a different hash seed and answers the same requests on
   every route; every response body must hash the same.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import swiss_ephemeris_required

_REPO = Path(__file__).resolve().parents[1]

# Synthetic people only. ``_EXCHANGES`` was chosen because its chart carries TWO
# Parivartana exchanges (Mercury/Jupiter and Venus/Saturn), so both the wording
# of an entry and the order of the entries are exercised.
_A = {"name": "a", "birth_date": "1961-01-30", "birth_time": "06:00:00",
      "birth_place": "x", "latitude": 7.0, "longitude": 80.0,
      "timezone_offset_hours": 5.5}
_B = {"name": "b", "birth_date": "1975-12-01", "birth_time": "12:30:00",
      "birth_place": "x", "latitude": 51.5, "longitude": -0.1,
      "timezone_offset_hours": 0.0}
_C = {"name": "c", "birth_date": "1990-01-14", "birth_time": "23:10:00",
      "birth_place": "x", "latitude": -33.9, "longitude": 151.2,
      "timezone_offset_hours": 10.0}
_EXCHANGES = {"name": "e", "birth_date": "1955-04-09", "birth_time": "06:00:00",
              "birth_place": "x", "latitude": 7.0, "longitude": 80.0,
              "timezone_offset_hours": 5.5}


def _child_env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"ENVIRONMENT": "test", "CALC_SERVICE_TOKEN": "test",
                "PUBLIC_SOURCE_URL": "https://example.com"})
    env.update(extra)
    return env


def _run_child(code: str, args: list[str], env: dict[str, str]) -> dict | list:
    proc = subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=_REPO, env=env, capture_output=True, timeout=600,
    )
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    lines = [ln for ln in stdout.splitlines() if ln.startswith("RESULT ")]
    assert proc.returncode == 0 and len(lines) == 1, (
        f"child exited {proc.returncode} with {len(lines)} RESULT lines\n"
        f"stdout tail:\n{stdout[-2000:]}\nstderr tail:\n{stderr[-4000:]}"
    )
    return json.loads(lines[0][len("RESULT "):])


# ---------------------------------------------------------------------------
# 1. Thread lifetimes must not change the answer
# ---------------------------------------------------------------------------

_THREAD_CHURN_CHILD = r'''
import json, os, sys, threading
from fastapi.encoders import jsonable_encoder
import swisseph as swe
from app import main as m
from app import schemas as S
from bphs_core import utils

limit, waves, people = int(sys.argv[1]), int(sys.argv[2]), json.loads(sys.argv[3])
A, B, C, E = people
calls = [
    ("chart A", lambda: m.chart_endpoint(S.PersonalDataIn(**A))),
    ("chart B", lambda: m.chart_endpoint(S.PersonalDataIn(**B))),
    ("dashas C", lambda: m.dashas_endpoint(
        S.DashaRequest(**C, from_date="2026-01-01", to_date="2031-01-01"))),
    ("transits B", lambda: m.transits_endpoint(S.TransitRequest(**B, at_date="2026-10-18"))),
    ("yogas E", lambda: m.yogas_endpoint(S.PersonalDataIn(**E))),
]

def answer(fn):
    return json.dumps(jsonable_encoder(fn()), sort_keys=True)

swiss = utils.probe_ephemeris_source(body=swe.MOON)[0] and utils.probe_ephemeris_source()[0]
reference = {name: answer(fn) for name, fn in calls}

if os.name == "nt":
    import ctypes
    crt = ctypes.CDLL("ucrtbase")
    if crt._setmaxstdio(limit) != limit:
        raise SystemExit("could not lower the C runtime stream limit")
else:
    import resource
    fd_dir = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (len(os.listdir(fd_dir)) + limit, hard))

mismatches, errors, ran = [], [], []
lock = threading.Lock()

def run(wave, name, fn):
    try:
        got = answer(fn)
    except BaseException as exc:
        with lock:
            errors.append(f"wave {wave} {name}: {type(exc).__name__}: {exc}")
        return
    with lock:
        ran.append(name)
        if got != reference[name]:
            mismatches.append(f"wave {wave} {name}")

for wave in range(waves):
    k = wave % len(calls)
    threads = [threading.Thread(target=run, args=(wave, name, fn))
               for name, fn in calls[k:] + calls[:k]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

print("RESULT " + json.dumps({"swiss": swiss, "ran": len(ran), "mismatches": mismatches,
                              "errors": errors}))
'''

# Small enough that the leak exhausts it within a few waves (every computing
# thread holds the planet and Moon files open), large enough for the
# interpreter's own needs once the leak is closed.
_STREAM_LIMIT = 64
_WAVES = 30
_CALLS_PER_WAVE = 5


def test_short_lived_threads_answer_exactly_like_the_main_thread() -> None:
    result = _run_child(
        _THREAD_CHURN_CHILD,
        [str(_STREAM_LIMIT), str(_WAVES), json.dumps([_A, _B, _C, _EXCHANGES])],
        _child_env(),
    )
    if swiss_ephemeris_required():
        assert result["swiss"], (
            "REQUIRE_SWISS_EPHEMERIS=1 but the child computed on the fallback engine, "
            "so this comparison would hold trivially and prove nothing"
        )
    assert result["errors"] == [], result["errors"][:5]
    assert result["mismatches"] == [], (
        f"{len(result['mismatches'])} of {result['ran']} answers computed on short-lived "
        "threads differ from the same request answered on the main thread "
        f"(first: {result['mismatches'][:5]}). A thread that ends without closing its "
        "Swiss Ephemeris files leaks them; once the process runs out, new threads "
        "silently compute on the Moshier fallback."
    )
    assert result["ran"] == _WAVES * _CALLS_PER_WAVE


# ---------------------------------------------------------------------------
# 2. The interpreter's hash seed must not change the answer
# ---------------------------------------------------------------------------

_SEED_CHILD = r'''
import hashlib, json, sys
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})
out = []
for path, body in json.loads(sys.argv[1]):
    r = client.post(path, json=body)
    out.append([path, r.status_code, hashlib.sha256(r.content).hexdigest()])
print("RESULT " + json.dumps(out))
'''

_SEEDS = ("0", "1", "2", "3")


def _seed_requests() -> list[list]:
    e, b = _EXCHANGES, _B
    day = {"start_date": "2026-10-18", "end_date": "2026-10-18"}
    return [
        ["/v1/chart", e],
        ["/v1/yogas", e],
        ["/v1/strength", e],
        ["/v1/special-points", e],
        ["/v1/profile", e],
        ["/v1/dashas", {**e, "from_date": "2026-01-01", "to_date": "2031-01-01"}],
        ["/v1/transits", {**e, "at_date": "2026-10-18"}],
        ["/v1/compat", {"person_a": e, "person_b": b, "reference_date": "2026-10-18"}],
        ["/v1/muhurat", {**e, **day}],
        ["/v1/muhurat/lagna-shuddhi",
         {**e, **day, "activity_category": "marriage", "step_seconds": 900}],
        ["/v1/muhurat/family-lagna-shuddhi",
         {"members": [e, b], **day, "activity_category": "generic", "step_seconds": 900}],
    ]


def test_every_route_answers_identically_under_any_hash_seed() -> None:
    requests = json.dumps(_seed_requests())
    by_seed = {
        seed: _run_child(_SEED_CHILD, [requests], _child_env(PYTHONHASHSEED=seed))
        for seed in _SEEDS
    }
    first = by_seed[_SEEDS[0]]
    assert [row[1] for row in first] == [200] * len(first), first
    differing = sorted({
        row[0]
        for rows in by_seed.values()
        for row, ref in zip(rows, first, strict=True)
        if row != ref
    })
    assert differing == [], (
        "these routes answered the same request differently under PYTHONHASHSEED "
        f"{', '.join(_SEEDS)}: {differing}. Some output order or wording depends on "
        "set iteration order."
    )
