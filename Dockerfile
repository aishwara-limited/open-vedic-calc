# ---------------------------------------------------------------------------
# Stage 0 — the uv build tool, pinned by digest.
#
# This used to be `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/`, with
# a comment arguing a floating tag was fine because uv is the installer rather
# than a project dependency. Two things were wrong with that.
#
#   * `:latest` is re-resolved on EVERY build, so two builds of this commit can
#     install two different binaries and nothing here records which one shipped.
#     Every other input to this image is pinned — the interpreter by
#     .python-version, the dependency set by uv.lock under `uv sync --frozen`,
#     the ephemeris data to sha256 by ci/swiss_ephemeris.json. The tool that
#     performs the frozen install was the one input still resolved at build time.
#
#   * `COPY --from=<registry image>` is invisible to the automated dependency
#     updater. .github/dependabot.yml already watches the `docker` ecosystem for
#     this directory, but that ecosystem reads FROM instructions; an image named
#     only in a COPY is never parsed, so it is neither bumped for a disclosed CVE
#     nor reported as outdated. Pinning a digest on the COPY would have swapped a
#     mutable reference for a frozen one that nothing was watching.
#
# Declaring it as a stage fixes both: the reference is now a FROM the updater can
# see and version-bump, and it carries an immutable digest between bumps. The
# `:<version>@sha256:<digest>` form is deliberate — the digest is what makes the
# build reproducible, the tag is what the updater compares to decide a newer
# release exists and what makes a bump legible in a diff.
#
# Digest verified 2026-09-01 against the GHCR registry API's
# Docker-Content-Digest header for this tag (the 0.12.5 digest it replaces had
# been resolved 2026-08-16 and cross-checked against three sources:
#   docker buildx imagetools inspect ghcr.io/astral-sh/uv:<tag>
#   the GHCR registry API's Docker-Content-Digest header for that tag
#   docker manifest inspect ghcr.io/astral-sh/uv:<tag>
# — all agreeing). It is the multi-arch INDEX digest, so it resolves on every
# build platform — this pin changes no bytes today, it stops them moving
# unrecorded tomorrow.
#
# ci/tests/test_dockerfile_image_pins.py is the guard on this shape.
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 AS uv

# ---------------------------------------------------------------------------
# Stage 1 — the Swiss ephemeris data files.
#
# These are BAKED INTO the image, not supplied at runtime. They used to be
# neither: this file created an empty data/ephe and a comment claimed the data
# "must be volume-mounted or COPY'd separately", but no mount was ever codified
# anywhere. swisseph does not raise when its data files are missing — it
# silently substitutes its built-in Moshier analytical ephemeris and returns a
# plausible result — so a deployment computed every chart it served on the
# fallback engine and looked perfectly healthy doing it.
#
# Baking rather than mounting, deliberately:
#   * ~2.1 MB is nothing against a container image;
#   * the data becomes immutable WITH THE IMAGE DIGEST, so rolling back to an
#     image is rolling back to its data — which matters because this service is
#     deployed by resolved digest;
#   * it removes the whole class of "deployed without its data" rather than
#     adding one more runtime dependency that can silently be absent;
#   * and EVERY builder of this Dockerfile gets the data — CI, a downstream
#     deploy pipeline, a local `docker build`, a compose stack — instead of each
#     one having to remember a fetch step of its own. That "every caller must
#     remember" shape is exactly what failed here.
#
# The fetch reuses the repo's existing checksum-pinned fetcher against
# ci/swiss_ephemeris.json; there is deliberately no second mechanism. It is
# fail-closed in every direction (download failure, checksum mismatch, unpinned
# checksum, malformed manifest all exit non-zero). --self-test runs FIRST so a
# verifier that had stopped verifying can never certify the real download, and
# --verify-only re-checks afterwards, so what stage 2 copies forward is bytes
# that were checksummed after they landed.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS ephemeris
WORKDIR /fetch
COPY ci/fetch_swiss_ephemeris.py ci/fetch_swiss_ephemeris.py
COPY ci/swiss_ephemeris.json ci/swiss_ephemeris.json
RUN python ci/fetch_swiss_ephemeris.py --self-test \
 && python ci/fetch_swiss_ephemeris.py \
 && python ci/fetch_swiss_ephemeris.py --verify-only

# ---------------------------------------------------------------------------
# Stage 2 — the shipped service image.
# ---------------------------------------------------------------------------
FROM python:3.11-slim

# Bake the building commit into the image so /source can return the authoritative
# running-commit (the value a downstream consumer keys its cache on). The CI build
# passes this via --build-arg GIT_COMMIT=<sha>; _resolve_version() prefers it over
# every fallback. Empty default => local/dev builds fall back to the source-content
# hash, never a stale constant.
ARG GIT_COMMIT=""
ENV GIT_COMMIT=${GIT_COMMIT}

WORKDIR /app

# Install uv itself from the digest-pinned stage above. Supply-chain risk for the
# actual app deps is covered by the frozen lockfile install below; this covers the
# installer that performs it.
COPY --from=uv /uv /uvx /bin/

# Install from the committed, hash-pinned lockfile only — `--frozen` fails the
# build if pyproject.toml and uv.lock have drifted, instead of silently
# re-resolving. Replaces the old floating `pip install -e .`, which ignored
# uv.lock entirely and could pull an unpinned/compromised transitive version of
# pyswisseph (native C) or any other dependency.
COPY pyproject.toml uv.lock README.md LICENSE EPHEMERIS_LICENSE.md ./
RUN uv sync --frozen --no-install-project --no-dev
ENV PATH="/app/.venv/bin:${PATH}"

COPY bphs_core ./bphs_core
COPY app ./app

# The verified data files, from stage 1. bphs_core/utils.py computes EPHE_PATH
# as <package>/../data/ephe, which under WORKDIR /app is /app/data/ephe — so
# this destination is not arbitrary. Nothing needs to mount anything at
# runtime; a mount here would SHADOW these files and put the service back on
# the fallback (app/ephemeris_guard.py refuses to start if that happens).
COPY --from=ephemeris /fetch/data/ephe ./data/ephe

# Second `uv sync --frozen` installs the project itself (editable, into the venv
# from the first sync) now that its source is present — still frozen against the
# same committed lockfile, no re-resolution.
RUN uv sync --frozen --no-dev

EXPOSE 8000

RUN adduser --disabled-password --gecos '' appuser
USER appuser

# BUILD-TIME PROOF that swisseph actually reads the baked files, AS THE USER
# THAT SERVES REQUESTS.
#
# A successful COPY proves files were copied. It does NOT prove the engine uses
# them: a request that asks for FLG_SWIEPH with the data absent, unreadable, or
# at the wrong path still SUCCEEDS and returns a plausible position with
# FLG_MOSEPH set. Never infer "Swiss is active" from a call that did not raise
# — read the retflag bit, which is what probe_ephemeris_source() does.
#
# Placed AFTER `USER appuser`, deliberately, and this is not a detail. An
# earlier draft of this file ran the same assertion as root, above. It PASSED,
# the image contained all four data files — and `docker run` as appuser still
# reported retflag 65604, because the fetcher's tempfile left the files 0600
# and root could read what appuser could not. A control verified as a different
# principal than the one that runs in production is not verified. (The root
# cause is fixed in ci/fetch_swiss_ephemeris.py, which now chmods 0644; this
# placement is what would have caught it, and what catches the next one.)
#
# Both bodies are checked because the data set is split across files:
# sepl_18.se1 carries the planets and semo_18.se1 the Moon, so a Sun-only
# assertion passes on a data set that leaves every nakshatra, pada and dasha
# on the fallback. Failing HERE makes an image that computes on the fallback
# impossible to produce, rather than merely unlikely.
RUN python -c "import sys, swisseph as swe; from bphs_core.utils import probe_ephemeris_source; bad = [n for n, b in (('Sun', swe.SUN), ('Moon', swe.MOON)) if not probe_ephemeris_source(body=b)[0]]; sys.exit('FATAL: the baked Swiss ephemeris data is not being read by swisseph - it fell back to the Moshier engine for: ' + ', '.join(bad)) if bad else print('Swiss ephemeris data verified active (Sun, Moon)')"

# --timeout-keep-alive 75: the default (5s) closes idle keep-alive connections
# fast, which races clients that pool connections (the backend's CalcClient keeps
# up to 20) — a send on a just-closed connection surfaces as httpx.ReadError.
# A 75s idle keep-alive outlives typical client idle gaps and removes that race;
# the client also retries the residual case. Keep ≥ any upstream/LB idle timeout.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "75"]
