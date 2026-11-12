"""
CALC-2: Coordinate bounds validation tests.

Verifies that non-finite (nan/inf) and out-of-range coordinates are rejected
with 422 at the schema boundary, and that valid extremes still pass (200).

The critical case is nan: ge/le constraints alone do NOT reject nan because
NaN comparisons are always False in IEEE 754, so a NaN field would silently
pass range checks and flow into swe.houses() / drik.Place(), producing a
finite-but-wrong chart. allow_inf_nan=False is required to catch this.

Note on sending non-finite values:
Python's json.dumps() raises ValueError for nan/inf (not valid JSON), so
tests that need to send NaN/Infinity literals must use content= with a raw
bytes body rather than json=. The test client's json= would fail before the
request is even sent.
"""
import json
import os

from fastapi.testclient import TestClient

os.environ.setdefault("CALC_SERVICE_TOKEN", "test")
os.environ.setdefault("PUBLIC_SOURCE_URL", "https://example.com")

from app.main import app
from tests.conftest import SAMPLE_A

client = TestClient(
    app,
    headers={"X-Calc-Service-Token": "test"},
    raise_server_exceptions=False,
)

_JSON_HEADERS = {"Content-Type": "application/json", "X-Calc-Service-Token": "test"}

# ---------------------------------------------------------------------------
# Base payloads — same shape the existing tests use.
# ---------------------------------------------------------------------------

_CHART_BASE = dict(SAMPLE_A)

_MUHURAT_BASE = {
    **SAMPLE_A,
    "start_date": "2026-05-26",
    "end_date": "2026-05-27",
}

_LAGNA_SHUDDHI_BASE = {
    **SAMPLE_A,
    "start_date": "2026-05-26",
    "end_date": "2026-05-27",
    "activity_category": "generic",
    "step_seconds": 60,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chart(overrides: dict) -> int:
    """POST /v1/chart with finite overrides and return status code."""
    return client.post("/v1/chart", json={**_CHART_BASE, **overrides}).status_code


def _chart_raw(body: str) -> int:
    """POST /v1/chart with raw JSON bytes (allows NaN/Infinity literals)."""
    return client.post("/v1/chart", content=body.encode(), headers=_JSON_HEADERS).status_code


def _muhurat(overrides: dict) -> int:
    """POST /v1/muhurat with finite overrides and return status code."""
    return client.post("/v1/muhurat", json={**_MUHURAT_BASE, **overrides}).status_code


def _muhurat_raw(body: str) -> int:
    """POST /v1/muhurat with raw JSON bytes (allows NaN/Infinity literals)."""
    return client.post("/v1/muhurat", content=body.encode(), headers=_JSON_HEADERS).status_code


def _lagna_shuddhi(overrides: dict) -> int:
    """POST /v1/muhurat/lagna-shuddhi with finite overrides and return status code."""
    return client.post(
        "/v1/muhurat/lagna-shuddhi", json={**_LAGNA_SHUDDHI_BASE, **overrides}
    ).status_code


def _lagna_shuddhi_raw(body: str) -> int:
    """POST /v1/muhurat/lagna-shuddhi with raw JSON bytes."""
    return client.post(
        "/v1/muhurat/lagna-shuddhi", content=body.encode(), headers=_JSON_HEADERS
    ).status_code


def _make_chart_body(lat: str, lon: str = "80.0", tz: str = "5.5") -> str:
    """Build a raw chart JSON body with the given lat/lon/tz as literal strings."""
    return (
        '{"name":"x","birth_date":"1950-06-15","birth_time":"06:00:00",'
        f'"birth_place":"S","latitude":{lat},"longitude":{lon},"timezone_offset_hours":{tz}}}'
    )


def _make_muhurat_body(lat: str = "7.0", lon: str = "80.0", tz: str = "5.5") -> str:
    return (
        '{"name":"x","birth_date":"1950-06-15","birth_time":"06:00:00",'
        f'"birth_place":"S","latitude":{lat},"longitude":{lon},"timezone_offset_hours":{tz},'
        '"start_date":"2026-05-26","end_date":"2026-05-27"}'
    )


def _make_lagna_body(lat: str = "7.0", lon: str = "80.0", tz: str = "5.5") -> str:
    return (
        '{"name":"x","birth_date":"1950-06-15","birth_time":"06:00:00",'
        f'"birth_place":"S","latitude":{lat},"longitude":{lon},"timezone_offset_hours":{tz},'
        '"start_date":"2026-05-26","end_date":"2026-05-27",'
        '"activity_category":"generic","step_seconds":60}'
    )


# ---------------------------------------------------------------------------
# Non-finite values — the critical CALC-2 case.
# nan passes ge/le guards silently; allow_inf_nan=False is what stops it.
# These MUST use raw JSON bodies because Python json.dumps() rejects nan/inf.
# ---------------------------------------------------------------------------

class TestNonFiniteChart:
    """Non-finite coordinates on /v1/chart must be rejected with 422."""

    def test_latitude_nan_is_422(self):
        # THE critical test: ge/le alone would let NaN slip through (NaN < x
        # is always False). allow_inf_nan=False is what closes this gap.
        assert _chart_raw(_make_chart_body("NaN")) == 422

    def test_latitude_inf_is_422(self):
        assert _chart_raw(_make_chart_body("Infinity")) == 422

    def test_latitude_neg_inf_is_422(self):
        assert _chart_raw(_make_chart_body("-Infinity")) == 422

    def test_longitude_nan_is_422(self):
        assert _chart_raw(_make_chart_body("7.0", "NaN")) == 422

    def test_longitude_inf_is_422(self):
        assert _chart_raw(_make_chart_body("7.0", "Infinity")) == 422

    def test_longitude_large_finite_is_422(self):
        # 1e308 is finite but out of range — rejected by ge/le (no raw needed).
        assert _chart({"longitude": 1e308}) == 422

    def test_tz_nan_is_422(self):
        assert _chart_raw(_make_chart_body("7.0", "80.0", "NaN")) == 422

    def test_tz_inf_is_422(self):
        assert _chart_raw(_make_chart_body("7.0", "80.0", "Infinity")) == 422


class TestNonFiniteMuhurat:
    """Non-finite coordinates on /v1/muhurat must be rejected with 422."""

    def test_latitude_nan_is_422(self):
        assert _muhurat_raw(_make_muhurat_body(lat="NaN")) == 422

    def test_latitude_inf_is_422(self):
        assert _muhurat_raw(_make_muhurat_body(lat="Infinity")) == 422

    def test_longitude_nan_is_422(self):
        assert _muhurat_raw(_make_muhurat_body(lon="NaN")) == 422


class TestNonFiniteLagnaShuddhi:
    """Non-finite coordinates on /v1/muhurat/lagna-shuddhi must be 422."""

    def test_latitude_nan_is_422(self):
        assert _lagna_shuddhi_raw(_make_lagna_body(lat="NaN")) == 422

    def test_latitude_inf_is_422(self):
        assert _lagna_shuddhi_raw(_make_lagna_body(lat="Infinity")) == 422

    def test_longitude_nan_is_422(self):
        assert _lagna_shuddhi_raw(_make_lagna_body(lon="NaN")) == 422


# ---------------------------------------------------------------------------
# Out-of-range finite values (chart endpoint)
# ---------------------------------------------------------------------------

class TestOutOfRangeChart:
    """Out-of-range but finite coordinates on /v1/chart must be 422."""

    def test_latitude_too_high(self):
        assert _chart({"latitude": 91}) == 422

    def test_latitude_too_low(self):
        assert _chart({"latitude": -91}) == 422

    def test_longitude_too_high(self):
        assert _chart({"longitude": 181}) == 422

    def test_longitude_too_low(self):
        assert _chart({"longitude": -181}) == 422

    def test_tz_too_high(self):
        assert _chart({"timezone_offset_hours": 15}) == 422

    def test_tz_too_low(self):
        assert _chart({"timezone_offset_hours": -13}) == 422


class TestOutOfRangeMuhurat:
    """Out-of-range finite coordinates on /v1/muhurat must be 422."""

    def test_latitude_too_high(self):
        assert _muhurat({"latitude": 91}) == 422

    def test_longitude_too_high(self):
        assert _muhurat({"longitude": 181}) == 422

    def test_tz_too_high(self):
        assert _muhurat({"timezone_offset_hours": 15}) == 422

    def test_tz_too_low(self):
        assert _muhurat({"timezone_offset_hours": -13}) == 422


class TestOutOfRangeLagnaShuddhi:
    """Out-of-range finite coordinates on /v1/muhurat/lagna-shuddhi must be 422."""

    def test_latitude_too_high(self):
        assert _lagna_shuddhi({"latitude": 91}) == 422

    def test_longitude_too_high(self):
        assert _lagna_shuddhi({"longitude": 181}) == 422

    def test_tz_too_high(self):
        assert _lagna_shuddhi({"timezone_offset_hours": 15}) == 422

    def test_tz_too_low(self):
        assert _lagna_shuddhi({"timezone_offset_hours": -13}) == 422


# ---------------------------------------------------------------------------
# Valid extremes must PASS (200) — real-world offsets must not be rejected.
# ---------------------------------------------------------------------------

class TestValidExtremesChart:
    """Boundary-exact and real-world offsets must not be schema-rejected (422).

    For latitude, the schema allows ge=-90, le=90, and the compute layer
    answers the whole range: Placidus is undefined beyond the polar circles,
    where the chart takes the equal-house fallback and says so in
    house_system (tests/test_polar_latitude_chart.py pins that through the
    route). So the poles must be 200, not merely "not 422". For tz and
    longitude we verify 200 because the underlying computation handles the
    full range.
    """

    def test_latitude_positive_90_schema_accepts(self):
        # lat=90 is within the schema bounds (ge=-90, le=90) and computes on the
        # equal-house fallback.
        assert _chart({"latitude": 90}) == 200

    def test_latitude_negative_90_schema_accepts(self):
        # Same reasoning as lat=90.
        assert _chart({"latitude": -90}) == 200

    def test_latitude_mid_range_passes(self):
        # A latitude in the computable range must return 200.
        assert _chart({"latitude": 60.0}) == 200

    def test_latitude_negative_mid_range_passes(self):
        assert _chart({"latitude": -60.0}) == 200

    def test_longitude_positive_180(self):
        assert _chart({"longitude": 180}) == 200

    def test_longitude_negative_180(self):
        assert _chart({"longitude": -180}) == 200

    def test_tz_india_5_5(self):
        # India Standard Time (+05:30)
        assert _chart({"timezone_offset_hours": 5.5}) == 200

    def test_tz_nepal_5_75(self):
        # Nepal Time (+05:45)
        assert _chart({"timezone_offset_hours": 5.75}) == 200

    def test_tz_india_sri_lanka_positive(self):
        # Sri Lanka / India (+05:30, used in SAMPLE_A)
        assert _chart({"timezone_offset_hours": 5.5}) == 200

    def test_tz_chatham_islands_12_75(self):
        # Chatham Islands (+12:45)
        assert _chart({"timezone_offset_hours": 12.75}) == 200

    def test_tz_min_negative_12(self):
        # Baker / Howland Islands (-12:00)
        assert _chart({"timezone_offset_hours": -12}) == 200

    def test_tz_max_positive_14(self):
        # Line Islands / Kiribati (+14:00)
        assert _chart({"timezone_offset_hours": 14}) == 200


# ---------------------------------------------------------------------------
# Family lagna-shuddhi: coordinate bounds enforced on FamilyMember fields.
# FamilyMember redefines lat/lon/tz (not inherited from PersonalDataIn),
# so the Field constraints must be applied there explicitly.
# ---------------------------------------------------------------------------

_FAMILY_BASE = {
    "members": [
        {**SAMPLE_A},
        {**SAMPLE_A, "name": "sample_b2"},
    ],
    "start_date": "2026-05-26",
    "end_date": "2026-05-27",
    "activity_category": "generic",
    "step_seconds": 60,
}


class TestFamilyCoordBounds:
    """Coordinate bounds enforced on FamilyMember (not inherited — redefined)."""

    def test_member_latitude_nan_is_422(self):
        # NaN in a family member's coordinates must be rejected.
        body = json.dumps({
            **_FAMILY_BASE,
            "members": [
                {**SAMPLE_A},
                {**SAMPLE_A, "name": "sample_b2"},
            ],
        })
        # Replace one latitude value with NaN literal in the raw JSON.
        body_raw = body.replace(
            f'"latitude": {SAMPLE_A["latitude"]}',
            '"latitude": NaN',
            1,  # first occurrence only (first member)
        )
        r = client.post(
            "/v1/muhurat/family-lagna-shuddhi",
            content=body_raw.encode(),
            headers=_JSON_HEADERS,
        )
        assert r.status_code == 422

    def test_member_latitude_out_of_range_is_422(self):
        bad = {
            **_FAMILY_BASE,
            "members": [
                {**SAMPLE_A, "latitude": 91},
                {**SAMPLE_A, "name": "sample_b2"},
            ],
        }
        r = client.post("/v1/muhurat/family-lagna-shuddhi", json=bad)
        assert r.status_code == 422

    def test_member_tz_too_high_is_422(self):
        bad = {
            **_FAMILY_BASE,
            "members": [
                {**SAMPLE_A, "timezone_offset_hours": 15},
                {**SAMPLE_A, "name": "sample_b2"},
            ],
        }
        r = client.post("/v1/muhurat/family-lagna-shuddhi", json=bad)
        assert r.status_code == 422
