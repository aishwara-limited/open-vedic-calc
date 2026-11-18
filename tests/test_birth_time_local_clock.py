"""``birth_time`` is a local clock time; a value that carries a zone is refused.

THE DEFECT THIS CLOSED
----------------------
Every person-like request model typed ``birth_time`` as a plain ``time``. That
type also accepts a clock time WITH a zone -- ``"10:30:00+05:30"``,
``"10:30:00Z"`` -- and a bare number, which is read as seconds past midnight
*in UTC*. Either way the engine received a zone-aware time it has no use for:
the offset from UTC travels in ``timezone_offset_hours``. Two things followed.

* ``/v1/dashas`` and ``/v1/compat`` compared the zone-aware birth instant with
  zone-free dates and raised: an unhandled 500.
* Every other route silently DROPPED the zone and computed for the bare clock
  time, so ``"10:30:00Z"`` and ``"10:30:00+05:30"`` -- two different instants,
  five and a half hours apart -- produced one and the same chart.

THE RULE
--------
A ``birth_time`` that carries a zone is refused at the schema boundary: 422,
naming the field and saying where the offset belongs. It is refused rather than
stripped, because stripping is the silent second behaviour above made official.

WHAT IS PINNED
--------------
* Every route that takes a ``birth_time`` (derived from the app's own routes,
  so a new one cannot be left out of the table) answers 422 for a zoned value
  and for a number, at every position a person appears in the body.
* The same routes still accept a local time, and the local forms -- ``HH:MM``,
  ``HH:MM:SS`` and fractional seconds -- are all still valid.
* Every ``time`` field on every request model, found by walking the models the
  routes declare, refuses a zoned value -- so a new person-like model that
  types its field as a bare ``time`` reddens here.
"""
from __future__ import annotations

import datetime
import types
from typing import Annotated, Union, get_args, get_origin

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError, create_model

from app.main import app
from tests.conftest import SAMPLE_A, SAMPLE_B

_SCAN = {"start_date": "2026-05-26", "end_date": "2026-05-26"}
_STEP = {"step_seconds": 3600}

# Values that parse as a clock time WITH a zone.
_ZONED = [
    "06:00:00+05:30",   # the audited case
    "06:00:00Z",
    "06:00:00-08:00",
    "06:00+05:30",
    "06:00:00.5Z",
    "06:00:00+00:00",   # a zero offset is still a zone
    21600,              # a number: seconds past midnight, read as UTC
    21600.5,
]
_LOCAL = ["06:00", "06:00:00", "06:00:00.5", "23:59:59.999999", "00:00:00"]


def _person(birth_time, base=SAMPLE_A) -> dict:
    return {**base, "birth_time": birth_time}


# route -> (body builder taking the birth_time under test, the loc of that
# birth_time in the 422, the status a good request gets)
_CASES = {
    "/v1/chart": (lambda t: _person(t), ["body", "birth_time"], 200),
    "/v1/strength": (lambda t: _person(t), ["body", "birth_time"], 200),
    "/v1/dashas": (
        lambda t: {**_person(t), "from_date": "2020-01-01", "to_date": "2030-01-01"},
        ["body", "birth_time"], 200,
    ),
    "/v1/yogas": (lambda t: _person(t), ["body", "birth_time"], 200),
    "/v1/transits": (
        lambda t: {**_person(t), "at_date": "2025-01-01"}, ["body", "birth_time"], 200,
    ),
    "/v1/special-points": (lambda t: _person(t), ["body", "birth_time"], 200),
    "/v1/profile": (lambda t: _person(t), ["body", "birth_time"], 200),
    "/v1/muhurat": (lambda t: {**_person(t), **_SCAN}, ["body", "birth_time"], 200),
    "/v1/muhurat/lagna-shuddhi": (
        lambda t: {**_person(t), **_SCAN, **_STEP}, ["body", "birth_time"], 200,
    ),
    "/v1/muhurat/lagna-shuddhi/async": (
        lambda t: {**_person(t), **_SCAN, **_STEP}, ["body", "birth_time"], 202,
    ),
    "/v1/muhurat/family-lagna-shuddhi": (
        lambda t: {"members": [SAMPLE_A, _person(t, SAMPLE_B)], **_SCAN, **_STEP},
        ["body", "members", 1, "birth_time"], 200,
    ),
    "/v1/muhurat/family-lagna-shuddhi/async": (
        lambda t: {"members": [_person(t), SAMPLE_B], **_SCAN, **_STEP},
        ["body", "members", 0, "birth_time"], 202,
    ),
    "/v1/compat": (
        lambda t: {"person_a": SAMPLE_A, "person_b": _person(t, SAMPLE_B)},
        ["body", "person_b", "birth_time"], 200,
    ),
}
# /v1/compat takes two people; the second position is the row above, this is
# the first.
_COMPAT_FIRST = (
    lambda t: {"person_a": _person(t), "person_b": SAMPLE_B},
    ["body", "person_a", "birth_time"],
)
_ROUTES = sorted(_CASES)


@pytest.fixture(scope="module")
def client():
    """Server exceptions are returned as responses, so a defect reads as the
    500 a caller would see."""
    with TestClient(
        app, headers={"X-Calc-Service-Token": "test"}, raise_server_exceptions=False
    ) as c:
        yield c


def _assert_refused(response, loc: list) -> None:
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert [e["loc"] for e in errors] == [loc], errors
    # The message says where the offset belongs.
    assert "timezone_offset_hours" in errors[0]["msg"], errors


# ---------------------------------------------------------------------------
# Through every route
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize("zoned", _ZONED, ids=repr)
def test_a_zoned_birth_time_is_422_on_every_route(client, route, zoned):
    build, loc, _ok = _CASES[route]
    _assert_refused(client.post(route, json=build(zoned)), loc)


@pytest.mark.parametrize("zoned", _ZONED, ids=repr)
def test_a_zoned_birth_time_is_422_for_the_first_person_of_a_pair(client, zoned):
    build, loc = _COMPAT_FIRST
    _assert_refused(client.post("/v1/compat", json=build(zoned)), loc)


@pytest.mark.parametrize("route", _ROUTES)
def test_every_route_still_accepts_a_local_birth_time(client, route):
    build, _loc, ok = _CASES[route]
    r = client.post(route, json=build("06:00:00"))
    assert r.status_code == ok, (route, r.text)


@pytest.mark.parametrize("local", _LOCAL)
def test_every_local_form_is_still_accepted(client, local):
    r = client.post("/v1/chart", json=_person(local))
    assert r.status_code == 200, (local, r.text)


def test_two_different_instants_no_longer_share_one_chart(client):
    """What the silent path did: ``Z`` and ``+05:30`` are different instants,
    and both used to answer 200 with the chart of the bare clock time."""
    for zoned in ("06:00:00Z", "06:00:00+05:30"):
        assert client.post("/v1/chart", json=_person(zoned)).status_code == 422
    assert client.post("/v1/chart", json=_person("06:00:00")).status_code == 200


# ---------------------------------------------------------------------------
# The table above is complete, and so is the schema
# ---------------------------------------------------------------------------

def _unwrap(annotation) -> list:
    """The plain types inside an annotation: through Annotated, unions, lists."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _unwrap(get_args(annotation)[0])
    if origin in (Union, types.UnionType, list, tuple, set, frozenset):
        return [t for arg in get_args(annotation) for t in _unwrap(arg)]
    return [annotation]


def _time_fields(model: type[BaseModel], seen: set | None = None) -> list[tuple]:
    """Every (model, field name, FieldInfo) typed as a clock time, reached from
    *model* through nested request models."""
    seen = set() if seen is None else seen
    if model in seen:
        return []
    seen.add(model)
    found = []
    for name, info in model.model_fields.items():
        for inner in _unwrap(info.annotation):
            if inner is datetime.time:
                found.append((model, name, info))
            elif isinstance(inner, type) and issubclass(inner, BaseModel):
                found += _time_fields(inner, seen)
    return found


def _body_model(route: APIRoute):
    field = route.body_field
    if field is None:
        return None
    return getattr(field, "type_", None) or field.field_info.annotation


def _routes_taking_a_time() -> dict[str, list[tuple]]:
    out = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        model = _body_model(route)
        if isinstance(model, type) and issubclass(model, BaseModel):
            fields = _time_fields(model)
            if fields:
                out[route.path] = fields
    return out


def test_the_route_table_covers_every_route_that_takes_a_clock_time():
    assert sorted(_routes_taking_a_time()) == _ROUTES


def _refuses(info, value) -> bool:
    """Validate *value* through the field exactly as its model declares it."""
    probe = create_model("Probe", value=(info.annotation, info))
    try:
        probe.model_validate({"value": value})
    except ValidationError:
        return True
    return False


def test_every_request_model_clock_time_refuses_a_zone():
    fields = [f for found in _routes_taking_a_time().values() for f in found]
    declared = {(model.__name__, name) for model, name, _info in fields}
    # The sweep is not blind: it reaches the person-like models the routes use.
    assert {
        ("PersonalDataIn", "birth_time"), ("DashaRequest", "birth_time"),
        ("TransitRequest", "birth_time"), ("MuhurtRequest", "birth_time"),
        ("LagnaShuddhiRequest", "birth_time"), ("FamilyMember", "birth_time"),
    } <= declared
    unguarded = sorted(
        f"{model.__name__}.{name} accepts {zoned!r}"
        for model, name, info in fields
        for zoned in _ZONED
        if not _refuses(info, zoned)
    )
    assert not unguarded, "\n".join(unguarded)
    rejected_local = sorted(
        f"{model.__name__}.{name} refuses {local!r}"
        for model, name, info in fields
        for local in _LOCAL
        if _refuses(info, local)
    )
    assert not rejected_local, "\n".join(rejected_local)
