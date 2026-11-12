import math
import os
import subprocess
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bphs_core import compat as compat_mod
from bphs_core import dashas as dashas_mod
from bphs_core import event_clock, utils
from bphs_core import lagna_shuddhi as lagna_shuddhi_mod
from bphs_core import muhurat as muhurat_mod
from bphs_core import rashi_drishti as rashi_drishti_mod
from bphs_core import special_points as sp_mod
from bphs_core import strength as strength_mod
from bphs_core import transits as transits_mod
from bphs_core import vimshopaka as vimshopaka_mod
from bphs_core import yogas as yogas_mod
from bphs_core.chart import Chart, ChartSnapshot, PersonalData, PlanetData

# Boot guard, imported for its IMPORT-TIME EFFECT: it raises at import if a real
# deployment is running on the Moshier fallback rather than the baked Swiss data,
# so the service dies instead of serving charts computed on the wrong engine.
# The comment sits ABOVE the import rather than continuing beside it because
# import sorting moves the statement and leaves a trailing continuation line
# stranded behind it -- which is how this note briefly came to read as a stray
# sentence between two imports.
from . import ephemeris_guard  # noqa: F401
from .auth import require_token
from .jobs import job_store
from .schemas import (
    BhavabalaItem,
    ChartResponse,
    CompatRequest,
    CompatResponse,
    DashaOverlap,
    DashaPeriodOut,
    DashaRequest,
    FamilyLagnaShuddhiJobStatus,
    FamilyLagnaShuddhiRequest,
    FamilyLagnaShuddhiResponse,
    FamilyMemberSample,
    GocharaVedha,
    InduLagnaOut,
    JaiminiKaraka,
    JobSubmitted,
    KutaScore,
    LagnaShuddhiAlternative,
    LagnaShuddhiJobStatus,
    LagnaShuddhiRequest,
    LagnaShuddhiResponse,
    LagnaShuddhiSample,
    MangalDoshaResult,
    MuhurtRequest,
    MuhurtResponse,
    PersonalDataIn,
    PlanetPlacement,
    ProfileResponse,
    RashiDrishti,
    RashiDrishtiPlanet,
    ShadbalaItem,
    SourceInfo,
    SpecialPointsResponse,
    SphutaOut,
    StrengthResponse,
    TimeWindow,
    TransitPlanetPlacement,
    TransitRequest,
    TransitResponse,
    VimshopakaItem,
    YogaOut,
)


def _resolve_version() -> str:
    """Cache-invalidation key for the calc engine, resolved in priority order.

    ``GIT_COMMIT`` (set at image build time via the Dockerfile ARG/ENV, which
    the CI build populates with the building commit) is the *authoritative*
    value: the exact running-commit a downstream consumer can key its cache on.
    The in-container ``git rev-parse`` only fires for checkouts that still carry
    a ``.git`` directory (local development) — the published image has none.

    The source-content hash (``'src-' + sha256[:16]``) is a deterministic,
    logic-tracking fallback for local/dev images built without ``GIT_COMMIT``:
    it is *not* an authoritative commit, but it still changes whenever the calc
    logic changes, which is the only property a content-keyed cache relies on.

    The literal ``"unknown"`` is returned only if even the source tree is
    unreadable; it is the unresolved sentinel that signals to a downstream
    consumer that the version could not be determined and must be treated as
    non-cacheable (never substituted silently for a real commit).
    """
    commit = os.environ.get("GIT_COMMIT")
    if commit:
        return commit.strip()
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        pass
    try:
        import hashlib

        digest = hashlib.sha256()
        roots = [
            os.path.join(os.path.dirname(__file__), os.pardir, "bphs_core"),
            os.path.dirname(__file__),
        ]
        for root in roots:
            for dirpath, _dirs, files in os.walk(root):
                for fname in sorted(files):
                    if not fname.endswith(".py"):
                        continue
                    with open(os.path.join(dirpath, fname), "rb") as fh:
                        digest.update(fh.read())
        return "src-" + digest.hexdigest()[:16]
    except Exception:
        return "unknown"


_COMMIT = _resolve_version()


# The AGPL-3.0 source offer /source publishes. This literal is the DEFAULT, not
# the answer: it used to be written inline in the response constructor, reachable
# only as the second argument of an os.environ.get call, and a source offer that
# can only be changed by editing a handler is one that cannot follow its own
# repository. Nothing about a repository URL is permanent -- an owner rename, a
# move between accounts, a mirror change -- and none of those events touch this
# codebase, so the stale literal would keep being served and a recipient
# following it would get a 404 where the license promises the Corresponding
# Source. Naming it here makes the offer greppable and makes moving it a
# deliberate edit a reviewer can see, rather than a detail buried in a response.
DEFAULT_PUBLIC_SOURCE_URL = "https://github.com/aishwara-limited/open-vedic-calc"


def _source_url_rejection_reason(url: str) -> str | None:
    """Why *url* is unacceptable as this deployment's source offer, or None if it is fine.

    Pure helper so the policy is unit-testable without process-env gymnastics,
    the same shape ``app/auth.py::_token_weakness_reason`` takes for the service
    token. It strips before judging, so the verdict is a property of the value
    an operator meant to supply rather than of the padding it arrived with.

    Two rejections, both of them values that would boot green with the license
    obligation broken. **Blank** is the one this guard exists for: an
    unsubstituted template, a secret that resolved to nothing, or a dangling
    ``PUBLIC_SOURCE_URL=`` in an env file would otherwise serve
    ``{"source_url": ""}`` at HTTP 200 -- a control silently disabling itself
    when its input is absent, and reporting success. **Not a location** covers
    the rest of the same class (``TODO``, ``changeme``, a bare ``owner/repo``
    slug, a filesystem path): a recipient cannot fetch any of them either.

    What this deliberately does NOT do is claim the URL *resolves*. There is no
    reachability probe and no scheme allowlist, because the 404-after-a-move
    failure that motivates the whole change is invisible to any local check --
    a validator implying otherwise would buy the appearance of the property
    without the property. One consequence worth stating rather than leaving to
    be discovered: a ``mailto:`` written offer has a scheme but no host and is
    refused here. That is AGPL section 6(b) territory; the field this feeds is
    named ``source_url`` and documented as a URL a consumer fetches.
    """
    candidate = url.strip()
    if not candidate:
        return "empty or whitespace-only"
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        return f"not parseable as a URL ({exc})"
    if not parts.scheme or not parts.netloc:
        return "not an absolute URL -- it needs a scheme and a host, e.g. 'https://host/owner/repo'"
    return None


def _resolve_source_url() -> str:
    """This deployment's AGPL source offer, resolved once at import.

    Resolved at import rather than per request for the reason ``_COMMIT`` and
    ``_ALLOWED_ORIGINS`` are: a runtime ``os.environ`` mutation must not be able
    to change what a control serves mid-process, and a per-request read would
    make the refusal below unreachable -- a process that had already booted
    would simply start serving the blank offer.

    The unset/invalid boundary follows the precedent already set in this
    service, rather than inventing a third convention. **Unset** takes the
    built-in default, because unlike a secret there IS a correct compiled-in
    answer -- the shape ``ALLOWED_ORIGINS`` (absent means the empty allow-list)
    and ``GIT_COMMIT`` (absent means fall through to the next resolver) already
    take. **Set and invalid** raises, in every environment, which is the shape
    the wildcard-``ALLOWED_ORIGINS`` guard takes: a present-and-wrong value is
    an operator error. It is deliberately not gated on ``is_real_deployment()``
    the way the ``CALC_SERVICE_TOKEN`` guard is -- a developer box legitimately
    runs without a token, but no environment legitimately wants a blank source
    offer, and a fail-closed control that stands down in three environment
    names is one that was never tested where it matters.
    """
    configured = os.environ.get("PUBLIC_SOURCE_URL")
    if configured is None:
        return DEFAULT_PUBLIC_SOURCE_URL
    reason = _source_url_rejection_reason(configured)
    if reason:
        raise RuntimeError(
            f"PUBLIC_SOURCE_URL is {reason}: {configured!r}. This service refuses to start "
            "rather than serve a blank or unusable AGPL-3.0 source offer -- a recipient "
            "following it would get nothing where the license promises the Corresponding "
            "Source. Set PUBLIC_SOURCE_URL to the URL where this deployment publishes its "
            "source, or unset it entirely to fall back to the built-in default "
            f"({DEFAULT_PUBLIC_SOURCE_URL})."
        )
    return configured.strip()


_SOURCE_URL = _resolve_source_url()

_ALLOWED_ORIGINS = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o]

# CALC-4: CLAUDE.md's CORS rule ("do not introduce a wildcard origin") was
# documented but never enforced -- ALLOWED_ORIGINS flowed straight into
# CORSMiddleware with no validation, so a deploy-time typo/copy-paste of
# ALLOWED_ORIGINS=* would silently open the API to any browser origin with
# no test or startup check catching it. Fail closed at import time, the same
# way app.auth refuses to boot on a missing/weak CALC_SERVICE_TOKEN, rather
# than waiting for the first request.
for _origin in _ALLOWED_ORIGINS:
    if _origin.strip() == "*":
        raise RuntimeError(
            f"ALLOWED_ORIGINS contains a bare wildcard origin ('*') in "
            f"{os.environ.get('ALLOWED_ORIGINS', '')!r}. A wildcard CORS "
            "origin is never permitted -- set ALLOWED_ORIGINS to an explicit "
            "comma-separated list of allowed origins."
        )

MAX_MUHURAT_DAYS = int(os.environ.get("MAX_MUHURAT_DAYS", "365"))
MAX_LAGNA_SHUDDHI_DAYS = int(os.environ.get("MAX_LAGNA_SHUDDHI_DAYS", "365"))
# Vimshottari is a 120-year (43,830-day) cycle.  The cap must be large enough
# to pass a full-life request (birth → birth+120y) without truncation.  47,000
# days (~128.6 years) gives the 120-year cycle plus headroom for the elapsed-
# fraction back-dating (up to ~20 years × 365.25 days).  This is intentionally
# NOT the 365-day muhurat value — a sub-120-year cap would reject every
# full-life dasha request.
MAX_DASHA_DAYS = int(os.environ.get("MAX_DASHA_DAYS", "47000"))

app = FastAPI(
    title="Open Vedic Calc",
    description="Generic BPHS calculation service — AGPL-3.0",
    version="1.0.0",
    # FR-MED-22: every business route is gated by the require_token dependency,
    # but FastAPI's auto-generated docs/schema endpoints are not routes with
    # that dependency attached -- they are wired by the FastAPI app object
    # itself, so leaving them enabled exposes the full API schema (including
    # internal field names/bounds) to anyone with network reach, with no
    # token required. Disable them; /healthz stays open by design (see below).
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively coerce values that would crash json.dumps into safe forms.

    FastAPI's default RequestValidationError handler includes the raw input
    and ctx.error values in the error body. These can be:
    - Non-finite floats (NaN, ±Infinity) — not valid JSON
    - Python exception objects in the ctx["error"] slot — not JSON-serializable

    Both are converted to their string representation so the 422 response
    can always be serialized.
    """
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    # Pydantic v2 puts the original exception object in ctx["error"]. The
    # standard json encoder cannot serialize Exception instances, so stringify.
    if isinstance(obj, Exception):
        return str(obj)
    return obj


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return a well-formed 422 even when input contains non-finite floats.

    The default FastAPI handler includes the raw input in the error detail,
    which crashes json.dumps when the input is NaN or ±Infinity. We sanitize
    before serializing so the 422 is always delivered (never silently becomes
    a 500 that obscures the schema rejection).
    """
    sanitized = _sanitize_for_json(exc.errors())
    return JSONResponse(status_code=422, content={"detail": sanitized})


# Stable, machine-readable discriminator carried in the error body so the HTTP
# caller can branch on this specific failure class without string-matching a
# human message. Part of the wire contract — see the handler below.
MUHURAT_LIMB_ERROR_CODE = "muhurat_limb_error"


@app.exception_handler(muhurat_mod.MuhurtaLimbError)
async def _muhurat_limb_error_handler(
    request: Request, exc: muhurat_mod.MuhurtaLimbError
) -> JSONResponse:
    """Surface a recommendation-affecting limb failure as a structured 422.

    ``bphs_core.muhurat`` RAISES ``MuhurtaLimbError`` (project decision
    2026-08-17) for every limb that decides WHICH time can be recommended,
    rather than fabricating a day frame the caller cannot distinguish from a
    real one. On a synchronous route that exception would otherwise propagate
    as an opaque 500, so the caller could not tell WHICH limb failed. This
    handler maps it into the same ``{"detail": ...}`` envelope the validation
    handler above uses, carrying the limb name, the target date and the stable
    ``code`` so the caller can branch on the failure precisely — never a 200
    masking an empty/partial muhurat list, never an opaque 500.

    422 (Unprocessable), not a 5xx, matches this service's existing convention:
    every "well-formed request the engine cannot fulfil" here (date-range caps,
    end-before-start, member counts, invalid activity) is already a 422, and a
    limb that cannot be computed for the requested date/place is the same class
    of outcome — deterministic, so retrying the identical request cannot change
    it. The failure is still logged server-side at ERROR with the originating
    traceback at the raise site (``muhurat._require``), so mapping it to 422
    loses no observability.

    Registered against the exception class, so it fires wherever a limb error
    reaches the request/response cycle (the ``/v1/muhurat`` sync route and the
    synchronous lagna-shuddhi routes alike). It does NOT fire on the async
    scan-job path: that path captures every exception into ``job.error`` on its
    background thread (see ``app/jobs.py``), which never enters this cycle.
    """
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": MUHURAT_LIMB_ERROR_CODE,
                "limb": exc.limb,
                "target_date": exc.target_date.strftime("%Y-%m-%d"),
                "message": str(exc),
            }
        },
    )


AUTH = [Depends(require_token)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_personal_data(p: PersonalDataIn) -> PersonalData:
    return PersonalData(
        name=p.name,
        birth_date=datetime.combine(p.birth_date, datetime.min.time()),
        birth_time=p.birth_time,
        birth_place=p.birth_place,
        latitude=p.latitude,
        longitude=p.longitude,
        timezone_offset_hours=p.timezone_offset_hours,
    )


def _pd_to_schema(pd: PlanetData) -> PlanetPlacement:
    is_gandanta, gandanta_proximity = utils.check_gandanta(pd.sign, pd.degrees)
    total_lon = (utils.SIGNS.index(pd.sign) * 30 + pd.degrees) % 360
    pada_lord = utils.nakshatra_pada_lord(total_lon)
    return PlanetPlacement(
        planet=pd.planet, sign=pd.sign, degrees=pd.degrees,
        nakshatra=pd.nakshatra, dignity=pd.dignity, house=pd.house,
        conjunctions=pd.conjunctions, aspects=pd.aspects,
        is_retrograde=pd.is_retrograde,
        is_gandanta=is_gandanta,
        gandanta_proximity_degrees=gandanta_proximity if is_gandanta else None,
        is_combust=pd.is_combust,
        combust_proximity_degrees=pd.combust_proximity_degrees,
        chalit_house=pd.chalit_house,
        pada_lord=pada_lord,
    )


def _chart_to_response(s: ChartSnapshot) -> ChartResponse:
    def to_list(varga: dict) -> list[PlanetPlacement]:
        return [_pd_to_schema(pd) for pd in varga.values()]

    rashi_drishti = RashiDrishti(
        sign_table=rashi_drishti_mod.get_rashi_drishti_table(),
        per_planet=[
            RashiDrishtiPlanet(
                planet=p.planet, sign=p.sign,
                aspects_signs=p.aspects_signs, aspects_planets=p.aspects_planets,
            )
            for p in rashi_drishti_mod.get_planet_rashi_drishti(s)
        ],
    )

    return ChartResponse(
        lagna=s.lagna, lagna_lord=s.lagna_lord,
        yoga_karaka=yogas_mod.get_yoga_karaka_planet(s),
        ayanamsa_value=s.ayanamsa_value,
        house_system=s.house_system,
        bhava_chalit_cusps=[round(c, 6) for c in s.chalit_cusps],
        rashi_drishti=rashi_drishti,
        rasi=to_list(s.rasi_chart),
        hora=to_list(s.hora_chart),
        drekkana=to_list(s.drekkana_chart),
        saptamsa=to_list(s.saptamsa_chart),
        navamsa=to_list(s.navamsa_chart),
        decamsa=to_list(s.decamsa_chart),
        dwadasamsa=to_list(s.dwadasamsa_chart),
        shodasamsa=to_list(s.shodasamsa_chart),
        chaturvimsa=to_list(s.chaturvimsa_chart),
        trimshamsa=to_list(s.trimshamsa_chart),
        shashtyamsa=to_list(s.shashtyamsa_chart),
    )


def _get_chart(p: PersonalDataIn) -> tuple[Chart, ChartSnapshot]:
    person = _to_personal_data(p)
    chart = Chart(person)
    return chart, chart.snapshot()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/v1/chart", response_model=ChartResponse, dependencies=AUTH)
def chart_endpoint(p: PersonalDataIn):
    _, s = _get_chart(p)
    return _chart_to_response(s)


@app.post("/v1/strength", response_model=StrengthResponse, dependencies=AUTH)
def strength_endpoint(p: PersonalDataIn):
    _, s = _get_chart(p)

    planets_with_shadbala = [
        pl for pl in strength_mod.SHADBALA_MINIMUMS if pl in s.rasi_chart
    ]
    shadbala = [
        ShadbalaItem(**vars(strength_mod.compute_shadbala(s, pl)))
        for pl in planets_with_shadbala
    ]
    bhavabala = [
        BhavabalaItem(**vars(r))
        for r in strength_mod.compute_all_bhavabala(s)
    ]
    akv = strength_mod.compute_ashtakavarga(s)

    vimshopaka = {
        r.planet: VimshopakaItem(
            total=r.total, grade=r.grade, contributions=r.contributions,
        )
        for r in vimshopaka_mod.compute_all_vimshopaka(s)
    }

    return StrengthResponse(
        shadbala=shadbala,
        bhavabala=bhavabala,
        ashtakavarga=akv,
        vimshopaka=vimshopaka,
    )


@app.post("/v1/dashas", response_model=list[DashaPeriodOut], dependencies=AUTH)
def dashas_endpoint(req: DashaRequest):
    start = datetime.strptime(req.from_date, "%Y-%m-%d")
    end = datetime.strptime(req.to_date, "%Y-%m-%d")
    if end < start:
        raise HTTPException(status_code=422, detail="to_date must be on or after from_date")
    # Cap measured from birth date, not from_date.  The real cost driver in
    # vimshottari_mahadashas is cycle_count, which scales with (to_date - BIRTH),
    # not (to_date - from_date).  A narrow far-future window (e.g. 9900→9999) with
    # a normal birth can still force dozens of cycles from birth before window-
    # filtering; capping from birth directly bounds cycle_count to ≈3 regardless
    # of from_date.  Birth→birth+120y is 43,830 days < 47,000, so every legitimate
    # full-life request still passes.
    birth_dt = datetime.combine(req.birth_date, datetime.min.time())
    if (end - birth_dt).days > MAX_DASHA_DAYS:
        raise HTTPException(status_code=422, detail=f"Date range exceeds {MAX_DASHA_DAYS} days")
    _, s = _get_chart(req)
    periods = dashas_mod.get_dasha_timeline(s, start, end, req.systems)
    return [
        DashaPeriodOut(
            lord=d.lord, level=d.level, system=d.system,
            start_date=d.start_date, end_date=d.end_date,
            duration_years=d.duration_years,
        )
        for d in periods
    ]


@app.post("/v1/yogas", response_model=list[YogaOut], dependencies=AUTH)
def yogas_endpoint(p: PersonalDataIn):
    _, s = _get_chart(p)
    yogas = yogas_mod.detect_all_yogas(s)
    return [
        YogaOut(
            name=y.name, description=y.description,
            planets_involved=y.planets_involved,
            houses_involved=y.houses_involved,
            strength=y.strength,
            is_viparita_raja=y.is_viparita_raja,
            activating_lords=y.activating_lords,
        )
        for y in yogas
    ]


@app.post("/v1/transits", response_model=TransitResponse, dependencies=AUTH)
def transits_endpoint(req: TransitRequest):
    _, s = _get_chart(req)
    at = datetime.strptime(req.at_date, "%Y-%m-%d")

    current = transits_mod.get_current_transits(s, at,
                                                 timezone_offset_hours=req.timezone_offset_hours)
    saturn = current.get("Saturn")
    jupiter = current.get("Jupiter")

    signals = transits_mod.compute_transit_signals(s, current)
    houses_lagna = transits_mod.compute_house_from_lagna(s, current)
    planets = [
        TransitPlanetPlacement(
            planet=tp.planet, sign=tp.sign, degrees=tp.degrees, nakshatra=tp.nakshatra,
            house_from_lagna=houses_lagna.get(tp.planet),
            house_from_moon=signals.get(tp.planet, {}).get("house_from_moon"),
            favourable=signals.get(tp.planet, {}).get("favourable"),
            bindu_score=signals.get(tp.planet, {}).get("bindu_score"),
        )
        for tp in current.values()
    ]

    sade_sati = transits_mod.get_sade_sati_info(s, at)

    saturn_vedha = transits_mod.check_ashtakavarga_vedha(s, "Saturn",
                                                          saturn.sign if saturn else "")
    jupiter_vedha = transits_mod.check_ashtakavarga_vedha(s, "Jupiter",
                                                           jupiter.sign if jupiter else "")

    gochara_vedha = [
        GocharaVedha(
            blocked_planet=v.blocked_planet,
            blocking_planet=v.blocking_planet,
            blocked_house=v.blocked_house,
            vedha_house=v.vedha_house,
            neutralised=v.neutralised,
        )
        for v in transits_mod.compute_gochara_vedha(s, current)
    ]

    derived = transits_mod.compute_transit_derived(s, current)

    return TransitResponse(
        planets=planets,
        sade_sati_active=sade_sati.is_active,
        sade_sati_phase=sade_sati.phase if sade_sati.is_active else None,
        saturn_vedha_blocked=saturn_vedha,
        jupiter_vedha_blocked=jupiter_vedha,
        gochara_vedha=gochara_vedha,
        chandrashtama=derived["chandrashtama"],
        dhaiya_active=derived["dhaiya_active"],
        dhaiya_phase=derived["dhaiya_phase"],
    )


@app.post("/v1/special-points", response_model=SpecialPointsResponse, dependencies=AUTH)
def special_points_endpoint(p: PersonalDataIn):
    _, s = _get_chart(p)
    karakas_raw = sp_mod.get_jaimini_karakas(s)

    indu = sp_mod.get_indu_lagna(s)
    beeja = sp_mod.get_beeja_sphuta(s)
    kshetra = sp_mod.get_kshetra_sphuta(s)

    def _sphuta_out(sp) -> SphutaOut:
        return SphutaOut(
            longitude=sp.longitude, sign=sp.sign, navamsa_sign=sp.navamsa_sign,
            sign_parity=sp.sign_parity, navamsa_parity=sp.navamsa_parity,
            strength=sp.strength, sign_lord=sp.sign_lord,
            sign_lord_dignity=sp.sign_lord_dignity,
        )

    return SpecialPointsResponse(
        arudha_lagna=sp_mod.get_arudha_lagna(s).sign,
        upapada=sp_mod.get_upapada(s).sign,
        atmakaraka=sp_mod.get_atmakaraka(s),
        karakamsa=sp_mod.get_karakamsa(s).sign,
        jaimini_karakas=[JaiminiKaraka(**k) for k in karakas_raw],
        indu_lagna=InduLagnaOut(
            sign=indu.sign, house_from_lagna=indu.house_from_lagna,
            occupants=indu.occupants, lord=indu.lord,
            lord_dignity=indu.lord_dignity, lord_house=indu.lord_house,
        ),
        beeja_sphuta=_sphuta_out(beeja),
        kshetra_sphuta=_sphuta_out(kshetra),
    )


@app.post("/v1/profile", response_model=ProfileResponse, dependencies=AUTH)
def profile_endpoint(p: PersonalDataIn):
    from bphs_core.profile import compute_profile
    _, s = _get_chart(p)
    result = compute_profile(s, p.birth_date, name=p.name)
    return ProfileResponse(**result)


@app.post("/v1/muhurat", response_model=MuhurtResponse, dependencies=AUTH)
def muhurat_endpoint(req: MuhurtRequest):
    _, s = _get_chart(req)

    # Extract natal Moon's nakshatra and sign from Rasi chart
    moon_pd = s.rasi_chart.get("Moon")
    birth_nak = moon_pd.nakshatra if moon_pd else None
    birth_sign = moon_pd.sign if moon_pd else None

    # Parse date range
    start_dt = datetime.strptime(req.start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(req.end_date, "%Y-%m-%d").date()
    if end_dt < start_dt:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")
    if (end_dt - start_dt).days > MAX_MUHURAT_DAYS:
        raise HTTPException(status_code=422, detail=f"Date range exceeds {MAX_MUHURAT_DAYS} days")

    days = []
    curr = start_dt
    # The event's place and zone when given; else the person's own coordinates
    # and fixed offset. Each date is read on the offset in force on that date.
    lat, lon = req.event_coordinates(req.latitude, req.longitude)
    clock = event_clock.make_clock(req.timezone_offset_hours, req.event_timezone)

    while curr <= end_dt:
        place = utils.make_place(req.name, lat, lon, clock.offset_for(curr))
        day_data = muhurat_mod.compute_muhurat_for_day(
            place=place,
            target_date=curr,
            birth_nakshatra=birth_nak,
            birth_moon_sign=birth_sign
        )
        days.append(day_data)
        curr += timedelta(days=1)

    return MuhurtResponse(days=days)


# ---------------------------------------------------------------------------
# Shared scan pipeline for the lagna-shuddhi endpoint pairs.
#
# Each ``_prepare_*`` helper performs ALL request validation (raising 422 to
# the caller immediately, for the async submit as well as the sync call) and
# the natal-Moon extraction, then returns a zero-arg callable that runs the
# scan and assembles the response model. The sync endpoint invokes the
# callable inline; the async submit hands the SAME callable to the job store.
# One pipeline means a validation or assembly change lands once and applies
# to both paths by construction — the parity tests in
# tests/test_async_scan_jobs.py then verify output equality end-to-end.
# ---------------------------------------------------------------------------

MAX_FAMILY_MEMBERS = 6


def _validate_lagna_shuddhi_range(start_date: str, end_date: str) -> None:
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end_dt < start_dt:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")
    if (end_dt - start_dt).days > MAX_LAGNA_SHUDDHI_DAYS:
        raise HTTPException(status_code=422, detail=f"Date range exceeds {MAX_LAGNA_SHUDDHI_DAYS} days")


def _natal_moon(person) -> tuple[str | None, str | None]:
    """Extract (nakshatra, sign) of the natal Moon from a person's chart."""
    _, s = _get_chart(person)
    moon_pd = s.rasi_chart.get("Moon")
    return (
        moon_pd.nakshatra if moon_pd else None,
        moon_pd.sign if moon_pd else None,
    )


def _prepare_lagna_shuddhi(req: LagnaShuddhiRequest):
    """Validate ``req`` (422 now) and return the scan runnable."""
    _validate_lagna_shuddhi_range(req.start_date, req.end_date)
    birth_nak, birth_sign = _natal_moon(req)
    lat, lon = req.event_coordinates(req.latitude, req.longitude)

    def _run_scan() -> LagnaShuddhiResponse:
        result = lagna_shuddhi_mod.scan_lagna_shuddhi(
            lat=lat,
            lon=lon,
            tz_offset=req.timezone_offset_hours,
            birth_nakshatra=birth_nak,
            birth_moon_sign=birth_sign,
            start_date=req.start_date,
            end_date=req.end_date,
            activity=req.activity_category,
            step_seconds=req.step_seconds,
            tz_name=req.event_timezone,
        )
        best_raw = result["best_instant"]
        best_window_raw = result["best_window"]
        top_raw = result["top_samples"]

        def _to_sample(d: dict) -> LagnaShuddhiSample:
            return LagnaShuddhiSample(**d)

        return LagnaShuddhiResponse(
            best_instant=_to_sample(best_raw) if best_raw else None,
            best_window=TimeWindow(**best_window_raw) if best_window_raw else None,
            top_samples=[_to_sample(d) for d in top_raw],
            clearance_summary=result.get("clearance_summary"),
            alternatives=[LagnaShuddhiAlternative(**a) for a in result.get("alternatives", [])],
        )

    return _run_scan


def _prepare_family_lagna_shuddhi(req: FamilyLagnaShuddhiRequest):
    """Validate ``req`` (422 now) and return the family-scan runnable."""
    if len(req.members) < 2:
        raise HTTPException(status_code=422, detail="At least 2 members required")
    if len(req.members) > MAX_FAMILY_MEMBERS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_FAMILY_MEMBERS} members allowed")
    _validate_lagna_shuddhi_range(req.start_date, req.end_date)

    # Build per-member dicts for the scan, extracting natal Moon from chart.
    # With an event place every member is scored at that one place, in that one
    # zone, so one wall time is one absolute instant for the whole group; each
    # member's natal Moon still comes from their own birth chart.
    member_dicts = []
    for m in req.members:
        birth_nak, birth_sign = _natal_moon(m)
        lat, lon = req.event_coordinates(m.latitude, m.longitude)
        member_dicts.append({
            "name": m.name,
            "lat": lat,
            "lon": lon,
            "tz_offset": m.timezone_offset_hours,
            "tz_name": req.event_timezone,
            "birth_nakshatra": birth_nak,
            "birth_moon_sign": birth_sign,
        })

    def _run_scan() -> FamilyLagnaShuddhiResponse:
        result = lagna_shuddhi_mod.scan_family_lagna_shuddhi(
            members=member_dicts,
            start_date=req.start_date,
            end_date=req.end_date,
            activity=req.activity_category,
            step_seconds=req.step_seconds,
        )
        per_member_out = [FamilyMemberSample(**md) for md in result["per_member"]]
        best_window_raw = result["best_window"]

        return FamilyLagnaShuddhiResponse(
            instant=result["instant"],
            best_window=TimeWindow(**best_window_raw) if best_window_raw else None,
            score=result["score"],
            score_100=result["score_100"],
            band=result["band"],
            per_member=per_member_out,
            consensus_quality=result["consensus_quality"],
            compromised_members=result["compromised_members"],
            clearance_summary=result.get("clearance_summary"),
            alternatives=[LagnaShuddhiAlternative(**a) for a in result.get("alternatives", [])],
        )

    return _run_scan


@app.post("/v1/muhurat/lagna-shuddhi", response_model=LagnaShuddhiResponse, dependencies=AUTH)
def lagna_shuddhi_endpoint(req: LagnaShuddhiRequest):
    return _prepare_lagna_shuddhi(req)()


@app.post("/v1/muhurat/family-lagna-shuddhi", response_model=FamilyLagnaShuddhiResponse, dependencies=AUTH)
def family_lagna_shuddhi_endpoint(req: FamilyLagnaShuddhiRequest):
    return _prepare_family_lagna_shuddhi(req)()


# ---------------------------------------------------------------------------
# Async scan-job variant (CR-4) -- ADDITIVE ONLY.
#
# The submit/poll pair below is a parallel path for the same two scans that
# hands back a job id immediately instead of blocking the caller's connection
# for the full scan duration (see app/jobs.py for why, and the concurrency
# model used). Validation runs at submit time (422 to the caller); only the
# scan itself runs on the background pool. Both paths share the exact same
# ``_prepare_*`` pipeline above, so they cannot drift apart.
# ---------------------------------------------------------------------------

@app.post(
    "/v1/muhurat/lagna-shuddhi/async",
    response_model=JobSubmitted,
    status_code=202,
    dependencies=AUTH,
)
def lagna_shuddhi_async_submit(req: LagnaShuddhiRequest):
    job_id = job_store.submit(_prepare_lagna_shuddhi(req))
    return JobSubmitted(job_id=job_id, status="pending")


@app.get(
    "/v1/muhurat/lagna-shuddhi/jobs/{job_id}",
    response_model=LagnaShuddhiJobStatus,
    dependencies=AUTH,
)
def lagna_shuddhi_job_status(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return LagnaShuddhiJobStatus(
        job_id=job.id,
        status=job.status,
        result=job.result if job.status == "done" else None,
        error=job.error,
    )


@app.post(
    "/v1/muhurat/family-lagna-shuddhi/async",
    response_model=JobSubmitted,
    status_code=202,
    dependencies=AUTH,
)
def family_lagna_shuddhi_async_submit(req: FamilyLagnaShuddhiRequest):
    job_id = job_store.submit(_prepare_family_lagna_shuddhi(req))
    return JobSubmitted(job_id=job_id, status="pending")


@app.get(
    "/v1/muhurat/family-lagna-shuddhi/jobs/{job_id}",
    response_model=FamilyLagnaShuddhiJobStatus,
    dependencies=AUTH,
)
def family_lagna_shuddhi_job_status(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return FamilyLagnaShuddhiJobStatus(
        job_id=job.id,
        status=job.status,
        result=job.result if job.status == "done" else None,
        error=job.error,
    )


@app.post("/v1/compat", response_model=CompatResponse, dependencies=AUTH)
def compat_endpoint(req: CompatRequest):
    _, snap_a = _get_chart(req.person_a)
    _, snap_b = _get_chart(req.person_b)
    result = compat_mod.compute_compat(snap_a, snap_b, req.reference_date or date.today())

    kutas = [
        KutaScore(name=k.name, score=k.score, max_score=k.max_score,
                  interpretation=k.interpretation)
        for k in result.kutas
    ]
    dosha_a = MangalDoshaResult(
        has_dosha=result.mangal_dosha_a.has_dosha,
        severity=result.mangal_dosha_a.severity,
        cancellation=result.mangal_dosha_a.cancellation,
    )
    dosha_b = MangalDoshaResult(
        has_dosha=result.mangal_dosha_b.has_dosha,
        severity=result.mangal_dosha_b.severity,
        cancellation=result.mangal_dosha_b.cancellation,
    )
    overlaps = [
        DashaOverlap(
            start_date=o.start_date, end_date=o.end_date,
            person_a_lord=o.person_a_lord, person_b_lord=o.person_b_lord,
            quality=o.quality,
        )
        for o in result.dasha_overlaps
    ]
    return CompatResponse(
        total_score=result.total_score,
        max_score=result.max_score,
        kutas=kutas,
        mangal_dosha_a=dosha_a,
        mangal_dosha_b=dosha_b,
        nakshatra_compatibility=result.nakshatra_compatibility,
        dasha_overlaps=overlaps,
        composite_strength_notes=result.composite_strength_notes,
    )


# Intentionally unauthenticated: this is the container liveness probe. The
# docker-compose healthchecks and any orchestrator startup probe hit /healthz
# with no Authorization header, and the service runs on internal-only ingress.
# The body carries no sensitive data — only a status string and a boolean for
# whether the ephemeris data is genuinely in use.
#
# CALC-1: ``ephe_loaded`` used to be ``os.path.isdir(data/ephe)`` -- True for
# an EMPTY directory (exactly what `mkdir -p data/ephe` in the Dockerfile
# leaves behind before any volume mount), so this probe reported healthy the
# entire time every worker thread was silently computing on the Moshier
# fallback (see bphs_core/utils.py for the root cause). It now derives the
# signal from the same retflag evidence the accuracy gate uses --
# ``utils.probe_ephemeris_source()`` asks swisseph directly and reads the
# FLG_SWIEPH/FLG_MOSEPH bit, so a mounted-but-empty or otherwise unusable
# ephemeris directory reports False instead of a false "ok".
#
# ``status`` now FOLLOWS ``ephe_loaded`` instead of being the constant "ok".
# It was the constant, so this endpoint asserted health while every chart came
# from the fallback -- measured 2026-07-31 against the image digest the staging
# revision was serving: ``200 {"status":"ok","ephe_loaded":false}``. A probe
# that passes with the control off is not a probe.
#
# The HTTP status stays 200 deliberately, and the STATUS STRING carries the
# signal. ``app/ephemeris_guard.py`` refuses to start a real deployment on the
# fallback at all, so "degraded" is only ever reachable in
# development/local/test -- the environments that deliberately tolerate the
# fallback, where the suite itself runs. A 503 there would break the
# docker-compose healthcheck and the dev loop while buying no accuracy in any
# environment that serves anyone. tests/test_ephemeris_baked.py pins both halves.
@app.get("/healthz")
def healthz():
    ephe_ok, _retflag = utils.probe_ephemeris_source()
    return {"status": "ok" if ephe_ok else "degraded", "ephe_loaded": ephe_ok}


# Authenticated: provenance (commit + source URL) is served only to the
# bearer-token-holding backend. The public AGPL source offer is the public
# GitHub repository, not this internal endpoint.
#
# ``ephe_loaded``/``ephemeris_source`` are carried HERE, not only on /healthz,
# because /healthz is not reachable through Cloud Run's frontend: it answers
# that path itself with a Google 404 that never reaches this container
# (measured 2026-07-31 -- /healthz returns Google's "Error 404 (Not Found)!!1"
# page while other unmatched paths return a different 404 body). A consumer
# that must FAIL A DEPLOY on this signal therefore has to read it from an
# endpoint that actually arrives, and /source is the one such consumers already
# use. Same canonical detector as /healthz -- never a second copy of the
# retflag classification.
#
# ``source_url`` is the module-level value resolved and validated at import by
# ``_resolve_source_url``, never a literal and never a fresh ``os.environ`` read.
# Both halves matter: a literal here cannot follow the repository when it moves,
# and an inline read would let a mid-process mutation change the license offer
# and would put a blank offer on the wire in a process the import-time guard
# already let boot.
@app.get("/source", response_model=SourceInfo, dependencies=AUTH)
def source():
    ephe_ok, _retflag = utils.probe_ephemeris_source()
    return SourceInfo(
        source_url=_SOURCE_URL,
        commit=_COMMIT,
        ephe_loaded=ephe_ok,
        ephemeris_source="swiss" if ephe_ok else "moshier",
    )
