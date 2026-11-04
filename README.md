# Open Vedic Calc

A generic, stateless HTTP service for Vedic astrology (BPHS) calculations.

Computes planetary positions, divisional charts, Shadbala, Bhavabala, Ashtakavarga,
dasha periods, yogas, transits, and special points from birth data.

**License:** AGPL-3.0. Full source available at this repository.

## Self-hosting

```bash
uv sync --frozen        # the exact set in uv.lock, on the interpreter in .python-version
uv run --frozen uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`--frozen` is not incidental, and neither is the interpreter. A universal
`uv.lock` can fork on the interpreter, and this one did at Python 3.11 while
`requires-python` still admitted 3.10 — `numpy` resolved to 2.2.6 below it and
2.4.6 at or above, `timezonefinder` to 8.2.0 and 8.2.5 — and wherever the lock
forks, "the locked set" does not name a single set of versions until the
interpreter is fixed. Even without a fork, the interpreter decides which wheels
and marker-gated packages install, so a base-image tag edit changes what
installs while `pyproject.toml` and `uv.lock` stay byte-identical. That is why
`.python-version` exists, why `requires-python` is exactly `>=` that interpreter,
and why the images, CI and the command above all read it instead of each naming
a version of their own.

Neither package that forked is reached by the compute path as the code stands,
which was measured rather than assumed — with the instrument proven live first,
then counted across every route this service serves and the full test suite:
numpy is called exactly twice, both times at import, building one constant
lookup table inside a dependency — a table measured identical on both sides of
that fork.
So the pin is here to install the set these values were recorded against, not to
guard numpy arithmetic. A floating `pip install -e .` resolves whatever is newest
today instead — measured, that differed from the shipped image on 13 packages
that actually ship.

Developing on it? Add the test extras and run the suite the way CI runs it:

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/ -q
uv run --frozen pytest ci/tests/ -q
```

Set the following environment variables:

```
CALC_SERVICE_TOKEN=<any secret>
PUBLIC_SOURCE_URL=https://github.com/aishwara-limited/open-vedic-calc
```

`PUBLIC_SOURCE_URL` is the AGPL-3.0 source offer `GET /source` publishes — where
the Corresponding Source for *your* running instance can be obtained. It is
**optional**: leave it unset and the service serves the built-in default shown
above. Set it when you run a fork or a mirror, so the offer names source a
recipient of your instance can actually fetch.

It must not be blank. An empty, whitespace-only, or non-URL value makes the
service **refuse to start**, in every environment, rather than answer `/source`
with an offer that leads nowhere — a recipient following a blank or broken offer
gets nothing where the license promises code, which is worse than a container
that fails loudly at boot.

Swiss Ephemeris data files: **nothing to do if you run the Docker images.**
`Dockerfile` and `Dockerfile.test` fetch and checksum-verify them during the
build and bake them into `/app/data/ephe`. Do not mount a volume over that
path — it shadows the baked files, and swisseph responds by silently computing
on its built-in Moshier fallback rather than raising.

Running from a source checkout instead (`uvicorn app.main:app`)? Fetch them once:

```
python ci/fetch_swiss_ephemeris.py
```

See `EPHEMERIS_LICENSE.md`.

## Astronomical conventions

Two engines can both be defensible and still disagree, because Vedic astrology has
genuine methodological choices. This service makes them explicitly, so a number
that differs from another tool can be explained rather than guessed at:

| Choice | This service | Where it is set |
|---|---|---|
| Ayanamsa | **Lahiri** (Chitrapaksha) | `bphs_core/utils.py` |
| Lunar nodes (Rahu / Ketu) | **True (osculating) node**; Ketu = Rahu + 180° | `bphs_core/utils.py`, `LUNAR_NODE_MODEL` |
| Planetary position frame | **Geometric** (`FLG_TRUEPOS`), sidereal, geocentric — flag word `65810` | `bphs_core/utils.py`, `POSITION_FLAGS` |
| Primary house frame | **Whole-sign**, counted from the lagna sign | `bphs_core/chart.py` |
| Bhava-Chalit cusps | Sidereal **Placidus**, supplementary only | `chalit_cusps` in the chart response |
| Ascendant | Computed directly from `swe.houses`, not from the chart library | `bphs_core/chart.py` |
| Sunrise / sunset | **Disc centre at the true (geometric) horizon** — the classical Hindu convention; `rsmi` words `897` / `898` | `bphs_core/utils.py`, `RISE_FLAGS` / `SET_FLAGS` |
| Ephemeris | Swiss Ephemeris data files; served date range **1800-01-02 … 2400-01-09**, narrowing to **… 2399-12-01** for the electional scan fields | baked into the images; bound in `app/schemas.py` |

That range is the **measured** span of the shipped data files, not the
"AD 1800–2400" label on them. The files stop answering on 2400-01-11, and
swisseph does not error when they do — it silently substitutes its built-in
Moshier ephemeris and returns a plausible result anyway. Rather than serve the
tail off the fallback at HTTP 200 with nothing saying so, dates outside the
measured span are refused with a 422. The bound holds one further day of margin
at each end because a local date spans UTC instants a day either side once
`timezone_offset_hours` is applied. See `EPHEMERIS_LICENSE.md` for the
measurement.

**Every** date a caller can send is bounded — all ten beyond `birth_date` — but
they are bounded by **two** spans, not one, because a *point lookup* and a
*scanned day* ask different amounts of the same files.

**Point-lookup fields — 1800-01-02 … 2400-01-09.** `at_date` (`/v1/transits`),
`from_date` / `to_date` (`/v1/dashas`), and the optional `reference_date` on
`/v1/compat`. These read the instant they name, so the span above — the data,
plus a day of timezone margin at each end — is exactly right for them. Measured,
a transit request reads at most 0.583 d past `at_date`, which is just the
timezone offset.

**Scanned-day fields — 1800-01-02 … 2399-12-01.** The `start_date` / `end_date`
pairs on `/v1/muhurat`, `/v1/muhurat/lagna-shuddhi` and
`/v1/muhurat/family-lagna-shuddhi` (including their `/async` submit forms). A
scanned day is **not** a point lookup: deciding whether its lunar month is
intercalary needs the new moons bracketing it, and the yoga limb searches
similarly, so computing one day reads up to **~32 days around it** — measured
+31.835 d forward at the furthest. Bounding these to the point-lookup span
therefore let an accepted scan run off the end of the data: at 2400-01-09, 53 of
64 (day, timezone) combinations read past the end of the files and 35 lost
accuracy on days the files *do* cover, at HTTP 200. The upper bound is pulled in
by 39 days so the whole of that reach still lands inside the data. The **lower**
bound is not pulled in, deliberately — the backward search also leaves the files,
but swisseph's fallback is measured *not* to persist in that direction, so
narrowing there would cost ~4.5 years of range and buy nothing.

Two of these fields used to fault rather than answer — `at_date=9999-01-01`
raised an uncaught `swisseph.Error` and `reference_date=9999-01-01` an uncaught
`OverflowError`, both surfacing as a bare 500 — and the muhurat scan range used
to serve dates past the files at 200 off the fallback. All are 422 now. Each 422
names the offending field, both bounds, **and which of the two spans it is
quoting**, because "outside the range the data files cover" is a true reason for
a point lookup and a misleading one for a scanned day, whose refused dates are
themselves covered by the files.

Two caveats worth knowing, both measured:

- `from_date` / `to_date` and `reference_date` drive **no** ephemeris lookups —
  dasha timelines are projected arithmetically from the natal Moon. Measured on
  a servable request (birth 2390-06-15, `from_date` 2395-01-01), `to_date` at
  2400-01-09, 2450-01-01 and 2500-01-01 all answered 200 with the same 15
  ephemeris calls, the natal chart, though the last runs a century past the
  span. They are bounded for the crash and to keep the point-lookup fields on one
  consistent span, not because a fallback answer was measured behind them (they
  drive none). The cost is that a
  late-born chart can no longer request a timeline running past 2400-01-09.
- Several limbs legitimately look outside the scanned day — the eclipse veto must
  find the *next* eclipse, the Adhika-Maasa check reads the bracketing new moons,
  and the yoga limb searches similarly — so reading past the data at the very
  edge of the range was once unavoidable. Reading past it is not itself the
  defect; no data exists there. The defect is that swisseph *keeps* the fallback
  afterwards, so a later lookup at a date the files **do** cover answers
  analytically too, and that happens *inside* a single library call where no
  restore can intercept it. Two things close it, and they are different in kind:
  `_is_eclipse_day` restores the ephemeris state on the way out, and the
  scanned-day fields are now bounded so the searches have nothing to run off in
  the first place. Measured after both: the low end loses no accuracy (zero
  in-span fallback across 58 dates sampled 1800-01-02…1801-07-14, despite most of
  those scans' calls answering from the fallback at dates with no data); the
  interior is clean, including multi-day range scans at every timezone; and the
  end-of-range residue is **gone for every date the service accepts** — the walk
  over the last accepted days finds zero in-span fallback at every timezone
  corner, where the same walk at 2400-01-09 lost 122–226 calls per request.
  One attribution correction, since the earlier text carried it: the residue was
  **not** principally the *tithi* search. Measured per limb, `drik.tithi` has the
  **smallest** out-of-day reach (+1.998 d); the two that actually reached the end
  of the data are `drik.lunar_month` (+31.834 d) and `drik.yogam` (+24.859 d).

The node model is the choice most likely to explain a visible discrepancy.
Measured over 1800–2400 at one-day steps against the real Swiss data files, the
true and mean nodes differ by up to **1.98°**, and place Rahu in a different
nakshatra pada on **28.85%** of days, a different nakshatra on 7.19%, and a
different rasi on 3.20%. So if your Rahu is a degree or two from what this
service returns, a mean-node engine is the first thing to check.

That model is pinned deliberately rather than inherited from a dependency
default, and the service refuses to start if its dependency stops honouring it —
see `bphs_core/utils.py` and `tests/test_lunar_node_model.py`.

The **position-flag word** is pinned the same way. Every longitude here is a
*geometric* position (`FLG_TRUEPOS`): the graha's true place on the ecliptic,
without the light-time and aberration corrections that give an *apparent*
position. Measured over 1800–2400 at one-day steps against the real Swiss data
files, the two frames differ by up to **60.54″** (Mercury) — small next to the
node model, but enough to move a placement across a pada boundary. If your chart
sits within a minute of arc of this service's, an apparent-position engine is the
thing to check. The word is declared as `POSITION_FLAGS` in `bphs_core/utils.py`
and the service refuses to start if the dependency ever builds a different one;
`tests/test_position_flags.py` is the contract.

That guard has fired in anger once. `pyjhora` 4.8.7 changed the word it builds
from `66386` to `65810` — dropping `FLG_NOGDEFL` and `FLG_NONUT` — and the
service refused to start until the change was reviewed and the declaration
re-derived. No served longitude moved: swisseph applies both flags of its own
accord under `FLG_TRUEPOS` and `FLG_SIDEREAL` respectively, so the two words are
the same computation (measured bit-identical across 72 graha-epoch pairs under
both ephemeris runtimes). Every golden in this repository stayed green through
it, which is precisely why the declaration exists.

The **sunrise/sunset convention** is pinned the same way. Every panchanga and
electional limb — tithi, nakshatra, yoga, karana, the thirty muhurtas and the
muhurat/lagna-shuddhi scan — is anchored to the day boundary, and this service
defines that boundary as the Sun's disc **centre** at the **true, unrefracted
horizon** (the classical *madhya-bimba* Surya-Siddhanta convention), not the upper
limb at the apparent, refracted horizon a secular almanac reports. That choice is
a settled decision, not an open question: the disc-centre, unrefracted convention
is the one the Siddhantic tithi arithmetic assumes, while the civil upper-limb
alternative remains a defensible convention a secular almanac uses. Measured at
Colombo on 2024-03-20, the two conventions place sunrise **147.99 s** apart, so a
quietly refracted engine would shift every day-boundary computation. The words are
declared as `RISE_FLAGS` / `SET_FLAGS` in `bphs_core/utils.py`, distinct from the
ephemeris frame above, and the service refuses to start if the dependency ever
builds a different one; `tests/test_rise_set_flags.py` is the contract.

## API

The API contract is defined in `app/schemas.py` (request/response models) and the
endpoint table below. `/docs` and `/openapi.json` are intentionally disabled at
runtime (unauthenticated introspection endpoints were a security risk) — there is
no served or committed OpenAPI document; read `app/schemas.py` for the exact
shapes.

Endpoints under `/v1/`:

| POST | `/chart` | Full chart: D1–D60, lagna, ayanamsa |
| POST | `/strength` | Shadbala, Bhavabala, Ashtakavarga |
| POST | `/dashas` | Vimshottari / Yogini / Char dasha periods |
| POST | `/yogas` | All 284 yogas incl. Viparita Raja |
| POST | `/transits` | Saturn/Jupiter gochara, Sade Sati, Vedha |
| POST | `/special-points` | Arudha, Upapada, Atmakaraka, Karakamsa |
| GET | `/source` | License, source URL, running commit |

### Errors

Request-validation failures return `422` with `{"detail": [...]}` (the standard
FastAPI shape). One engine-compute failure has its own structured shape: when a
muhurat/electional limb that decides *which* time can be recommended cannot be
computed for the requested date/place, the engine raises rather than fabricating
a day frame, and the synchronous routes surface that as a `422` naming the limb:

```json
{"detail": {"code": "muhurat_limb_error", "limb": "sunrise",
            "target_date": "2026-05-26", "message": "..."}}
```

The stable `code` is the field to branch on; `limb` names what failed. This is
returned instead of an opaque `500`, and never as a `200` with an empty or
partial result. On the async scan-job endpoints the same failure is reported in
the job's `error` field on poll, not as an HTTP error on submit.
