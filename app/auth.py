import hmac
import logging
import os

from fastapi import Header, HTTPException, status

from .deployment import LENIENT_ENVS, environment, is_real_deployment

logger = logging.getLogger(__name__)

# The environment policy lives in app/deployment.py, not here. Two independent
# fail-closed guards read it — this one and app/ephemeris_guard.py — and a
# second copy of the environment list would let them disagree: a container that
# enforces its token while tolerating a Moshier ephemeris, or the reverse. The
# fail-secure default (ENVIRONMENT unset means 'production', so auth is ON
# unless an operator explicitly names an insecure environment) is defined there
# and is unchanged; the old default 'development' was fail-open.

# Resolved once at import. ENVIRONMENT does not change within a running process,
# and caching it prevents a runtime os.environ mutation from silently flipping
# authentication off mid-process.
_TOKEN_REQUIRED: bool = is_real_deployment()

# A real deployment token is a long random secret. Reject obvious placeholders
# and anything too short: a guessable/default token (e.g. left at "changeme")
# is no better than no token at all.
_MIN_TOKEN_LEN = 16
_PLACEHOLDER_TOKENS = {
    "test", "tests", "testing", "changeme", "change-me", "change_me",
    "secret", "token", "password", "placeholder", "example", "dummy",
    "calc", "calc-token", "calc-service-token", "your-token-here", "xxx", "todo",
}


def _token_weakness_reason(token: str) -> str | None:
    """Why *token* is unacceptable for a non-dev deployment, or None if it is fine.

    Pure helper so the policy is unit-testable without process-env gymnastics.
    """
    if not token:
        return "unset"
    if token.strip().lower() in _PLACEHOLDER_TOKENS:
        return "a known placeholder value"
    if len(token) < _MIN_TOKEN_LEN:
        return f"too short (<{_MIN_TOKEN_LEN} chars)"
    return None


# Fail fast at import (app startup) rather than on the first request: a non-dev
# deployment with a missing OR weak token is a misconfiguration, not a runtime
# condition. A guessable default would expose every calc endpoint.
if _TOKEN_REQUIRED:
    _weakness = _token_weakness_reason(os.environ.get("CALC_SERVICE_TOKEN", ""))
    if _weakness:
        raise RuntimeError(
            f"CALC_SERVICE_TOKEN is {_weakness} in ENVIRONMENT={environment()!r}. "
            "The calc-service refuses to start with a missing or weak token outside "
            f"{sorted(LENIENT_ENVS)}. Set CALC_SERVICE_TOKEN to a long random secret."
        )
else:
    # Auth is intentionally disabled (ENVIRONMENT is in LENIENT_ENVS).
    # Emit a startup CRITICAL so this insecure mode is impossible to miss in logs.
    logger.critical(
        "Authentication is DISABLED: ENVIRONMENT=%r is in the insecure-env list %r. "
        "ALL calc endpoints are unprotected. "
        "Set ENVIRONMENT to a non-insecure value and supply CALC_SERVICE_TOKEN "
        "before exposing this service.",
        environment(),
        sorted(LENIENT_ENVS),
    )


def _same_token(presented: str, expected: str) -> bool:
    """Constant-time equality of two tokens, defined for EVERY string.

    ``hmac.compare_digest`` refuses a ``str`` holding any non-ASCII character
    (``TypeError``), and *presented* is whatever the client put in the header --
    the server decodes header bytes as Latin-1, so one byte above 0x7F is
    enough. Comparing the two as ``str`` therefore turned a wrong token into an
    unhandled exception and a 500. Both sides are encoded the same way and
    compared as bytes instead, where ``compare_digest`` accepts anything.
    ``surrogatepass`` makes the encoding total as well, so there is no input
    for which this raises: a value that is not the token is simply not equal.
    Contract: tests/test_auth_non_ascii_token.py.
    """
    return hmac.compare_digest(
        presented.encode("utf-8", "surrogatepass"),
        expected.encode("utf-8", "surrogatepass"),
    )


def require_token(
    x_calc_service_token: str = Header(default=""),
) -> None:
    """Validate the app-layer secret carried in ``X-Calc-Service-Token``.

    The token travels in its own header so that ``Authorization`` is reserved
    exclusively for the Google OIDC identity token: when Cloud Run IAM
    authentication is enabled, that ``Authorization: Bearer <id_token>`` is
    validated at the platform edge before the request reaches the container.
    The two are separate transports — Cloud Run handles identity, this function
    handles the in-container app secret — so they must never share a header.
    """
    expected = os.environ.get("CALC_SERVICE_TOKEN", "")
    if not expected:
        # Only reachable in an insecure env (the import-time guard blocks the
        # non-dev case). Fail closed anyway if that ever changes.
        if _TOKEN_REQUIRED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Calc service is misconfigured (no auth token).",
            )
        logger.critical(
            "CALC_SERVICE_TOKEN is not set — ALL ENDPOINTS ARE UNPROTECTED. "
            "ENVIRONMENT=%r is in the insecure-env list. "
            "Set CALC_SERVICE_TOKEN to enable authentication.",
            environment(),
        )
        return

    if not _same_token(x_calc_service_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token",
        )
