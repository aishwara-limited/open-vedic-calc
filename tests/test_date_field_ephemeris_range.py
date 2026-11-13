"""Every date field the caller can send must sit inside the served ephemeris span.

PR #68 bounded ``birth_date`` to the MEASURED Swiss data span
(``MIN_EPHEMERIS_DATE``..``MAX_EPHEMERIS_DATE``, app/schemas.py) after finding
that the tail of the advertised range answered at HTTP 200 off the Moshier
fallback. ``birth_date`` was not the only date on the wire. NINE further
``IsoDateStr`` inputs carried no range check at all — ``at_date``, ``from_date``,
``to_date``, and THREE ``start_date``/``end_date`` pairs — and a TENTH,
``reference_date``, was missed by the field sweep entirely because it is a
``date``, not an ``IsoDateStr``, so it never matched that grep. TEN in all, and
``_SINGLE_DATE_CASES`` below carries one entry per field.

MEASURED BEFORE THIS CHANGE (base 5e63404, Swiss data present, spying on every
``swe.calc_ut`` a served request makes):

    field                        input            base behaviour
    ---------------------------- ---------------- --------------------------------
    at_date          /v1/transits 9999-01-01      500 — UNCAUGHT swisseph.Error
    at_date          /v1/transits 0001-01-01      500 — UNCAUGHT swisseph.Error
    at_date          /v1/transits 2400-06-01      200, 10/25 calls on MOSHIER
    at_date          /v1/transits 2500-01-01      200, 71/86 calls on MOSHIER
    start/end        /v1/muhurat  2400-06-01      200, 1450/6353 calls on MOSHIER
    start/end        lagna-shuddhi 2400-06-01     200, 1650/6553 calls on MOSHIER
    start/end        family        2400-06-01     200, 3300/13106 calls on MOSHIER
    reference_date   /v1/compat   9999-01-01      500 — UNCAUGHT OverflowError
    from/to          /v1/dashas   9999-12-31      422 (the MAX_DASHA_DAYS cap)

The two 500s are the same class of defect PR #68's docstring described for
``birth_date=9999-01-01``: a well-formed request reaching the engine unguarded
and faulting there instead of being refused at the schema boundary. The four
silent-Moshier rows are the same class as the ``birth_date`` tail — a 200 whose
numbers came from the fallback engine with nothing in the response saying so.

WHAT THESE TESTS DO AND DO NOT CLAIM
------------------------------------
``at_date`` is asserted Swiss-backed at both bounds across every timezone
corner, because it is a single instant lookup and the spy can attribute the
calls to it.

``reference_date``, ``from_date`` and ``to_date`` are NOT asserted Swiss-backed,
and that omission is deliberate rather than an oversight. Measured, they drive
ZERO ephemeris calls.

For /v1/dashas the demonstration has to run on a pair the service will actually
SERVE, which a normal birth cannot provide: birth 1950-06-15 with to_date
2999-12-31 is refused 422 by the birth-relative MAX_DASHA_DAYS cap having made
ZERO ephemeris calls, so it shows nothing either way. A late birth keeps the cap
satisfied — measured at base with birth 2390-06-15 and from_date 2395-01-01,
to_date at 2400-01-09, 2450-01-01 and 2500-01-01 all returned 200 with the
swe.calc_ut count pinned at exactly 15 (the natal chart), the last of them
running ~100 years past the ephemeris span. /v1/compat needs no such care, having
no cap: 30 calls (its two natal charts) at reference_date 2026-05-26,
2400-01-09, 2500-01-01 and 3000-01-01 alike.

A "Swiss-backed" spy assertion on those fields would pass by construction while
measuring nothing, which is worse than no test. They are bounded for the crash
and for a uniform served contract; what is asserted here is the crash closing.

The muhurat/lagna-shuddhi scanned-day fields ARE now asserted Swiss-backed at
their bound, which they previously were not. They are bound to a NARROWER span
than the point-lookup fields — ``MIN_SCANNED_DATE``..``MAX_SCANNED_DATE`` rather
than ``MIN_EPHEMERIS_DATE``..``MAX_EPHEMERIS_DATE`` — because a scanned day is
not a point lookup: measured per limb, ``compute_muhurat_for_day`` reaches up to
+31.835 d past the day it is scanning, so the same date bound that is correct
for ``birth_date`` let an accepted scan run off the end of the shipped files.
Every assertion here about "the bound" therefore names the bound that binds THAT
field; see ``tests/test_scanned_day_ephemeris_reach.py`` for the per-limb
measurement and the derivation.
"""
import datetime
import os
import threading
from types import UnionType
from typing import Annotated, Union, get_args, get_origin

import pytest
from pydantic import AfterValidator, BaseModel

os.environ.setdefault("CALC_SERVICE_TOKEN", "test")
os.environ.setdefault("PUBLIC_SOURCE_URL", "https://example.com")

import swisseph as swe
from fastapi.testclient import TestClient

from app import schemas as app_schemas
from app.main import app
from app.schemas import (
    MAX_EPHEMERIS_DATE,
    MAX_SCANNED_DATE,
    MIN_EPHEMERIS_DATE,
    MIN_SCANNED_DATE,
)
from bphs_core import utils
from tests.conftest import SAMPLE_A, SAMPLE_B

_ONE_DAY = datetime.timedelta(days=1)
MIN_S = MIN_EPHEMERIS_DATE.isoformat()
MAX_S = MAX_EPHEMERIS_DATE.isoformat()
BELOW_MIN = (MIN_EPHEMERIS_DATE - _ONE_DAY).isoformat()
ABOVE_MAX = (MAX_EPHEMERIS_DATE + _ONE_DAY).isoformat()

# The three electional start_date/end_date pairs are bound MORE TIGHTLY than the
# point-lookup fields, because a scanned day reaches up to +31.8 d past itself
# (see tests/test_scanned_day_ephemeris_reach.py for the per-limb measurement).
# Every assertion below that names "the bound" therefore has to name the bound
# that actually binds THAT field — a test carrying one span for all ten fields
# would pass only by accident once the two spans differ.
SCAN_MIN_S = MIN_SCANNED_DATE.isoformat()
SCAN_MAX_S = MAX_SCANNED_DATE.isoformat()

# (lo, hi) as ISO strings, per field class.
_POINT_BOUNDS = (MIN_S, MAX_S)
_SCAN_BOUNDS = (SCAN_MIN_S, SCAN_MAX_S)

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

# A birth date that leaves plenty of MAX_DASHA_DAYS headroom, so a /v1/dashas
# assertion about the ephemeris bound is never actually answered by the cap.
_DASHA_PERSON = {**SAMPLE_A, "birth_date": "1950-06-15"}

_SCAN_EXTRA = {"activity_category": "generic", "step_seconds": 3600}


def _transits(at_date, **over):
    return {**SAMPLE_A, "at_date": at_date, **over}


def _dashas(from_date, to_date, **over):
    return {**_DASHA_PERSON, "from_date": from_date, "to_date": to_date,
            "systems": ["vimshottari"], **over}


def _dashas_valid_at(d):
    """A /v1/dashas body that is valid in EVERY respect except the span check.

    The ephemeris span is ~600 years wide while MAX_DASHA_DAYS caps a timeline
    at ~128 years FROM BIRTH, so no single anchor birth date can pair with both
    ends of the span: to_date=2400-01-09 against a 1950 birth trips the cap, and
    from_date=2400-01-09 against a 1970 to_date trips the ordering guard. Both
    would answer 422 for a reason that has nothing to do with the bound under
    test. Collapsing birth, from and to onto the same day makes the cap zero and
    the ordering trivially satisfied, so a 422 here can only be the span bound.
    """
    return {**SAMPLE_A, "birth_date": d, "from_date": d, "to_date": d,
            "systems": ["vimshottari"]}


def _muhurat(start, end, **over):
    return {**SAMPLE_A, "start_date": start, "end_date": end, **over}


def _lagna(start, end, **over):
    return {**SAMPLE_A, "start_date": start, "end_date": end, **_SCAN_EXTRA, **over}


def _family(start, end, **over):
    return {"members": [SAMPLE_A, SAMPLE_B], "start_date": start, "end_date": end,
            **_SCAN_EXTRA, **over}


def _compat(d):
    return {"person_a": SAMPLE_A, "person_b": SAMPLE_B, "reference_date": d}


# (label, endpoint, field name, builder for an OUT-OF-SPAN probe, builder for an
# otherwise-entirely-valid probe, the (lo, hi) span that binds THIS field). The
# two builders differ only for /v1/dashas, where the birth-relative cap and the
# ordering guard would otherwise answer instead of the bound — see
# _dashas_valid_at. The span is carried per case because the six scanned-day
# fields are bound more tightly than the four point-lookup ones.
_SINGLE_DATE_CASES = [
    ("at_date", "/v1/transits", "at_date",
     lambda d: _transits(d), lambda d: _transits(d), _POINT_BOUNDS),
    ("from_date", "/v1/dashas", "from_date",
     lambda d: _dashas(d, "1970-01-01"), _dashas_valid_at, _POINT_BOUNDS),
    ("to_date", "/v1/dashas", "to_date",
     lambda d: _dashas("1960-01-01", d), _dashas_valid_at, _POINT_BOUNDS),
    ("muhurat.start_date", "/v1/muhurat", "start_date",
     lambda d: _muhurat(d, d), lambda d: _muhurat(d, d), _SCAN_BOUNDS),
    ("muhurat.end_date", "/v1/muhurat", "end_date",
     lambda d: _muhurat(d, d), lambda d: _muhurat(d, d), _SCAN_BOUNDS),
    ("lagna.start_date", "/v1/muhurat/lagna-shuddhi", "start_date",
     lambda d: _lagna(d, d), lambda d: _lagna(d, d), _SCAN_BOUNDS),
    ("lagna.end_date", "/v1/muhurat/lagna-shuddhi", "end_date",
     lambda d: _lagna(d, d), lambda d: _lagna(d, d), _SCAN_BOUNDS),
    ("family.start_date", "/v1/muhurat/family-lagna-shuddhi", "start_date",
     lambda d: _family(d, d), lambda d: _family(d, d), _SCAN_BOUNDS),
    ("family.end_date", "/v1/muhurat/family-lagna-shuddhi", "end_date",
     lambda d: _family(d, d), lambda d: _family(d, d), _SCAN_BOUNDS),
    ("reference_date", "/v1/compat", "reference_date", _compat, _compat,
     _POINT_BOUNDS),
]

_IDS = [c[0] for c in _SINGLE_DATE_CASES]


# ---------------------------------------------------------------------------
# The COUNT is derived here, never typed into prose
# ---------------------------------------------------------------------------
#
# The first draft of this module said "eight" because a grep for `IsoDateStr`
# was eyeballed and the three start_date/end_date pairs were read as two. The
# number was wrong in five places before anyone re-counted. So the enumeration
# is computed from the schema module itself and asserted, and any future date
# input either appears here or reddens this file.


_OUT_OF_SPAN_PROBES = ("2500-01-01", datetime.date(2500, 1, 1))


def _after_validators(annotation) -> list:
    """Every AfterValidator function reachable inside this annotation.

    Recursive because a naive ``field.metadata`` check gets ``reference_date``
    WRONG: it is declared ``BoundedReferenceDate | None``, and for a union
    Pydantic leaves ``FieldInfo.metadata`` EMPTY — the validator lives on the
    union's Annotated member, not on the field.
    """
    out: list = []
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        out += [m.func for m in args[1:] if isinstance(m, AfterValidator)]
        out += _after_validators(args[0])
        return out
    if get_origin(annotation) in (Union, UnionType):
        for arg in get_args(annotation):
            out += _after_validators(arg)
    return out


def _rejects_out_of_span(funcs) -> bool:
    """Does any of these validators actually REFUSE a date outside the span?

    Presence of an AfterValidator is NOT the question, and testing for it was a
    real bug in the first draft of this checker. ``IsoDateStr`` carries its own
    AfterValidator — the ISO *shape* check — so a presence test calls every bare
    ``IsoDateStr`` field "bounded". Measured: with that version, reverting
    ``at_date: BoundedAtDate`` to ``at_date: IsoDateStr`` left this file GREEN,
    which is exactly the regression the checker exists to catch.

    So the validators are CALLED with an out-of-span probe and must raise. A
    shape validator accepts 2500-01-01 happily; only a range validator refuses.
    """
    for fn in funcs:
        for probe in _OUT_OF_SPAN_PROBES:
            try:
                fn(probe)
            except ValueError:
                return True
            except Exception:
                continue  # wrong probe type for this validator; try the other
    return False


def _request_model_date_fields() -> dict[tuple[str, str], bool]:
    """{(model, field): is_bounded} for every date-ish field on a request model."""
    found: dict[tuple[str, str], bool] = {}
    for name in dir(app_schemas):
        obj = getattr(app_schemas, name)
        if not (isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel):
            continue
        # Request models only: response models are free to carry unbounded dates.
        if not any(tag in name for tag in ("Request", "DataIn", "Member", "PersonFields")):
            continue
        for field, info in obj.model_fields.items():
            if "date" in field:
                # BOTH places must be gathered, and each catches what the other
                # misses. For a plain `x: BoundedAtDate` Pydantic HOISTS the
                # metadata onto FieldInfo.metadata and leaves `annotation` as the
                # bare `str`/`date` — so walking the annotation alone finds
                # nothing. For `x: BoundedReferenceDate | None` it does the
                # opposite: metadata is EMPTY and the validator stays inside the
                # union member. Measured both ways; a checker that looks in one
                # place is wrong about half the fields here.
                funcs = [m.func for m in info.metadata if isinstance(m, AfterValidator)]
                funcs += _after_validators(info.annotation)
                found[(name, field)] = _rejects_out_of_span(funcs)
    return found


def test_every_request_model_date_field_is_bounded():
    """No date a caller can send may reach the engine unbounded."""
    fields = _request_model_date_fields()
    unbounded = sorted(k for k, bounded in fields.items() if not bounded)
    assert not unbounded, (
        "these request-model date fields carry no range validator:\n"
        + "\n".join(f"  - {m}.{f}" for m, f in unbounded)
    )


def test_the_non_birth_date_field_count_is_ten():
    """Pins the number this module's docstring states.

    Ten distinct declaration sites, not ten models: birth_date is declared once
    on BoundedPersonFields and inherited, while start_date/end_date are declared
    separately on each of the three scan request models.
    """
    non_birth = sorted(k for k in _request_model_date_fields() if k[1] != "birth_date")
    assert len(non_birth) == 10, (
        f"expected 10 non-birth date fields on request models, found "
        f"{len(non_birth)}:\n" + "\n".join(f"  - {m}.{f}" for m, f in non_birth)
        + "\n\nIf a date input was added or removed, update the count in this "
        "module's docstring, app/schemas.py and CLAUDE.md together — and add a "
        "_SINGLE_DATE_CASES entry for it."
    )


def test_the_case_table_covers_every_non_birth_date_field():
    """_SINGLE_DATE_CASES must not silently stop covering a field."""
    declared = {f for (_m, f) in _request_model_date_fields() if f != "birth_date"}
    covered = {field for (_l, _e, field, _bad, _ok, _bounds) in _SINGLE_DATE_CASES}
    assert declared == covered, (
        f"case table covers {sorted(covered)} but the request models declare "
        f"{sorted(declared)}; missing {sorted(declared - covered)}"
    )
    assert len(_SINGLE_DATE_CASES) == 10, (
        f"expected one case per non-birth date field (10), got {len(_SINGLE_DATE_CASES)}"
    )


# ---------------------------------------------------------------------------
# Out of span -> 422, and the 422 names the real bound
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", _SINGLE_DATE_CASES, ids=_IDS)
@pytest.mark.parametrize("bad", ["9999-01-01", "0001-01-01", "2400-06-01", "2500-01-01"])
def test_out_of_span_date_is_422(case, bad):
    """Every date input refuses a value outside the served ephemeris span.

    2400-06-01 and 2500-01-01 are the important rows: they are not absurd
    inputs, they are dates the service used to ANSWER at 200 with numbers from
    the Moshier fallback. 9999-01-01 and 0001-01-01 are the two that faulted.
    """
    label, endpoint, _field, build_bad, _build_ok, _bounds = case
    r = client.post(endpoint, json=build_bad(bad))
    assert r.status_code == 422, (
        f"{label}={bad} was not refused at the schema boundary. "
        f"Got {r.status_code}: {r.text[:300]}"
    )


@pytest.mark.parametrize("case", _SINGLE_DATE_CASES, ids=_IDS)
def test_the_422_names_the_field_and_the_real_bound(case):
    """A caller must be told which field and which span, in dates not years.

    "The real bound" is the one that binds THIS field. A scanned-day field whose
    422 quoted the point-lookup span would send the caller looking for a bug in
    a request that the service had in fact refused for a different, narrower
    reason — so the span asserted here is the per-case one.
    """
    label, endpoint, field, build_bad, _build_ok, (lo, hi) = case
    r = client.post(endpoint, json=build_bad("2500-01-01"))
    assert r.status_code == 422
    body = r.text
    assert field in body, f"{label}: the 422 does not name the field. Got: {body[:400]}"
    assert lo in body, (
        f"{label}: the 422 does not name this field's lower bound ({lo}). "
        f"Got: {body[:400]}"
    )
    assert hi in body, (
        f"{label}: the 422 does not name this field's upper bound ({hi}). "
        f"Got: {body[:400]}"
    )


@pytest.mark.parametrize("case", _SINGLE_DATE_CASES, ids=_IDS)
@pytest.mark.parametrize("end", ["lower", "upper"])
def test_one_day_outside_each_bound_is_422(case, end):
    label, endpoint, _field, build_bad, _build_ok, (lo, hi) = case
    edge = (
        (datetime.date.fromisoformat(lo) - _ONE_DAY).isoformat()
        if end == "lower"
        else (datetime.date.fromisoformat(hi) + _ONE_DAY).isoformat()
    )
    r = client.post(endpoint, json=build_bad(edge))
    assert r.status_code == 422, (
        f"{label}={edge} is one day outside this field's span ({lo}..{hi}) and "
        f"must be refused. Got {r.status_code}: {r.text[:200]}"
    )


@pytest.mark.parametrize("case", _SINGLE_DATE_CASES, ids=_IDS)
@pytest.mark.parametrize("end", ["lower", "upper"])
def test_the_bounds_themselves_are_accepted(case, end):
    """The bound is inclusive: neither end may be refused."""
    label, endpoint, _field, _build_bad, build_ok, (lo, hi) = case
    edge = lo if end == "lower" else hi
    r = client.post(endpoint, json=build_ok(edge))
    assert r.status_code != 422, (
        f"{label}={edge} is ON this field's bound ({lo}..{hi}) and must be "
        f"accepted. Got 422: {r.text[:300]}"
    )


# ---------------------------------------------------------------------------
# The two uncaught engine faults this closes
# ---------------------------------------------------------------------------

def test_transits_year_9999_no_longer_reaches_the_engine():
    """Base: 500, uncaught ``swisseph.Error`` from drik.sidereal_longitude.

    Measured on 5e63404 — ``swisseph.Error: swisseph.calc_ut: SwissEph file
    'sepl_96.se1' not found`` escaping to the caller as a raw 500. The schema
    must refuse it before the engine is reached.
    """
    r = client.post("/v1/transits", json=_transits("9999-01-01"))
    assert r.status_code == 422, f"expected a clean 422, got {r.status_code}"


def test_compat_year_9999_no_longer_overflows():
    """Base: 500, uncaught ``OverflowError: date value out of range``.

    Measured on 5e63404 at bphs_core/compat.py:374 —
    ``window_start + timedelta(days=25 * 365.25)`` runs past year 9999 and
    raises. This is the TENTH date field, and the one the IsoDateStr sweep
    missed: reference_date is a ``date``, so it never matched that grep.
    """
    r = client.post("/v1/compat", json={
        "person_a": SAMPLE_A, "person_b": SAMPLE_B, "reference_date": "9999-01-01"})
    assert r.status_code == 422, f"expected a clean 422, got {r.status_code}"


def test_compat_reference_date_stays_optional():
    """The bound must not make an optional field required."""
    r = client.post("/v1/compat", json={"person_a": SAMPLE_A, "person_b": SAMPLE_B})
    assert r.status_code == 200, r.text[:300]


# ---------------------------------------------------------------------------
# Reversed ranges — pinned. These already 422 on base; the bound must not
# convert any of them into a 200, a crash, or an empty iteration.
# ---------------------------------------------------------------------------

_REVERSED = [
    ("/v1/dashas", _dashas("2030-01-01", "2020-01-01"), ("from_date", "to_date")),
    ("/v1/muhurat", _muhurat("2026-05-27", "2026-05-26"), ("start_date", "end_date")),
    ("/v1/muhurat/lagna-shuddhi", _lagna("2026-05-27", "2026-05-26"), ("start_date", "end_date")),
    ("/v1/muhurat/family-lagna-shuddhi", _family("2026-05-27", "2026-05-26"), ("start_date", "end_date")),
]


@pytest.mark.parametrize("endpoint,body,names", _REVERSED,
                         ids=[e for e, _b, _n in _REVERSED])
def test_reversed_in_bounds_range_is_422_naming_the_order(endpoint, body, names):
    """Measured on base: all four already 422 with an ordering message.

    Both ends are inside the span here, so the new bound cannot be what
    refuses them — this pins that the ORDERING guard is still the thing that
    fires, and that a reversed range never degrades to an empty 200.
    """
    r = client.post(endpoint, json=body)
    assert r.status_code == 422, f"{endpoint}: got {r.status_code}: {r.text[:200]}"
    low = r.text.lower()
    assert any(n in low for n in names), (
        f"{endpoint}: the 422 does not name the ordering. Got: {r.text[:300]}"
    )


@pytest.mark.parametrize("endpoint,body", [
    ("/v1/muhurat", _muhurat(SCAN_MAX_S, SCAN_MIN_S)),
    ("/v1/muhurat/lagna-shuddhi", _lagna(SCAN_MAX_S, SCAN_MIN_S)),
    ("/v1/muhurat/family-lagna-shuddhi", _family(SCAN_MAX_S, SCAN_MIN_S)),
])
def test_reversed_range_exactly_on_both_bounds_is_still_422(endpoint, body):
    """The widest legal-but-reversed range. Both ends pass the span check, so
    the ordering guard is the only thing standing between this and a scan that
    iterates nothing."""
    r = client.post(endpoint, json=body)
    assert r.status_code == 422, f"{endpoint}: got {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# Composition with the pre-existing range CAPS
# ---------------------------------------------------------------------------

def test_muhurat_day_cap_still_fires_for_an_in_bounds_range():
    """An over-cap range with BOTH ends inside the span must still hit the cap.

    If the new bound shadowed the cap, this would come back with the span
    message instead — the cap would be dead code and a 400-day scan would be
    refused for the wrong reason (or, once someone "fixed" the message, not at
    all).
    """
    import app.main as main_mod
    start = datetime.date(2026, 1, 1)
    end = start + datetime.timedelta(days=main_mod.MAX_MUHURAT_DAYS + 1)
    assert MIN_SCANNED_DATE <= start and end <= MAX_SCANNED_DATE, (
        "this test must exercise the CAP, not the scanned-day span bound"
    )
    r = client.post("/v1/muhurat", json=_muhurat(start.isoformat(), end.isoformat()))
    assert r.status_code == 422
    assert "exceeds" in r.text.lower(), (
        f"the day cap no longer fires — the span bound shadowed it. Got: {r.text[:300]}"
    )


def test_lagna_shuddhi_day_cap_still_fires_for_an_in_bounds_range():
    import app.main as main_mod
    start = datetime.date(2026, 1, 1)
    end = start + datetime.timedelta(days=main_mod.MAX_LAGNA_SHUDDHI_DAYS + 1)
    assert MIN_SCANNED_DATE <= start and end <= MAX_SCANNED_DATE, (
        "this test must exercise the CAP, not the scanned-day span bound"
    )
    r = client.post("/v1/muhurat/lagna-shuddhi", json=_lagna(start.isoformat(), end.isoformat()))
    assert r.status_code == 422
    assert "exceeds" in r.text.lower(), r.text[:300]


def test_dasha_cap_still_fires_for_an_in_bounds_range():
    """MAX_DASHA_DAYS is measured from BIRTH, so it can still fire on a
    to_date well inside the ephemeris span. SAMPLE_A is born 1950-06-15;
    birth + 47001 days is 2079-ish — comfortably inside the bound."""
    import app.main as main_mod
    birth = datetime.date.fromisoformat(_DASHA_PERSON["birth_date"])
    to_dt = birth + datetime.timedelta(days=main_mod.MAX_DASHA_DAYS + 1)
    assert to_dt <= MAX_EPHEMERIS_DATE, (
        "this test must exercise the CAP, not the span bound — "
        f"{to_dt} is outside {MAX_S}"
    )
    r = client.post("/v1/dashas", json=_dashas(birth.isoformat(), to_dt.isoformat()))
    assert r.status_code == 422
    assert "exceeds" in r.text.lower(), (
        f"the dasha cap no longer fires. Got: {r.text[:300]}"
    )


def test_full_life_dasha_span_still_returns_200():
    """Positive control: the legitimate 120-year full-cycle request must not
    become collateral damage of the new bound."""
    birth = datetime.date.fromisoformat(_DASHA_PERSON["birth_date"])
    to_dt = birth + datetime.timedelta(days=44000)
    r = client.post("/v1/dashas", json=_dashas(birth.isoformat(), to_dt.isoformat()))
    assert r.status_code == 200, r.text[:300]
    lords = {p["lord"] for p in r.json() if p["level"] == "mahadasha"}
    assert len(lords) >= 9, f"expected all 9 mahadasha lords, got {lords}"


# ---------------------------------------------------------------------------
# The async submit paths share these models — the refusal must land at SUBMIT,
# not inside a job that reports failure later.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("endpoint,body", [
    ("/v1/muhurat/lagna-shuddhi/async", _lagna("2400-06-01", "2400-06-02")),
    ("/v1/muhurat/family-lagna-shuddhi/async", _family("2400-06-01", "2400-06-02")),
])
def test_async_submit_refuses_an_out_of_span_range(endpoint, body):
    r = client.post(endpoint, json=body)
    assert r.status_code == 422, (
        f"{endpoint} accepted an out-of-span range for asynchronous execution "
        f"({r.status_code}) — the caller would get a job id and a late failure "
        "instead of a refusal."
    )


# The band that is inside the POINT-lookup span but outside the SCANNED-DAY span
# is exactly what the narrower bound added, so it is the band worth probing on
# every path that accepts a scan. Without this, the async submit could keep the
# wider bound and nothing would say so.
_BETWEEN_THE_TWO_SPANS = (MAX_SCANNED_DATE + _ONE_DAY).isoformat()


@pytest.mark.parametrize("endpoint,build", [
    ("/v1/muhurat", _muhurat),
    ("/v1/muhurat/lagna-shuddhi", _lagna),
    ("/v1/muhurat/family-lagna-shuddhi", _family),
    ("/v1/muhurat/lagna-shuddhi/async", _lagna),
    ("/v1/muhurat/family-lagna-shuddhi/async", _family),
])
def test_a_scan_day_inside_the_point_span_but_past_the_scan_bound_is_422(
    endpoint, build
):
    """The narrower scanned-day bound binds every scan path, sync and async.

    ``MAX_SCANNED_DATE + 1`` is still comfortably inside ``MAX_EPHEMERIS_DATE``,
    so a field that had kept the point-lookup span would answer 200 here — and
    would answer it off the Moshier fallback for part of the compute, which is
    the defect the narrower bound exists to close.
    """
    assert MAX_SCANNED_DATE < MAX_EPHEMERIS_DATE, (
        "this probe only means something while the two spans differ"
    )
    r = client.post(endpoint, json=build(_BETWEEN_THE_TWO_SPANS,
                                         _BETWEEN_THE_TWO_SPANS))
    assert r.status_code == 422, (
        f"{endpoint} accepted {_BETWEEN_THE_TWO_SPANS} as a scanned day. That is "
        f"past MAX_SCANNED_DATE ({MAX_SCANNED_DATE}), so part of the scan's "
        f"compute reads past the end of the shipped files. Got {r.status_code}: "
        f"{r.text[:200]}"
    )
    assert SCAN_MAX_S in r.text, (
        f"{endpoint}: the refusal does not quote the scanned-day bound. "
        f"Got: {r.text[:300]}"
    )


def test_the_two_spans_give_DIFFERENT_reasons_for_a_refusal():
    """A refused scanned day must not be explained in point-lookup terms.

    "Outside the span the data files cover" is a true reason for `at_date` and a
    MISLEADING one for a scanned day: MAX_SCANNED_DATE + 1 is comfortably inside
    the files, so a caller told that the data does not cover it would reasonably
    conclude the service was wrong. What is outside the files is what the scan
    READS AROUND that day. This pins that the two field classes explain
    themselves differently, so the reason cannot silently collapse back onto one
    wording the way the bounds themselves once did.
    """
    scan = client.post("/v1/muhurat",
                       json=_muhurat(_BETWEEN_THE_TWO_SPANS, _BETWEEN_THE_TWO_SPANS))
    point = client.post("/v1/transits", json=_transits("2500-01-01"))
    assert scan.status_code == 422 and point.status_code == 422

    files_cover = "data files actually cover"
    assert files_cover in point.text, (
        "the point-lookup 422 stopped explaining itself as the span the files "
        f"cover. Got: {point.text[:300]}"
    )
    assert files_cover not in scan.text, (
        "a scanned-day refusal is being explained as 'the span the data files "
        f"actually cover' — but {_BETWEEN_THE_TWO_SPANS} IS covered by the files; "
        "what is not covered is the ~32 days the scan reads around it. Got: "
        f"{scan.text[:400]}"
    )
    assert "not a point lookup" in scan.text, (
        f"the scanned-day 422 does not say why its span is narrower. "
        f"Got: {scan.text[:400]}"
    )


# ---------------------------------------------------------------------------
# at_date is Swiss-backed at both bounds — re-measured, not restated
# ---------------------------------------------------------------------------

_TZ_CORNERS = (14.0, -12.0, 5.5)


def _moshier_calls_during(endpoint: str, body: dict) -> tuple[int, int]:
    """(moshier_calls, total_calls) over every swe.calc_ut the request makes."""
    records: list[int] = []
    lock = threading.Lock()
    real_calc_ut = swe.calc_ut

    # *args/**kwargs, not a fixed positional signature: pyjhora calls
    # swe.calc_ut(jd, planet, flags=flags) by KEYWORD on the sidereal_longitude
    # path, so a spy declared (jd, planet, flags, ...) survives only because its
    # third parameter happens to be spelled `flags`. Rename it and every probe
    # through that path raises TypeError and records nothing — a zero that means
    # "blind instrument", not "no Moshier calls".
    def spy(*args, **kwargs):
        values, retflag = real_calc_ut(*args, **kwargs)
        with lock:
            records.append(retflag)
        return values, retflag

    swe.calc_ut = spy
    try:
        response = client.post(endpoint, json=body)
    finally:
        swe.calc_ut = real_calc_ut

    assert response.status_code == 200, (
        f"the probe request itself failed: {response.status_code} {response.text[:300]}"
    )
    with lock:
        flags = list(records)
    assert flags, "no swe.calc_ut calls were observed — the spy did not take effect"
    return sum(1 for f in flags if f & swe.FLG_MOSEPH), len(flags)


def test_at_date_at_both_bounds_is_swiss_backed(swiss_ephemeris: int) -> None:
    """No admissible /v1/transits request inside the span may answer on Moshier.

    at_date is a single instant lookup, so — unlike the scanned-day fields —
    the spy attributes these calls to the bounded field itself. Sweeping the
    timezone extremes is what makes reusing birth_date's one-day margin a
    measurement rather than an assumption: tz=+14 pulls the UTC instant a day
    earlier than the local date and tz=-12 pushes it a day later.
    """
    failures: list[str] = []
    for bound in (MIN_S, MAX_S):
        for tz in _TZ_CORNERS:
            for birth_time in ("00:00:00", "23:59:59"):
                body = _transits(
                    bound,
                    birth_date=MIN_S if bound == MIN_S else "1990-01-01",
                    birth_time=birth_time,
                    timezone_offset_hours=tz,
                )
                moshier, total = _moshier_calls_during("/v1/transits", body)
                if moshier:
                    failures.append(
                        f"at_date={bound} tz={tz:+g} birth_time={birth_time}: "
                        f"{moshier}/{total} swe.calc_ut calls answered on MOSHIER"
                    )
    assert not failures, (
        "an admissible /v1/transits request inside the served span was computed "
        "on the Moshier fallback:\n"
        + "\n".join(f"  - {f}" for f in failures)
        + "\n\nEither the bound is too wide for the shipped files or the timezone "
        "margin is too thin. Re-measure before widening anything."
    )


def test_an_at_date_just_past_the_bound_would_have_leaked(swiss_ephemeris: int) -> None:
    """The bound is TIGHT, not merely safe.

    Without this, narrowing at_date to any small interval would satisfy the
    test above. Asks the engine's own detector whether the day past the bound
    (plus the timezone margin) really is where the data stops.
    """
    past = MAX_EPHEMERIS_DATE + datetime.timedelta(days=2)
    swiss_active, _ = utils.probe_ephemeris_source(
        swe.julday(past.year, past.month, past.day, 12.0), swe.SUN
    )
    assert not swiss_active, (
        f"{past} still answers from Swiss data, so the shipped files reach further "
        "than when this bound was measured. The bound is now needlessly narrow — "
        "re-measure and widen it deliberately."
    )


# ---------------------------------------------------------------------------
# CLOSED: the scanned-day endpoints no longer consult data outside the files.
# ---------------------------------------------------------------------------
#
# This section used to read "KNOWN, SEPARATELY-TRACKED", because the bound could
# not stop the searches described below from crossing the end of the data — the
# fallback happens INSIDE one pyjhora call, where no restore can intercept it.
# The separate tracking is now discharged: the scanned-day fields carry their own
# narrower bound (``MAX_SCANNED_DATE``, app/schemas.py), derived from the reach
# measured per limb, so an ACCEPTED scanned day never reaches outside the shipped
# files in the first place. ``test_no_accepted_scanned_day_loses_accuracy_to_the_
# fallback`` below asserts the consequence, and
# ``tests/test_scanned_day_ephemeris_reach.py`` asserts the cause.
#
# TWO THINGS THE ACCOUNT BELOW GOT WRONG, corrected in place rather than deleted,
# because the reasoning is what makes the numbers checkable:
#   * ``drik.tithi`` is named below as the leading contributor among the day's
#     own panchanga limbs. Re-measured per call site with an instrument that is
#     not blind to pyjhora's keyword call spelling, ``drik.tithi`` has the
#     SMALLEST out-of-day reach of any limb (+1.998 d). The second-furthest limb
#     is ``drik.yogam`` at +24.859 d, which nothing here had mentioned; the
#     furthest is ``drik.lunar_month`` at +31.834 d.
#   * the earlier spy was declared ``def spy(jd, planet, flags, *a, **k)`` and
#     survives pyjhora's ``swe.calc_ut(jd, planet, flags=flags)`` only because
#     its third parameter happens to be spelled ``flags``. Rename it and the
#     probe raises TypeError and silently records nothing.
#
# WHAT THE PREDECESSOR OF THIS SECTION GOT WRONG
# ----------------------------------------------
# It attributed the whole residual to ``muhurat.py::_is_eclipse_day`` calling
# ``drik.next_solar_eclipse`` / ``next_lunar_eclipse``, on the strength of the
# ``_moshier_calls_during`` spy below. That attribution cannot have come from
# that instrument: ``swe.sol_eclipse_when_loc`` and ``swe.lun_eclipse_when``
# compute their positions INSIDE the C library and never re-enter the Python
# binding, so the spy records **zero** calls for the whole of ``_is_eclipse_day``
# (measured at 2400-01-09, 1800-01-02 and 2026-05-26 alike, and now pinned by
# ``tests/test_muhurat_edge_probe_engine.py``).
#
# Re-measured, attributing each Moshier call to its call site:
#
#   scanned 1800-01-02  1500/1864 on Moshier, ALL of them ``_is_adhik_maasa``
#                       (``drik.lunar_month``) searching back to 1798-07-10.
#   scanned 2400-01-09   342/2800 on Moshier — 48 from ``_is_adhik_maasa``
#                       reaching forward to 2400-01-29, and 294 from the day's
#                       OWN panchanga limbs — ``drik.tithi`` first — at
#                       2400-01-08..2400-01-10.
#
# Those call sites are named by FUNCTION, deliberately, not by line number. The
# first draft of this block cited the tithi call by line number, which was true
# at the base commit and false by the time it was written: the same change that
# added this comment added ~25 lines to ``_is_eclipse_day`` above it, shifting
# that call (492 -> 517). A citation invalidated by its own commit is the worst
# case of the failure this repo already recorded ("a citation that rots
# silently is worse than none"), and it is not hypothetical here — sweeping the
# tree's other file:line citations turned up further pre-existing ones that no
# longer point at what they claim, none of them introduced by this change.
#
# HOW MANY is deliberately not written here, and that omission is the point.
# A count in this comment is another hand-typed number that nothing recounts: it
# would rot the next time any cited file is edited, which is the same defect the
# paragraph above is warning about. Two review rounds on this very change died on
# hand-typed numbers, and the sweeping instrument has known blind spots as well:
# a citation naming two lines of one file at once, prose phrasings, and
# citations into dependencies whose line numbers move with the pinned version. Any
# total would therefore be one instrument's lower bound wearing the costume of a
# fact. The enumeration lives in the change's report against a stated commit,
# where it is a dated measurement instead of a standing claim.
#
# Name the callee and its enclosing function; both are greppable and neither
# moves when a line is inserted somewhere above.
#
# THE PART THAT ACTUALLY COSTS ACCURACY
# -------------------------------------
# Reading past the files is not itself a defect — the next eclipse and the
# bracketing new moons genuinely are outside the scanned day, and no data exists
# there to read. What IS a defect is that swisseph KEEPS the fallback afterwards,
# so a later lookup at an IN-span JD answers analytically too. Measured on base
# in a fresh process::
#
#     probe Moon at 2400-01-09       -> SWISS   (retflag 65602)
#     read  Moon at 2400-01-29       -> MOSHIER (retflag 65604)
#     probe Moon at 2400-01-09 again -> MOSHIER (retflag 65604)   # still in span
#
# So the number worth tracking is not "Moshier calls" (a scan at 1800-01-02 makes
# 1500 of them and loses nothing — every one is at a JD with no data) but
# "Moshier calls at a JD that IS inside the files". ``_in_span_fallback_during``
# below counts exactly that, and the two tests that follow pin it.
#
# Measured after ``_is_eclipse_day`` began restoring the ephemeris state:
#   * low edge  1800-01-02..1801-07-14 — ZERO in-span loss on all 58 dates
#     sampled, despite up to 1600/3300 calls answering on Moshier.
#   * high edge — the residual is real and timezone-dependent. Earliest scanned
#     day showing any in-span loss across the tz corners is 2399-12-24 (tz=-12,
#     4 calls); it becomes dense over the final week (up to 303 calls).
#   * interior — zero, including 10-day and 30-day RANGE scans at every corner.
#
# That high-edge residual was ``drik.yogam``'s and ``_is_adhik_maasa``'s searches
# running past the data end (NOT principally ``drik.tithi``'s — see the
# correction at the head of this section), which no restore inside this repo can
# prevent, because the fallback happens *within* one pyjhora call. It is closed
# by narrowing the scanned-day bound so those searches have nothing to run off:
# ``MAX_SCANNED_DATE`` = 2399-12-01 leaves a 40.853 d budget to the end of the
# data against a 31.835 d worst measured reach. Re-measured after the narrowing,
# the walk below over the last accepted days finds ZERO in-span loss at every
# timezone corner, where the same walk at ``MAX_EPHEMERIS_DATE`` lost 122-226
# calls per request.

# The measured extent of the shipped Sun/Moon data (sepl_18 / semo_18), at
# one-day steps with utils.probe_ephemeris_source. Wider than the SERVED span on
# purpose: MAX_EPHEMERIS_DATE is 2400-01-09 and the files reach 2400-01-10, so a
# scanned day's next-day lookups are legitimately inside the data.
_FILES_FIRST_JD = swe.julday(1800, 1, 1, 0.0)
_FILES_LAST_JD = swe.julday(2400, 1, 10, 24.0)


def _in_span_fallback_during(endpoint: str, body: dict) -> tuple[int, int, int]:
    """(in_span_fallback, moshier, total) over every swe.calc_ut of a request.

    ``in_span_fallback`` is the count that means "accuracy was lost": a call at a
    Julian Day the shipped files DO cover, which nonetheless answered from the
    Moshier engine. A Moshier answer outside the files is not a defect; there is
    nothing else to answer with.
    """
    records: list[tuple[float, int]] = []
    lock = threading.Lock()
    real_calc_ut = swe.calc_ut

    # See the note on the sibling spy above: signature-agnostic on purpose.
    def spy(*args, **kwargs):
        jd = args[0] if args else kwargs["jd"]
        values, retflag = real_calc_ut(*args, **kwargs)
        with lock:
            records.append((jd, retflag))
        return values, retflag

    swe.calc_ut = spy
    try:
        response = client.post(endpoint, json=body)
    finally:
        swe.calc_ut = real_calc_ut

    assert response.status_code == 200, (
        f"the probe request itself failed: {response.status_code} {response.text[:300]}"
    )
    with lock:
        seen = list(records)
    assert seen, "no swe.calc_ut calls were observed — the spy did not take effect"
    moshier = [(jd, rf) for jd, rf in seen if rf & swe.FLG_MOSEPH]
    in_span = [jd for jd, _rf in moshier if _FILES_FIRST_JD <= jd <= _FILES_LAST_JD]
    return len(in_span), len(moshier), len(seen)


def test_the_interior_of_the_span_loses_no_accuracy_to_the_fallback(
    swiss_ephemeris: int,
) -> None:
    """Inside the served range, nothing answers from the fallback at all.

    The predecessor asserted this for ONE mid-span day. That is too weak in two
    ways, and both were measured before being fixed here: an out-of-range search
    can leave the engine degraded for the NEXT day of the same scan (so a range
    scan is a different question from a single day), and the local-day boundary
    moves with the timezone (so one offset is not a measurement of the field).
    """
    failures: list[str] = []
    # These sit BELOW MAX_SCANNED_DATE, not below MAX_EPHEMERIS_DATE. The
    # predecessor's range started on 2399-12-01 and ran ten days past it, which
    # the scanned-day bound now refuses outright — a 422 the probe would report
    # as a failed request rather than as a clean scan, so the dates move with the
    # bound they are meant to sit inside.
    cases = [
        ("single day", "2399-11-01", "2399-11-01"),
        ("10-day range", "2399-11-01", "2399-11-10"),
        ("10-day range, modern", "2026-05-20", "2026-05-29"),
    ]
    for label, start, end in cases:
        for tz in _TZ_CORNERS:
            body = _muhurat(start, end, timezone_offset_hours=tz)
            in_span, moshier, total = _in_span_fallback_during("/v1/muhurat", body)
            if moshier:
                failures.append(
                    f"{label} {start}..{end} tz={tz:+g}: {moshier}/{total} calls on "
                    f"MOSHIER ({in_span} of them at a JD the files DO cover)"
                )
    assert not failures, (
        "a muhurat scan well inside the served span now answers on the Moshier "
        "fallback:\n" + "\n".join(f"  - {f}" for f in failures)
        + "\n\nThe edge residual has widened into the interior of the range. "
        "Re-measure it; do not relax this test."
    )


def test_no_accepted_scanned_day_loses_accuracy_to_the_fallback(
    swiss_ephemeris: int,
) -> None:
    """The end-of-range residual is CLOSED, at the last day the service accepts.

    THIS REPLACES ``test_the_edge_residual_stays_at_the_edge``, and the
    replacement is the point. That test asserted only that the residual did not
    spread INWARD, and deliberately refused to assert the final days were clean
    "because they are not". They are now: the scanned-day fields are bound to
    ``MAX_SCANNED_DATE``, derived so a scanned day's furthest measured reach
    (+31.835 d) still lands inside the shipped files.

    So the assertion inverts. Instead of requiring a clear month of margin below
    the bound, this walks the last days the service will ACCEPT — the ones whose
    predecessors leaked — and requires every one of them to be clean at every
    timezone corner. Measured before the bound moved, the same walk at
    ``MAX_EPHEMERIS_DATE`` lost 122-226 in-span calls per request depending on
    the offset, and 53 of 64 (day, tz) combinations read past the end of the
    data outright.
    """
    failures: list[str] = []
    for days_below in (0, 1, 3, 7, 15, 30, 180):
        day = (MAX_SCANNED_DATE - datetime.timedelta(days=days_below)).isoformat()
        for tz in _TZ_CORNERS:
            body = _muhurat(day, day, timezone_offset_hours=tz)
            in_span, moshier, total = _in_span_fallback_during("/v1/muhurat", body)
            if in_span:
                failures.append(
                    f"{day} (SCAN_MAX-{days_below}d) tz={tz:+g}: {in_span} of "
                    f"{moshier}/{total} Moshier calls were at a JD INSIDE the "
                    "shipped files"
                )
    assert not failures, (
        "a muhurat scan on a day the service ACCEPTS lost accuracy to the "
        "fallback on a Julian Day the shipped files DO cover:\n"
        + "\n".join(f"  - {f}" for f in failures)
        + "\n\nMAX_SCANNED_DATE is supposed to make this impossible. Re-measure "
        "the scan's forward reach (tests/test_scanned_day_ephemeris_reach.py) "
        "and narrow the bound; do not relax this test."
    )


def test_no_accepted_lagna_shuddhi_scan_loses_accuracy_at_either_edge(
    swiss_ephemeris: int,
) -> None:
    """The lagna-shuddhi scans compute one NEIGHBOURING day beyond each end of
    the request, and that reach is clean at both scanned-day bounds.

    A scan scores each instant against the vaara (sunrise to sunrise) that
    contains it, so its pre-dawn hours need the day BEFORE ``start_date`` and
    its windows need the day AFTER ``end_date`` (a night window reaches the
    next date, and a Varjyam can lie on the previous evening) -- see
    ``bphs_core/lagna_shuddhi.py::_ScanDays``. That moves the scan's reach one
    day past ``MAX_SCANNED_DATE`` (inside its 9-day margin) and one day before
    ``MIN_SCANNED_DATE`` (before the data, where a Moshier answer is not a loss).
    Measured when the neighbour days were introduced: zero in-span fallback at
    either bound, at every timezone corner, for the solo and the family route.
    """
    failures: list[str] = []
    for day in (MAX_SCANNED_DATE, MIN_SCANNED_DATE):
        iso = day.isoformat()
        cases = [
            ("/v1/muhurat/lagna-shuddhi", _lagna(iso, iso, timezone_offset_hours=tz))
            for tz in _TZ_CORNERS
        ] + [("/v1/muhurat/family-lagna-shuddhi", _family(iso, iso))]
        for endpoint, body in cases:
            in_span, moshier, total = _in_span_fallback_during(endpoint, body)
            if in_span:
                failures.append(
                    f"{endpoint} {iso}: {in_span} of {moshier}/{total} Moshier "
                    "calls were at a JD INSIDE the shipped files"
                )
    assert not failures, (
        "a lagna-shuddhi scan on a day the service ACCEPTS lost accuracy to the "
        "fallback:\n" + "\n".join(f"  - {f}" for f in failures)
    )
