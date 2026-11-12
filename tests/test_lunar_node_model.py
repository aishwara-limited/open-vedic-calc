"""The lunar node model (Rahu / Ketu) is a DECLARED choice, not an inherited default.

WHY THIS MODULE EXISTS
----------------------
Rahu and Ketu can be computed from either the TRUE (osculating) lunar node — the
actual instantaneous intersection of the Moon's orbital plane with the ecliptic —
or the MEAN node, a smoothed analytical fit to that intersection. The two differ
by a lot. Measured in this repo with the then-frozen dependency set (pyswisseph
2.10.3.2, pyjhora 4.8.6 — these are properties of swisseph's two node bodies, so
the later 4.8.7 bump left them untouched and pyswisseph is unmoved at 2.10.3.2)
against the real Swiss ephemeris data files, scanning
1800-01-01..2400-12-31 (the data files' full label span — WIDER than the served
birth-date bound, which is narrower and measured; see MIN_EPHEMERIS_DATE /
MAX_EPHEMERIS_DATE in app/schemas.py) one day at a time and refining the worst
day at one-hour steps:

    max |true - mean| = 1.981465100 deg = 118.8879 arcmin = 7133.2744 arcsec
    at JD 2417129.4166666595 (1905-10-10 22:00 UT)

    over the same 219511 sampled days, the two models place Rahu in a
    different nakshatra PADA on 28.85% of them, a different NAKSHATRA on
    7.19%, and a different RASI on 3.20%

That is not a rounding difference; it is an interpretive difference, and it is
more than twice the ~0.883 deg Lahiri-vs-Fagan/Bradley ayanamsa error this repo
already treats as a serious defect.

Until this module existed the choice was pinned NOWHERE. The engine inherited
whatever the astronomy library defaulted to, and the dependency carried an open
lower bound (`pyjhora>=4.8.0`), so a routine version bump could have moved every
Rahu and Ketu by up to 1.98 deg with no code change at all. The committed goldens
would have caught the movement, but a golden failure with no declared model reads
as a regression to fix rather than a deliberate choice to honour — the right
answer existed nowhere, so the next reader would have guessed.

THREE LEVERS, AND THE OBVIOUS ONE IS NOT THE ONE THAT SERVES
------------------------------------------------------------
Measured while writing this, not read from documentation. `jhora.const._RAHU`
(and its `_use_true_nodes_for_rahu_ketu` flag) is the lever everything about the
library's naming suggests. Under pyjhora 4.8.6, setting it to the mean node and
computing a real chart returned the TRUE node anyway, unchanged to the last
digit: the chart path is `drik.dhasavarga(jd, place, 1)`,
and dhasavarga declared `set_rahu_ketu_as_true_nodes=True` as a LITERAL parameter
default, so it rebuilt the body table from that literal and never consulted the
constants. `bphs_core.utils.apply_lunar_node_model` therefore pins the constants
AND the mutable `drik.planet_list`, and VERIFIES the serving default it cannot
set — refusing to start if the library ever disagrees with the declaration.

THAT THIRD LEVER CHANGED SHAPE IN pyjhora 4.8.7, and the applier already
anticipated it. The default is now `set_rahu_ketu_as_true_nodes=None` and the
body that rebuilt the table is commented out upstream ("it is altering/forcing
other than configured values"), so dhasavarga now DEFERS to the constants that
lever 1 pins. `_serving_path_node_default` treats `None` as acceptable for
exactly this reason, and the served node is unchanged — measured on the 4.8.7
resolve, Rahu at 2000-01-01 12:00 UT is 100.100800 deg, equal to swisseph's TRUE
node and 3911.8 arcsec from its MEAN node.

One consequence is worth stating plainly rather than discovering later. Under
4.8.6, declaring `LUNAR_NODE_MODEL = "mean"` hard-failed at import, because the
literal would have kept serving true nodes under a mean banner. Under 4.8.7 it
no longer hard-fails — measured: it serves 101.187424 deg, the actual mean node.
That is not a lost guard so much as a guard whose reason expired: the
banner-vs-reality contradiction it detected can no longer arise, because the
engine now serves whatever it declares. The friction that keeps the model from
moving on a one-word edit is unchanged and lives here —
`test_the_declared_lunar_node_model_is_the_true_node` pins the literal, and the
Swiss goldens move by ~1 deg on both shadow grahas.

THE CHOICE: TRUE NODE
---------------------
Recorded, with its rationale, in CLAUDE.md ("Engine conventions") and README.md.
In one line: every other graha this engine serves is a true/apparent position
from a modern ephemeris, so serving a smoothed mean element for one graha alone
would be internally inconsistent — and it is what the engine already served, so
declaring it changes no number anyone has already been given.

WHAT IS ASSERTED HERE
---------------------
The positive signal, never the absence of an error:

  * the declared model is TRUE, and all three levers really carry it;
  * a REAL served Chart's Rahu matches a direct TRUE-node computation and is
    ~1.98 deg away from the MEAN node (so this cannot pass on the wrong model);
  * Ketu is exactly Rahu + 180 deg;
  * the applier fails CLOSED when any lever will not honour the declaration —
    setter missing, setter ineffective, serving default flipped, serving
    parameter renamed away;
  * importing the package is what pins it, not luck about which module loaded
    first;
  * the dependency that supplies every one of those levers is pinned to an EXACT
    version in both pyproject.toml and uv.lock, so none of them can move
    underneath us.

Everything here is meaningful under BOTH runtimes — the Moshier fallback (the
ordinary CI job and the default local loop, no data files) and real Swiss data —
because the node model is a body-selection choice, not an ephemeris-source one.
Measured deltas of the served Rahu against a direct TRUE-node computation at the
worst epoch: 0.000000 arcsec on Moshier, 0.002977 arcsec on Swiss data.
"""
from __future__ import annotations

import datetime
import importlib.metadata
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import swisseph as swe
from jhora.panchanga import drik

from bphs_core import utils
from bphs_core.chart import Chart, PersonalData

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_UV_LOCK = _REPO_ROOT / "uv.lock"

# The epoch of maximum true-vs-mean disagreement in the SCANNED span, from the
# scan quoted in the module docstring. (It also falls inside the narrower served
# birth-date bound, so it remains the worst case for what the service answers.) Chosen deliberately: the two models cross
# (agree exactly) twice per ~173-day eclipse half-year, so a test that picked an
# arbitrary instant could accidentally sample a crossing and pass on either model.
_MAX_DIVERGENCE_UT = (1905, 10, 10, 22, 0)

# Separation between the served value and a direct computation of the SAME model.
# Measured worst case 0.002977 arcsec (8.3e-7 deg) on Swiss data, 0.0 on Moshier;
# the residual is pyjhora's extra position flags (FLG_TRUEPOS et al). 1e-3 deg is
# ~1200x above that residual and ~2000x below the 1.98 deg model separation, so it
# can never confuse the two models in either direction.
_SAME_MODEL_TOLERANCE_DEG = 1e-3

# The measured separation at the epoch above is 1.9815 deg (Swiss) / 1.9793 deg
# (Moshier). Requiring > 1.5 deg keeps margin on both while staying far above any
# ephemeris-source or flag difference.
_MODEL_SEPARATION_FLOOR_DEG = 1.5


def _separation(a: float, b: float) -> float:
    """Absolute angular separation in degrees, wrap-safe across 0/360."""
    return abs(((a - b + 180.0) % 360.0) - 180.0)


@pytest.fixture
def restore_node_model():
    """Re-apply the declared model after a test deliberately corrupts it.

    Several tests below flip `jhora.const` to the wrong model on purpose. That
    state is process-global (a module attribute, not thread-local), so leaving it
    corrupted would silently move Rahu for every later test in the session —
    including the committed Swiss goldens. Restoration is a fixture teardown
    rather than an in-test `finally` so it also runs when a test fails mid-way.
    """
    yield
    utils.apply_lunar_node_model()
    assert utils.jhora_const._RAHU == utils.LUNAR_NODE_BODY


# ---------------------------------------------------------------------------
# The declaration itself
# ---------------------------------------------------------------------------


def test_the_declared_lunar_node_model_is_the_true_node() -> None:
    """The engine declares a node model, and it is TRUE.

    Asserting the literal is the point: this test is the tripwire that makes a
    change of astrological model impossible to land silently. If the model is
    ever deliberately changed, this assertion and the goldens both have to be
    re-recorded in the same reviewed change, which is exactly the friction the
    absence of any declaration used to remove.
    """
    assert utils.LUNAR_NODE_MODEL == "true", (
        "the engine's declared lunar node model changed. This moves every Rahu "
        "and Ketu by up to 1.98 deg (a different nakshatra pada on 28.85% of "
        "days in 1800-2400) and invalidates every chart previously served. It is "
        "an astrological model decision, not an implementation detail: re-record "
        "the goldens and the rationale in CLAUDE.md in the same change."
    )
    assert utils.LUNAR_NODE_BODY == swe.TRUE_NODE


def test_the_declaration_is_actually_carried_by_the_astronomy_library() -> None:
    """A declared constant that the library never sees would be decoration.

    All three levers, because they are genuinely independent — measured: pinning
    only the constants leaves the served chart completely unmoved.
    """
    assert utils.jhora_const._RAHU == swe.TRUE_NODE, (
        f"jhora.const._RAHU is {utils.jhora_const._RAHU}, expected "
        f"swisseph.TRUE_NODE ({swe.TRUE_NODE}) — the declared model was not applied"
    )
    # The library reads BOTH names: most call sites read `const._RAHU`, while
    # `drik.set_planet_list` reads the boolean. They must agree, or different
    # limbs of one chart disagree about which node they are describing.
    assert utils.jhora_const._use_true_nodes_for_rahu_ketu is True

    listed = [
        body
        for body, planet_id in drik.planet_list.items()
        if planet_id == utils.jhora_const.RAHU_ID
    ]
    assert listed == [swe.TRUE_NODE], (
        f"drik.planet_list maps Rahu to {listed}, expected [{swe.TRUE_NODE}] — the "
        "mutable planet_list global still describes the previous model"
    )


def test_the_serving_path_agrees_with_the_declaration() -> None:
    """The lever that actually decides a served chart is the one worth pinning.

    `Chart._compute` calls `drik.dhasavarga(jd, place, 1)` without a node
    argument, so dhasavarga's own parameter default — a library literal this repo
    cannot set — is what every served Rahu and Ketu comes from. It ignores
    `const._RAHU` entirely. If a dependency bump ever moves that literal, the
    engine must refuse to start rather than quietly serve the other model.
    """
    default = utils._serving_path_node_default()
    assert default is None or default is True, (
        f"drik.dhasavarga applies {utils._SERVING_PATH_NODE_PARAMETER}={default!r}, "
        "which contradicts the declared true node"
    )


# ---------------------------------------------------------------------------
# The served value — the assertion that cannot be satisfied by the wrong model
# ---------------------------------------------------------------------------


def test_a_served_rahu_matches_the_declared_node_model() -> None:
    """A REAL Chart's Rahu is the TRUE node, measured against swisseph directly.

    This is the load-bearing assertion. Every other check here is about
    configuration; this one is about the number the caller is actually given, so
    it still holds if the configuration were bypassed entirely — which is not
    hypothetical, since `drik.dhasavarga` bypasses `const._RAHU` by design. Proved
    non-vacuous by patching the installed library to ask dhasavarga for the mean
    node while leaving every signature and constant in agreement: this test goes
    red and the Swiss goldens go with it.
    """
    year, month, day, hour, minute = _MAX_DIVERGENCE_UT
    person = PersonalData(
        name="synthetic",
        birth_date=datetime.date(year, month, day),
        birth_time=datetime.time(hour, minute, 0),
        birth_place="Synthetic",
        latitude=7.0,
        longitude=80.0,
        timezone_offset_hours=0.0,  # so the local JD below IS the UT JD
    )
    snapshot = Chart(person).snapshot()
    served_rahu = snapshot.rasi_chart["Rahu"].longitude_abs
    served_ketu = snapshot.rasi_chart["Ketu"].longitude_abs

    jd_ut = swe.julday(year, month, day, hour + minute / 60.0)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    with utils.EPHEMERIS_LOCK:
        true_values, _ = swe.calc_ut(jd_ut, swe.TRUE_NODE, flags)
        mean_values, _ = swe.calc_ut(jd_ut, swe.MEAN_NODE, flags)

    from_true = _separation(served_rahu, true_values[0])
    from_mean = _separation(served_rahu, mean_values[0])

    assert from_true < _SAME_MODEL_TOLERANCE_DEG, (
        f"the served Rahu ({served_rahu}) is {from_true:.9f} deg from the TRUE "
        f"node ({true_values[0]}) — the engine is not serving its declared model"
    )
    assert from_mean > _MODEL_SEPARATION_FLOOR_DEG, (
        f"the served Rahu ({served_rahu}) is only {from_mean:.9f} deg from the "
        f"MEAN node ({mean_values[0]}). Either the two models are not separated "
        "at this epoch (so this test proves nothing and the epoch must change) "
        "or the engine is serving the mean node."
    )
    # 1e-9 deg = 3.6 microarcsec, i.e. exactness up to float noise. Ketu is not an
    # independent computation: the library derives it as Rahu + 180 from the same
    # longitude, so anything above float noise here means the two shadow grahas
    # came from different models.
    assert _separation(served_ketu, (served_rahu + 180.0) % 360.0) < 1e-9, (
        f"Ketu ({served_ketu}) is not 180 deg from Rahu ({served_rahu}) — "
        "the two nodes came from different computations"
    )


# ---------------------------------------------------------------------------
# The applier — mechanism, and fail-closed behaviour
# ---------------------------------------------------------------------------


def test_apply_lunar_node_model_restores_the_declaration(restore_node_model) -> None:
    """The applier ACTS; it does not merely agree with whatever it finds.

    Corrupting the library first is what makes this meaningful: an applier that
    was silently a no-op would still leave `_RAHU` on the mean node here.
    """
    utils.jhora_const.set_node_mode(False)
    drik.set_planet_list(set_rahu_ketu_as_true_nodes=False)
    assert utils.jhora_const._RAHU == swe.MEAN_NODE, "precondition not established"
    assert swe.MEAN_NODE in drik.planet_list, "precondition not established"

    utils.apply_lunar_node_model()

    assert utils.jhora_const._RAHU == swe.TRUE_NODE
    assert utils.jhora_const._use_true_nodes_for_rahu_ketu is True
    assert drik.planet_list[swe.TRUE_NODE] == utils.jhora_const.RAHU_ID
    assert swe.MEAN_NODE not in drik.planet_list


def test_apply_lunar_node_model_fails_closed_when_the_setter_is_missing(
    restore_node_model,
) -> None:
    """A library that no longer offers the setter must stop the engine.

    The alternative — carrying on with whatever the library defaulted to — is the
    exact silent-inheritance failure this whole module exists to remove.

    Patched by hand rather than with `monkeypatch`, deliberately: pytest undoes
    `monkeypatch` AFTER the fixtures a test declared before it, so the
    `restore_node_model` teardown would run while the setter was still missing
    and fail there instead of restoring. An explicit `finally` makes the order
    unambiguous rather than a property of argument order.
    """
    original_setter = utils.jhora_const.set_node_mode
    del utils.jhora_const.set_node_mode
    try:
        with pytest.raises(RuntimeError, match="set_node_mode"):
            utils.apply_lunar_node_model()
    finally:
        utils.jhora_const.set_node_mode = original_setter


def test_apply_lunar_node_model_fails_closed_when_the_setter_does_nothing(
    restore_node_model,
) -> None:
    """Calling the setter is not evidence it took effect — verify the result.

    A future library could keep the function and change what it does. The applier
    must read back the constants the rest of the library actually uses, not
    assume the call worked.
    """
    original_setter = utils.jhora_const.set_node_mode
    original_setter(False)  # establish the WRONG model, then make it un-fixable
    utils.jhora_const.set_node_mode = lambda _use_true: None
    try:
        with pytest.raises(RuntimeError, match="did not take effect"):
            utils.apply_lunar_node_model()
    finally:
        utils.jhora_const.set_node_mode = original_setter


def test_apply_lunar_node_model_fails_closed_when_the_serving_path_disagrees(
    restore_node_model,
) -> None:
    """The exact shape of the threat: a dependency bump moves dhasavarga's default.

    Substituting a stub whose signature carries the OTHER model reproduces that
    without touching the installed library, and proves the engine stops instead
    of serving mean-node charts while still declaring the true node.
    """
    original_dhasavarga = drik.dhasavarga

    def flipped_dhasavarga(jd, place, divisional_chart_factor=1,
                           set_rahu_ketu_as_true_nodes=False, **kwargs):
        raise AssertionError("not meant to be called")

    drik.dhasavarga = flipped_dhasavarga
    try:
        with pytest.raises(RuntimeError, match="of its own accord"):
            utils.apply_lunar_node_model()
    finally:
        drik.dhasavarga = original_dhasavarga


def test_apply_lunar_node_model_fails_closed_when_the_serving_parameter_vanishes(
    restore_node_model,
) -> None:
    """A renamed or removed parameter means the model is no longer knowable."""
    original_dhasavarga = drik.dhasavarga

    def parameterless_dhasavarga(jd, place, divisional_chart_factor=1, **kwargs):
        raise AssertionError("not meant to be called")

    drik.dhasavarga = parameterless_dhasavarga
    try:
        with pytest.raises(RuntimeError, match="no longer takes"):
            utils.apply_lunar_node_model()
    finally:
        drik.dhasavarga = original_dhasavarga


def test_importing_the_package_is_what_pins_the_model() -> None:
    """Import `bphs_core` into a fresh interpreter that starts on the WRONG model.

    A subprocess, deliberately. In-process the model is already pinned by the
    time any test runs, so nothing in this session can distinguish "the package
    pins it" from "the library happened to default to it". The child flips the
    library to the mean node BEFORE importing the package; if the package's
    import-time application were dropped, the child would still report the mean
    node and this test goes red.
    """
    probe = textwrap.dedent(
        """
        import swisseph as swe
        from jhora import const

        const.set_node_mode(False)
        assert const._RAHU == swe.MEAN_NODE, "child failed to establish the wrong model"

        import bphs_core  # noqa: F401  -- the import under test

        print(f"RESULT {const._RAHU} {swe.TRUE_NODE} {swe.MEAN_NODE}")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300, encoding="utf-8", errors="replace",
    )
    assert completed.returncode == 0, (
        f"probe interpreter failed:\nstdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    result = [line for line in completed.stdout.splitlines() if line.startswith("RESULT ")]
    assert result, f"probe produced no RESULT line:\nstdout:\n{completed.stdout}"
    rahu, true_node, mean_node = (int(part) for part in result[-1].split()[1:])
    assert rahu == true_node, (
        f"a fresh interpreter that started on the mean node ({mean_node}) still "
        f"had _RAHU={rahu} after importing bphs_core — importing the package no "
        "longer pins the declared lunar node model, so the engine is back to "
        "inheriting whatever the library defaults to"
    )


# ---------------------------------------------------------------------------
# The dependency pin — the default must not be able to move underneath the code
# ---------------------------------------------------------------------------
#
# Textual parsing rather than a TOML parser: reading two lines needs none, and
# the same convention is already used by
# ci/tests/test_ci_runs_gate_regression_suite.py.

_PYPROJECT_DEP = re.compile(r'^\s*"pyjhora(?P<specifier>[^"]*)"\s*,?\s*$', re.MULTILINE)
_LOCK_REQUIREMENT = re.compile(
    r'\{\s*name\s*=\s*"pyjhora"\s*,\s*specifier\s*=\s*"(?P<specifier>[^"]*)"\s*\}'
)


def test_pyjhora_is_pinned_to_an_exact_version_in_pyproject() -> None:
    """An open lower bound would let the node-model default move on a bump.

    `pyjhora` is where the default lives (`jhora.const._RAHU`). It was declared
    `>=4.8.0`, so a resolve that picked a release which flipped that default would
    have moved every Rahu and Ketu by up to 1.98 deg with no code change. Pinned
    exactly, the same way the other astronomy dependency (`pyswisseph`) already
    is, a bump becomes a visible, reviewable diff that re-runs the goldens.
    """
    match = _PYPROJECT_DEP.search(_PYPROJECT.read_text(encoding="utf-8"))
    assert match, "pyjhora is no longer a declared dependency in pyproject.toml"
    specifier = match.group("specifier")
    assert specifier.startswith("=="), (
        f'pyproject.toml declares "pyjhora{specifier}". It must be an exact "==" '
        "pin: this dependency supplies the lunar node model default, and an open "
        "bound lets that default — and therefore every Rahu and Ketu the engine "
        "serves — move on a routine dependency resolve."
    )
    pinned = specifier[2:]
    installed = importlib.metadata.version("pyjhora")
    assert pinned == installed, (
        f"pyproject.toml pins pyjhora=={pinned} but the running environment has "
        f"{installed}. The tests, the goldens and the shipped image must all be "
        "the same resolve."
    )


def test_the_lockfile_records_the_same_exact_pin() -> None:
    """uv.lock is what the image installs (`uv sync --frozen`), so it must agree.

    Drift here is not cosmetic: `--frozen` fails the build when the lock and
    pyproject disagree, so a lock still recording the old open bound turns a
    correct pin into a broken image build. Asserting it names the cause here
    instead of at `docker build`.
    """
    lock_text = _UV_LOCK.read_text(encoding="utf-8")
    match = _LOCK_REQUIREMENT.search(lock_text)
    assert match, "uv.lock no longer records a pyjhora requirement"
    assert match.group("specifier") == "==" + importlib.metadata.version("pyjhora"), (
        f'uv.lock records pyjhora "{match.group("specifier")}" but the running '
        f"environment has {importlib.metadata.version('pyjhora')} — re-run `uv lock`"
    )
