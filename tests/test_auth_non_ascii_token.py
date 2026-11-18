"""A token header that is not ASCII is a wrong token: 401, never 500.

THE DEFECT THIS CLOSED
----------------------
``require_token`` compared the presented header with the configured token as
two ``str`` values. ``hmac.compare_digest`` refuses a ``str`` holding any
non-ASCII character and raises ``TypeError``; the header is whatever the client
sent, so a single byte above 0x7F in ``X-Calc-Service-Token`` turned an
authentication refusal into an unhandled exception and a 500. Access was still
denied, but a 500 reads as an outage, is retried, and lands in the error budget
instead of the auth log.

THE RULE
--------
The comparison is made on bytes (both sides encoded the same way), still in
constant time, and is defined for every header value. A value that is not the
token is a 401 whatever bytes it holds.

WHAT IS PINNED
--------------
* Through the real routes: a non-ASCII header is 401 with the same body as any
  other wrong token, on a POST route and on ``/source``.
* The right token still passes; a wrong ASCII token is still 401; a token that
  merely STARTS with the right one is still 401.
* ``require_token`` itself never raises anything but the 401, over a spread of
  hostile strings, and the comparison still goes through
  ``hmac.compare_digest``.
"""
from __future__ import annotations

import hmac

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from tests.conftest import SAMPLE_A

_TOKEN = "test"  # what tests/conftest.py configures
_HEADER = "X-Calc-Service-Token"
_REFUSAL = {"detail": "Invalid or missing service token"}

# Header values as the BYTES a client can put on the wire.
_NON_ASCII_HEADERS = [
    b"\xe9wrong",                    # one Latin-1 byte, the audited case
    b"\xff\xfe\xfd",                 # nothing printable at all
    "tést".encode("utf-8"),     # a UTF-8 lookalike of the real token
    b"test\xe9",                     # the real token with one byte appended
    b"\xe9test",                     # ... and prepended
    b"tes\xf4",                      # same length as the real token
]


@pytest.fixture(scope="module")
def client():
    """No default token header, and server exceptions returned as responses so
    a defect reads as the 500 a caller would see."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize("header", _NON_ASCII_HEADERS, ids=repr)
def test_non_ascii_token_is_401_on_a_post_route(client, header):
    r = client.post("/v1/chart", json=SAMPLE_A, headers={_HEADER: header})
    assert r.status_code == 401, r.text
    assert r.json() == _REFUSAL


@pytest.mark.parametrize("header", _NON_ASCII_HEADERS, ids=repr)
def test_non_ascii_token_is_401_on_source(client, header):
    r = client.get("/source", headers={_HEADER: header})
    assert r.status_code == 401, r.text
    assert r.json() == _REFUSAL


def test_the_right_token_still_passes(client):
    assert client.post("/v1/chart", json=SAMPLE_A, headers={_HEADER: _TOKEN}).status_code == 200
    assert client.get("/source", headers={_HEADER: _TOKEN}).status_code == 200


@pytest.mark.parametrize("header", ["wrong", "tes", "testt", "TEST", ""])
def test_a_wrong_ascii_token_is_still_401(client, header):
    r = client.post("/v1/chart", json=SAMPLE_A, headers={_HEADER: header})
    assert r.status_code == 401, r.text
    assert r.json() == _REFUSAL


def test_a_missing_header_is_still_401(client):
    r = client.post("/v1/chart", json=SAMPLE_A)
    assert r.status_code == 401
    assert r.json() == _REFUSAL


# Strings as the dependency can receive them: the server decodes header bytes
# as Latin-1, so every code point up to U+00FF is reachable from the wire; the
# rest are here to show the comparison is defined for ANY string.
_HOSTILE_STRINGS = [
    "éwrong", "ÿþ", "testé", "tést", "\x00test", "test\x00",
    "中文", "\U0001f512", "\ud800", "test\udcff", "‮tset",
]


@pytest.mark.parametrize("presented", _HOSTILE_STRINGS, ids=ascii)
def test_require_token_refuses_any_string_with_a_401_and_nothing_else(monkeypatch, presented):
    monkeypatch.setenv("CALC_SERVICE_TOKEN", _TOKEN)
    with pytest.raises(HTTPException) as refused:
        auth.require_token(x_calc_service_token=presented)
    assert refused.value.status_code == 401
    assert refused.value.detail == _REFUSAL["detail"]


def test_require_token_accepts_exactly_the_configured_token(monkeypatch):
    monkeypatch.setenv("CALC_SERVICE_TOKEN", "0123456789abcdef0123456789abcdef")
    assert auth.require_token(x_calc_service_token="0123456789abcdef0123456789abcdef") is None
    for near_miss in ("0123456789abcdef0123456789abcde", "0123456789abcdef0123456789abcdef0"):
        with pytest.raises(HTTPException) as refused:
            auth.require_token(x_calc_service_token=near_miss)
        assert refused.value.status_code == 401


def test_the_comparison_is_still_constant_time(monkeypatch):
    """The fix must not trade the timing-safe comparison for ``==``: every
    presented token, right or wrong, ASCII or not, goes through
    ``hmac.compare_digest``, and what it is handed is bytes."""
    monkeypatch.setenv("CALC_SERVICE_TOKEN", _TOKEN)
    compared: list[tuple] = []
    real = hmac.compare_digest

    def recording(a, b):
        compared.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", recording)
    auth.require_token(x_calc_service_token=_TOKEN)
    for presented in ("wrong", "éwrong"):
        with pytest.raises(HTTPException):
            auth.require_token(x_calc_service_token=presented)
    assert len(compared) == 3
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in compared)
    assert all(_TOKEN.encode("utf-8") in pair for pair in compared)
