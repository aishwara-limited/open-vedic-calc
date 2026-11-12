import functools
import inspect
import os
import threading

import swisseph as swe
from jhora import const as jhora_const
from jhora import utils as jhora_utils
from jhora.panchanga import drik

# ---------------------------------------------------------------------------
# The lunar node model (Rahu / Ketu) is DECLARED here. It is never inherited.
#
# Rahu and Ketu can be computed from either the TRUE (osculating) lunar node --
# the actual instantaneous intersection of the Moon's orbital plane with the
# ecliptic -- or the MEAN node, a smoothed analytical fit to that intersection.
# Measured on the then-pinned dependency set (pyswisseph 2.10.3.2, pyjhora 4.8.6)
# against the real Swiss ephemeris data files, over the data files' full label
# span (1800-01-01..2400-12-31 -- WIDER than the served birth-date bound, which
# is narrower and measured; see MIN_EPHEMERIS_DATE/MAX_EPHEMERIS_DATE in
# app/schemas.py) at one-day steps and refined at one-hour steps around the
# worst day:
#
#     max |true - mean| = 1.981465100 deg = 118.8879 arcmin = 7133.2744 arcsec
#                         at 1905-10-10 22:00 UT
#
# and across those 219511 sampled days the two models put Rahu in a different
# nakshatra PADA on 28.85% of them, a different NAKSHATRA on 7.19%, and a
# different RASI on 3.20%. Ketu follows Rahu exactly (Rahu + 180 deg), so the
# choice moves both shadow grahas together. For scale, that is more than twice
# the ~0.883 deg Lahiri-vs-Fagan/Bradley ayanamsa error documented above.
#
# Those figures are a property of swisseph's two node bodies, not of pyjhora, so
# the 4.8.6 -> 4.8.7 bump did not disturb them; pyswisseph is unmoved at
# 2.10.3.2. What the bump DID move is lever 3 below -- re-read that before
# assuming any of this block still describes the mechanism.
#
# WHY TRUE. Every other graha this engine serves is a true/apparent position
# from a modern ephemeris; the true node is the same class of quantity, so
# serving a smoothed mean element for one graha alone would make a single chart
# internally inconsistent. The Siddhantic mean-motion treatment of Rahu is a
# computational method of its era, not a doctrinal requirement, and this engine
# already declines that era's methods for every visible graha. It is also what
# the engine already served, so declaring it moves no number that any caller has
# already been given.
#
# OWNER-RULED (2026-08-17): the true node is not merely an engine-declared choice
# but an explicit owner ruling of that date. Because the engine already served
# the true node (see above and tests/test_lunar_node_model.py), the ruling moves
# no served longitude -- it records the authority behind the existing choice and
# settles the true-vs-mean question rather than reopening it.
#
# WHY IT IS DECLARED AT ALL, given it matches the library's current behaviour:
# an inherited default is not a choice, it is an accident that happens to be
# right. A library release that moved it would have moved every Rahu and Ketu by
# up to 1.98 deg with no change in this repository at all. The committed goldens
# would have failed -- but a golden failure with no declared model anywhere reads
# as a regression to chase rather than a deliberate choice to honour. The
# dependency is additionally pinned to an exact version in pyproject.toml so the
# default cannot move underneath this declaration in the first place; this block
# is what makes the choice legible when it does move.
#
# THREE INDEPENDENT LEVERS, and the third is the one that actually serves.
# Verified by measurement, not by reading the config (flip only the first and the
# served chart does not move at all):
#
#   1. ``const._RAHU`` / ``const._use_true_nodes_for_rahu_ketu`` -- read at call
#      time by every ``drik.sidereal_longitude(jd, const._RAHU)`` site.
#   2. ``drik.planet_list`` -- a MUTABLE module global, rebuilt by
#      ``drik.set_planet_list()``; body id -> planet id for the position loops.
#   3. ``drik.dhasavarga``'s own parameter default. This is the lever the chart
#      path uses: ``Chart._compute`` calls ``drik.dhasavarga(jd, place, 1)``.
#      Under pyjhora 4.8.6 dhasavarga declared
#      ``set_rahu_ketu_as_true_nodes=True`` as a LITERAL default (not ``None``),
#      so it re-derived planet_list from that literal and never consulted lever 1
#      at all: setting only the constants left every served Rahu unchanged -- a
#      declaration that looked applied and was not.
#      ``apply_lunar_node_model`` below pins 1 and 2 and VERIFIES 3.
#
#      pyjhora 4.8.7 CHANGED THIS LEVER: the default is now ``None`` and the
#      forcing body is commented out upstream ("it is altering/forcing other than
#      configured values"), so dhasavarga now defers to lever 1. The verifier was
#      already written for that case -- ``_serving_path_node_default`` returns the
#      default and ``None`` is accepted precisely because it means "defers to the
#      constants, which this function has already pinned". Re-measured on the
#      4.8.7 resolve, the served node is unchanged: Rahu at 2000-01-01 12:00 UT is
#      100.100800 deg, equal to swisseph's TRUE node, 3911.8 arcsec from MEAN.
#
# A CONSEQUENCE OF THAT CHANGE, stated rather than left to be discovered. Under
# 4.8.6, lever 3 being an unsettable literal meant declaring
# LUNAR_NODE_MODEL = "mean" HARD-FAILED at import rather than silently serving
# true-node charts under a mean-node banner. Under 4.8.7 it no longer hard-fails
# -- measured: it serves 101.187424 deg, the real mean node. The guard did not
# weaken so much as its reason expired: the banner-vs-reality contradiction it
# detected cannot arise now that the serving path honours the declaration. What
# has NOT changed is the friction that keeps the model from moving on a one-word
# edit: switching model still means re-recording the Swiss goldens (both shadow
# grahas move ~1 deg) and re-recording the declaration's own tripwire in
# tests/test_lunar_node_model.py, in the same reviewed change.
#
# Changing LUNAR_NODE_MODEL is an astrological model decision, not an
# implementation detail: it invalidates every previously served chart.
# tests/test_lunar_node_model.py is the tripwire that enforces all of the above.
# ---------------------------------------------------------------------------
LUNAR_NODE_MODEL = "true"

# Derived, never independently declared, so the two can never disagree; an
# unknown model name raises KeyError at import rather than serving something
# unintended.
LUNAR_NODE_BODY = {"true": swe.TRUE_NODE, "mean": swe.MEAN_NODE}[LUNAR_NODE_MODEL]


_SERVING_PATH_NODE_PARAMETER = "set_rahu_ketu_as_true_nodes"


def _serving_path_node_default() -> bool | None:
    """The node model ``drik.dhasavarga`` applies when this repo does not pass one.

    ``Chart._compute`` calls ``dhasavarga`` without that argument, so this
    literal -- not ``const._RAHU`` -- decides which node every served chart
    carries. ``None`` means the library defers to the constants, which
    ``apply_lunar_node_model`` has already pinned, and is therefore acceptable.
    """
    parameters = inspect.signature(drik.dhasavarga).parameters
    parameter = parameters.get(_SERVING_PATH_NODE_PARAMETER)
    if parameter is None:
        raise RuntimeError(
            f"drik.dhasavarga no longer takes a {_SERVING_PATH_NODE_PARAMETER!r} "
            "parameter, so this engine can no longer tell which lunar node model "
            "the chart path serves. Refusing to continue: re-establish how the "
            "serving path selects Rahu and Ketu before moving the dependency pin."
        )
    return parameter.default


def apply_lunar_node_model() -> None:
    """Pin the astronomy library to LUNAR_NODE_MODEL, or refuse to run.

    Fail-closed throughout. Every step below is read back after it is applied,
    because calling a setter is not evidence it took effect, and the cost of
    being wrong is up to 1.98 deg on both shadow grahas.

    Pins the two levers this repo can set, and verifies the third it cannot:

    1. ``const.set_node_mode`` rather than assigning ``const._RAHU`` directly,
       because two library-internal names must stay in agreement -- most call
       sites read ``const._RAHU``, while ``set_planet_list`` and others read the
       boolean ``_use_true_nodes_for_rahu_ketu``. A direct assignment would
       desynchronise them and leave different limbs of one chart describing
       different nodes.
    2. ``drik.set_planet_list``, because ``drik.planet_list`` is a mutable
       module global that was built from the constants at drik's own import
       time -- i.e. before this ran.
    3. ``drik.dhasavarga``'s parameter default, which is a library literal this
       repo cannot set and which is what the chart path actually uses. It is
       verified, never assumed: if it ever stops agreeing with the declaration
       the engine refuses to start instead of serving the other model.

    ``const._KETU`` is deliberately NOT verified: the library resolves it to -10
    under the true node and to ``-swe.MEAN_NODE`` -- which is also -10 -- under
    the mean node, so it carries no information about which model is active. It
    is a sentinel that makes the library compute Ketu as Rahu + 180 deg, which
    is why Ketu always follows whichever model Rahu is on.

    Idempotent, and cheap: it sets and inspects module attributes and does not
    touch the ephemeris.
    """
    want_true_node = LUNAR_NODE_MODEL == "true"

    # (1) the library's module-level constants
    setter = getattr(jhora_const, "set_node_mode", None)
    if setter is None:
        raise RuntimeError(
            "the astronomy library no longer exposes jhora.const.set_node_mode, so "
            f"this engine cannot pin its declared lunar node model ({LUNAR_NODE_MODEL} "
            "node). Refusing to continue rather than inheriting whatever the library "
            "defaults to: the true and mean nodes differ by up to 1.98 degrees, which "
            "moves Rahu's and Ketu's nakshatra pada on roughly a third of dates. "
            "Re-establish the declaration against the new library API in the same "
            "change that moves the pin."
        )
    setter(want_true_node)

    applied_body = getattr(jhora_const, "_RAHU", None)
    applied_flag = getattr(jhora_const, "_use_true_nodes_for_rahu_ketu", None)
    if applied_body != LUNAR_NODE_BODY or applied_flag != want_true_node:
        raise RuntimeError(
            f"pinning the declared lunar node model did not take effect: asked the "
            f"astronomy library for the {LUNAR_NODE_MODEL} node (swisseph body "
            f"{LUNAR_NODE_BODY}), but jhora.const now reports _RAHU={applied_body!r} "
            f"and _use_true_nodes_for_rahu_ketu={applied_flag!r}. Refusing to serve "
            "charts whose Rahu and Ketu are on an undeclared model."
        )

    # (2) drik's mutable planet_list global, built before this ran
    drik.set_planet_list(set_rahu_ketu_as_true_nodes=want_true_node)
    listed_body = next(
        (body for body, planet_id in drik.planet_list.items()
         if planet_id == jhora_const.RAHU_ID),
        None,
    )
    if listed_body != LUNAR_NODE_BODY:
        raise RuntimeError(
            f"pinning the declared lunar node model did not take effect in "
            f"drik.planet_list: Rahu is mapped to swisseph body {listed_body!r}, "
            f"expected {LUNAR_NODE_BODY} for the {LUNAR_NODE_MODEL} node."
        )

    # (3) the serving path's own literal, which this repo cannot set
    serving_default = _serving_path_node_default()
    if serving_default is not None and serving_default != want_true_node:
        raise RuntimeError(
            f"this engine declares the {LUNAR_NODE_MODEL} lunar node, but the chart "
            f"path (drik.dhasavarga, called by Chart._compute) applies "
            f"{_SERVING_PATH_NODE_PARAMETER}={serving_default!r} of its own accord, "
            "so every served Rahu and Ketu would be on the other model -- up to "
            "1.98 degrees away, a different nakshatra pada on roughly a third of "
            "dates. Refusing to serve charts that contradict the declaration. Either "
            "the dependency changed that default (revert the bump, or pass the node "
            "argument to drik.dhasavarga explicitly and re-record the Swiss "
            "goldens), or LUNAR_NODE_MODEL was changed without that routing work."
        )


apply_lunar_node_model()

# ---------------------------------------------------------------------------
# The swisseph POSITION-FLAG WORD is DECLARED here. It is never inherited.
#
# Every planetary longitude this engine serves is the result of
# ``swe.calc_ut(jd, body, flags)``. That third argument decides the REFERENCE
# FRAME the number is expressed in -- geometric or apparent, with or without
# gravitational deflection, with or without nutation, sidereal or tropical. It is
# part of what the answer means, not a tuning knob.
#
# It used to be inherited from ``drik.PLANET_FLAGS``, which the astronomy library
# builds at ITS import time from ``jhora.const.PLANET_POSITIONS_*`` module
# globals. Measured 2026-07-31, this same repository on two dependency resolves:
#
#     pyjhora 4.8.6, pyswisseph 2.10.3.2   PLANET_FLAGS = 66386
#     pyjhora 4.8.7 (one patch release)    PLANET_FLAGS = 65810
#
# a difference of 576 = FLG_NOGDEFL (512) | FLG_NONUT (64), because 4.8.7 flipped
# ``PLANET_POSITIONS_USE_DEFLECTION`` and ``PLANET_POSITIONS_USE_NUTATION`` from
# False to True. No file here changed, and nothing in this repository went red.
#
# THAT BUMP HAS SINCE BEEN TAKEN, DELIBERATELY, and this declaration re-derived
# with it (2026-08-21). The pin is now ``pyjhora==4.8.7`` and the declared word is
# 65810. Re-measured on the 4.8.7 resolve, the five source globals now read
# GEOCENTRIC=True, TRUE=True, USE_ABERRATION=True, USE_DEFLECTION=True,
# USE_NUTATION=True, and the builder returns 65810. Upstream published no
# substantive changelog for the release (the 4.8.7 release note reads, in full,
# "See README.MD"), so the WHY below is measured here rather than quoted.
#
# WHY THE SERVED NUMBERS DID NOT MOVE -- the mechanism, read out of swisseph's
# OWN retflag rather than inferred from magnitudes. Requesting each word for
# Mercury at 2000-01-01 12:00 UT:
#
#     requested 66386 -> retflag 67410, swisseph adding back FLG_NOABERR
#     requested 65810 -> retflag 67410, swisseph adding back
#                                       FLG_NONUT|FLG_NOGDEFL|FLG_NOABERR
#
# The retflags are IDENTICAL. Under FLG_TRUEPOS the two requests converge on the
# same effective word inside the library, so they are not merely close, they are
# the same computation. Confirmed on output: over 72 graha-epoch pairs (8 grahas
# x 9 epochs spanning 1800-01-01..2400-12-31, including the 2353-06-16 extreme)
# the longitude AND the daily speed are BIT-IDENTICAL between the two words --
# compared as packed IEEE-754 bits, not against a tolerance -- 56 of those pairs
# answered by the real Swiss data files and 16 by the Moshier fallback, so the
# result holds under both ephemeris runtimes.
#
# WHICH FLAG IS MASKED BY WHICH -- measured separately, because they are NOT both
# masked by the same thing, and an earlier gloss that said so was imprecise:
#
#     FLG_NOGDEFL is masked by FLG_TRUEPOS. Clear TRUEPOS and swisseph stops
#         adding it back: requested 66370 -> retflag 66370 (nothing added),
#         requested 65794 -> retflag 65858. The two then serve DIFFERENT numbers.
#     FLG_NONUT is masked by FLG_SIDEREAL, not by TRUEPOS. Even with TRUEPOS
#         cleared, the 65794 request comes back with FLG_NONUT added (retflag
#         65858): a sidereal request is referred to the mean equinox regardless.
#
# So dropping the 576 from the declaration is safe only while FLG_TRUEPOS and
# FLG_SIDEREAL are both declared. That is not left to prose -- ``apply_position_
# flags`` enforces it as an invariant below, which is the replacement for what
# declaring the two inert flags used to buy: they could not become live silently.
# Measured cost if the invariant were violated: with TRUEPOS cleared the two
# words separate by up to 0.128869 arcsec across the same 72 pairs (worst Saturn,
# 2400-12-31), and FLG_NOABERR would be worth 20.8557 arcsec.
#
# WHAT THE GOVERNING FLAGS ARE WORTH. Measured with the frozen resolve against
# the real Swiss ephemeris data files, scanning 1800-01-01..2400-12-31 (the data
# files' full label span, WIDER than the served birth-date bound -- see
# MIN_EPHEMERIS_DATE/MAX_EPHEMERIS_DATE in app/schemas.py) at one-day steps --
# 219511 days x 9 grahas:
#
#   FLG_TRUEPOS (geometric vs apparent)
#       max 0.016817256 deg = 60.5421 arcsec, Mercury at 2353-06-16 00:00 UT.
#       Per graha: Mercury 60.5421", Venus 44.7711", Mars 38.9693",
#       Jupiter 30.0595", Saturn 27.2519", Sun 20.8489", Moon 0.7632",
#       Rahu/Ketu 0.0146".
#
#   FLG_NOGDEFL + FLG_NONUT (the 576 that moved between the two resolves)
#       max 0.000000000 deg = 0.000000 arcsec, every graha, all 219511 days.
#
# The second number is why this block exists. Under FLG_TRUEPOS swisseph ignores
# deflection and aberration outright, and for a sidereal request it applies
# FLG_NONUT of its own accord (a request of FLG_SWIEPH|FLG_SIDEREAL comes back
# with retflag 65602, carrying an FLG_NONUT nobody asked for). So the library's
# flag word moved and NO golden in this repository could have caught it -- the
# served numbers were bit-identical. The 576 is inert, but inert CONDITIONALLY,
# masked by another flag inherited from the same undeclared source: clear
# FLG_TRUEPOS and FLG_NOGDEFL is worth 0.0711 arcsec and FLG_NOABERR 20.8557
# arcsec (measured at century steps over the same span). Three coupled defaults,
# one of which decides whether the other two matter, is not a frame anyone chose.
# That is now an ENFORCED invariant rather than an observation -- see (0b) in
# ``apply_position_flags``.
#
# WHY THIS FRAME. It is the frame the engine already served, so declaring it
# moves no number any caller has been given -- deliberately, exactly as with the
# lunar node model above, and that remained true across the 4.8.6 -> 4.8.7 bump
# precisely because of the bit-identity measured above. FLG_TRUEPOS (geometric,
# i.e. light-time and aberration not applied) is the classical Vedic convention:
# BPHS positions are the graha's true place on the ecliptic, and the ~60 arcsec
# of light-time and aberration that separate it from the apparent place are an
# observational correction with no BPHS meaning. Every limb of a chart --
# nakshatra, pada, varga, dasha balance -- is then derived from one consistent
# frame. FLG_SIDEREAL with the Lahiri ayanamsa follows from the engine being
# sidereal at all; FLG_SPEED is required because ``drik.planets_in_retrograde``
# reads the sign of the returned daily motion. FLG_TOPOCTR is deliberately NOT
# taken: this service receives no observer altitude, and a topocentric frame
# would make every position depend on one.
#
# FLG_NOGDEFL and FLG_NONUT are deliberately NOT taken either, and that is the
# one line of this declaration that CHANGED at 4.8.7 rather than being restated.
# They used to be taken, for a stated reason: they are inert under FLG_TRUEPOS,
# and declaring them meant they could not become live silently. Requesting them
# is now redundant -- measured above, swisseph adds both back of its own accord
# and returns the identical retflag either way -- so continuing to declare them
# would mean declaring a frame the library no longer builds, and the tripwire at
# (1) below is an EQUALITY against the library's word by design: absorbing a
# disagreement instead of resolving it is the exact failure this block exists to
# end. The protection they bought is therefore re-created directly, as the
# masking invariant at (0b), which fails closed if a future edit ever clears
# FLG_TRUEPOS or FLG_SIDEREAL while these two are absent. Never reason about one
# of these flags without the others.
#
# THREE LEVERS, measured rather than read from documentation:
#
#   1. ``jhora.const.PLANET_POSITIONS_*`` -- five module globals, read by
#      ``jhora.utils.set_flags_for_planet_positions()`` on every call. This is
#      the INHERITED DEFAULT, and it is what moved between 4.8.6 and 4.8.7.
#   2. ``drik.PLANET_FLAGS`` -- a MUTABLE module global built from (1) at drik's
#      import time, i.e. before anything in this package has run. This is the
#      word that actually SERVES: ``drik.sidereal_longitude``, ``drik.dhasavarga``
#      (hence ``charts.rasi_chart``) and ``drik.planets_in_retrograde`` all read
#      it at call time.
#   3. ``jhora.const._TROPICAL_MODE`` -- when true, ``drik.sidereal_longitude``
#      ignores ``PLANET_FLAGS`` entirely and computes with
#      ``FLG_SWIEPH + FLG_SPEED``, i.e. tropical, ~24 deg away. A pinned word
#      that is bypassed is not a pin.
#
# ``apply_position_flags`` below checks the declaration against its own
# decomposition (0) and against the masking invariant (0b), compares (1) against
# this declaration and refuses to start on any disagreement, PINS (2) and reads
# it back, and verifies (3). The comparison against (1) is the dependency-bump
# tripwire: pinning alone would silently absorb a library that changed its mind,
# which is the failure this block exists to end. It has now fired in anger once
# -- on the 4.8.7 bump, where it was the ONLY thing in this repository that went
# red (measured: 41 collection errors, every one this RuntimeError, while every
# golden stayed green because the served numbers did not move).
#
# SCOPE, stated rather than left to be discovered. This is the PLANETARY POSITION
# word only. The ascendant and Bhava-Chalit cusps come from
# ``swe.houses(jd_utc, lat, lon, b"P")`` in chart.py, which takes no flag word at
# all; sunrise/sunset use pyjhora's separate ``drik.RISE_FLAGS`` /
# ``drik.SET_FLAGS`` (measured 897 / 898 on 4.8.6 and re-measured 897 / 898 on
# the 4.8.7 resolve, so they did not move on this bump -- and they are declared
# in their own right below).
#
# Contract: tests/test_position_flags.py. Extend it, never weaken it. The
# dependency that supplies all three levers is pinned to an exact version in
# pyproject.toml for the same reason the lunar node model needs it to be.
# ---------------------------------------------------------------------------
POSITION_FLAGS = 65810

# The same word, longhand. Kept alongside the literal rather than deriving one
# from the other on purpose: the literal is the number a measurement can be
# compared against without running anything, and the names are what make the
# frame readable. ``apply_position_flags`` asserts they agree, which is what
# would catch a swisseph release that renumbered a constant -- every name in
# this file would still read correctly while the word they compose changed.
POSITION_FLAG_COMPONENTS: dict[str, int] = {
    "FLG_SWIEPH": swe.FLG_SWIEPH,        #     2  Swiss ephemeris data files
    "FLG_SIDEREAL": swe.FLG_SIDEREAL,    # 65536  sidereal zodiac (Lahiri, set per thread)
    "FLG_TRUEPOS": swe.FLG_TRUEPOS,      #    16  geometric, not apparent, position
    "FLG_SPEED": swe.FLG_SPEED,          #   256  daily motion (retrogression needs it)
}

# The two flags this declaration relies on being applied WITHOUT asking, mapped
# to the declared flag that makes each one redundant. Both entries are measured
# from swisseph's own retflag, not from documentation (see the block above):
# requesting 65810 comes back as 67410, with FLG_NONUT and FLG_NOGDEFL added.
#
# This is what replaces declaring the two flags outright. Their value was never
# the bits -- swisseph sets those either way -- it was that a later edit could
# not quietly make them live. Checked by ``apply_position_flags`` step (0b): if a
# masking flag ever leaves the declared word while its dependent flag is absent,
# the engine refuses to start rather than serving deflected or nutated positions
# under a declaration that does not mention either.
_IMPLIED_BY: dict[str, str] = {
    "FLG_NOGDEFL": "FLG_TRUEPOS",   # geometric positions suppress deflection
    "FLG_NONUT": "FLG_SIDEREAL",    # sidereal positions refer to the mean equinox
}

# Every distinct swisseph position flag, for rendering a word by name in an error
# message. Aliases are excluded deliberately: FLG_DEFAULTEPH is FLG_SWIEPH and
# FLG_ORBEL_AA is FLG_TOPOCTR, so including them would print one bit twice, and
# composites (FLG_ASTROMETRIC = FLG_NOABERR|FLG_NOGDEFL) would print a bit that
# is not a bit. Resolved with getattr so a swisseph that drops a name degrades to
# reporting it as an unnamed bit rather than failing to import.
_SWISSEPH_FLAG_NAMES = (
    "FLG_JPLEPH", "FLG_SWIEPH", "FLG_MOSEPH", "FLG_HELCTR", "FLG_TRUEPOS",
    "FLG_J2000", "FLG_NONUT", "FLG_SPEED3", "FLG_SPEED", "FLG_NOGDEFL",
    "FLG_NOABERR", "FLG_EQUATORIAL", "FLG_XYZ", "FLG_RADIANS", "FLG_BARYCTR",
    "FLG_TOPOCTR", "FLG_SIDEREAL", "FLG_ICRS", "FLG_JPLHOR", "FLG_JPLHOR_APPROX",
    "FLG_CENTER_BODY",
)


def describe_position_flags(word: int) -> str:
    """Render a swisseph flag word as ``<int> = NAME|NAME|...``.

    Error messages about this word are read by someone deciding whether a
    dependency bump is safe. "expected 66386, got 65810" sends them off to
    decompose a bit field by hand; "dropped FLG_NOGDEFL|FLG_NONUT" tells them
    what moved. Bits swisseph does not name are reported as hex rather than
    dropped -- an unnamed bit is precisely the case where a silent renderer
    would make a real difference invisible.
    """
    named = [
        name
        for name in _SWISSEPH_FLAG_NAMES
        if (bit := getattr(swe, name, 0)) and word & bit == bit
    ]
    covered = 0
    for name in named:
        covered |= getattr(swe, name)
    leftover = word & ~covered
    rendered = "|".join(named) if named else "<no named flags>"
    if leftover:
        rendered += f"|<unnamed bits {hex(leftover)}>"
    return f"{word} = {rendered}"


def apply_position_flags() -> None:
    """Pin the astronomy library to POSITION_FLAGS, or refuse to run.

    Fail-closed throughout, and every step is read back after it is applied:
    calling a setter is not evidence it took effect, and the cost of being wrong
    is a reference frame nobody chose.

    Idempotent, and cheap: it reads and writes module attributes and does not
    touch the ephemeris.
    """
    # (0) the declaration must equal its own decomposition
    composed = 0
    for bit in POSITION_FLAG_COMPONENTS.values():
        composed |= bit
    if composed != POSITION_FLAGS:
        raise RuntimeError(
            f"the declared position-flag word {POSITION_FLAGS} does not equal the "
            f"word its own named components compose ({composed}: "
            f"{describe_position_flags(composed)}). Either the declaration and its "
            "decomposition were edited apart, or a swisseph release renumbered one "
            "of these constants -- in which case every name in bphs_core/utils.py "
            "still reads correctly while the reference frame moved underneath it. "
            "Refusing to serve positions in a frame this engine cannot name."
        )

    # (0b) the masking invariant -- what replaces declaring FLG_NOGDEFL/FLG_NONUT
    #
    # Those two are omitted from the declared word because swisseph applies them
    # unasked under flags that ARE declared (measured: requesting 65810 returns
    # retflag 67410, with both added back). The omission is therefore safe only
    # while the masking flag is still declared. Checked before the library
    # comparison below on purpose: step (1) happens to reject some of these cases
    # too, but for the WRONG reason -- it reports a dependency bump and tells the
    # reader to revert it, which is not what a cleared FLG_TRUEPOS is -- and it
    # would not fire at all if the library ever built the same reduced word.
    for omitted, masking in _IMPLIED_BY.items():
        omitted_bit = getattr(swe, omitted, 0)
        masking_bit = getattr(swe, masking, 0)
        if POSITION_FLAGS & omitted_bit:
            continue  # taken explicitly; nothing is being relied on
        if not POSITION_FLAGS & masking_bit:
            raise RuntimeError(
                f"the declared position-flag word omits {omitted}, which is only "
                f"safe while {masking} is declared -- and {masking} is not in "
                f"{describe_position_flags(POSITION_FLAGS)}. swisseph applies "
                f"{omitted} of its own accord under {masking} (measured: a request "
                "of 65810 returns retflag 67410, carrying FLG_NONUT and "
                "FLG_NOGDEFL nobody asked for), which is why this engine stopped "
                f"requesting it at the pyjhora 4.8.7 bump. With {masking} gone "
                f"that mask lifts and {omitted} becomes LIVE -- gravitational "
                "deflection is worth 0.0711 arcsec and the two words separate by "
                "up to 0.128869 arcsec once FLG_TRUEPOS is cleared. Refusing to "
                "serve positions in a frame this engine no longer describes: "
                f"either re-declare {omitted} explicitly, or keep {masking}."
            )

    # (1) the library's own inherited word -- the dependency-bump tripwire
    builder = getattr(jhora_utils, "set_flags_for_planet_positions", None)
    if builder is None:
        raise RuntimeError(
            "the astronomy library no longer exposes "
            "jhora.utils.set_flags_for_planet_positions, so this engine can no "
            "longer tell which position-flag word the library would apply of its "
            "own accord. Refusing to continue rather than inheriting it unseen: "
            "that word decides whether every served longitude is geometric or "
            "apparent (up to 60.54 arcsec) and sidereal or tropical (~24 deg). "
            "Re-establish the declaration against the new library API in the same "
            "change that moves the dependency pin."
        )
    inherited = builder()
    if inherited != POSITION_FLAGS:
        difference = inherited ^ POSITION_FLAGS
        raise RuntimeError(
            "the astronomy library's own position-flag word no longer matches this "
            f"engine's declaration.\n"
            f"    declared by this engine: {describe_position_flags(POSITION_FLAGS)}\n"
            f"    built by the library:    {describe_position_flags(inherited)}\n"
            f"    they differ by:          {describe_position_flags(difference)}\n"
            "This is what a dependency bump looks like when it moves the reference "
            "frame: pyjhora 4.8.6 built 66386 and 4.8.7 built 65810, with no change "
            "in this repository and no golden able to see it. Refusing to start. "
            "Either revert the bump, or -- if the new frame is wanted -- change "
            "POSITION_FLAGS deliberately and re-record the Swiss goldens in the "
            "same reviewed change."
        )

    # (2) drik's mutable serving global, built before this ran
    drik.PLANET_FLAGS = POSITION_FLAGS
    if drik.PLANET_FLAGS != POSITION_FLAGS:
        raise RuntimeError(
            "pinning the declared position-flag word did not take effect: asked for "
            f"{describe_position_flags(POSITION_FLAGS)} but drik.PLANET_FLAGS now "
            f"reports {describe_position_flags(drik.PLANET_FLAGS)}. That global is "
            "what drik.sidereal_longitude, drik.dhasavarga and "
            "drik.planets_in_retrograde read at call time, so every served position "
            "would be in an undeclared frame."
        )

    # (3) the bypass lever this repo cannot set, only verify
    if getattr(jhora_const, "_TROPICAL_MODE", False):
        raise RuntimeError(
            "jhora.const._TROPICAL_MODE is set, so drik.sidereal_longitude ignores "
            "the pinned position-flag word entirely and computes with "
            f"{describe_position_flags(swe.FLG_SWIEPH | swe.FLG_SPEED)} -- tropical "
            "longitudes, roughly 24 degrees from the sidereal ones this engine "
            "declares. Refusing to serve charts in a zodiac it does not declare."
        )


apply_position_flags()


# ---------------------------------------------------------------------------
# The sunrise/sunset CONVENTION word is DECLARED here. It is never inherited.
#
# Every electional and panchanga limb this engine serves is anchored to the day
# boundary: ``drik.sunrise``/``drik.sunset``/``drik.moonrise``/``drik.moonset``,
# and through them the tithi, nakshatra, yoga, karana, the thirty muhurtas, the
# raahu/yamaganda/gulika windows and the whole muhurat/lagna-shuddhi scan. Each
# of those rise/set calls passes a second bit word to swisseph's
# ``swe.rise_trans`` -- the ``rsmi`` argument, DISTINCT from the ephemeris flag
# word POSITION_FLAGS pins. The ``rsmi`` word decides WHAT COUNTS AS SUNRISE:
# whether the Sun's disc centre or its lower limb touches the horizon, whether
# that horizon is the true (geometric) one or the apparent (refracted) one, and
# whether the rise or the set instant is wanted. It is not a tuning knob; it is
# part of what "sunrise" means, and a day whose start moves drags every limb
# measured from it.
#
# Until this block existed the engine stated that word nowhere. It inherited
# ``drik.RISE_FLAGS`` / ``drik.SET_FLAGS``, which the astronomy library builds at
# ITS import time from ``jhora.utils.set_flags_for_rise_set()``, which in turn
# reads three ``jhora.const.RISE_SET_*`` module globals. Measured on pyjhora
# 4.8.6 and RE-measured on the now-pinned 4.8.7 (pyswisseph 2.10.3.2 throughout):
# RISE_FLAGS = 897, SET_FLAGS = 898 on both -- so unlike the position-flag word
# (which moved 66386 -> 65810 on that same bump) this one has not moved. But "has
# not moved" is not "declared": the same three ``const`` globals that build it
# are exactly the shape of default that pyjhora 4.8.7 flipped for the position
# word, and a release that flips ``RISE_SET_USE_REFRACTION`` or
# ``RISE_SET_USE_DISC_CENTER_FOR_RISING`` would move every served sunrise with no
# change in this repository and nothing here to notice it.
#
# ONE NEW WAY THE PIN COULD BE UNDONE, found while reading the 4.8.7 diff and
# recorded because it is not visible from this file. In 4.8.6
# ``drik.refresh_planet_flags(longitude, latitude, elevation)`` took three
# REQUIRED arguments and rebuilt only ``PLANET_FLAGS``. In 4.8.7 all three became
# optional and it now also rebuilds ``RISE_FLAGS`` and ``SET_FLAGS`` from the
# ``const`` globals -- i.e. one no-argument call would silently revert BOTH pins
# applied here. Measured on the installed 4.8.7: the only callers are a
# ``if __name__ == "__main__"`` demo block in drik.py (never executed on import)
# and ``jhora/ui/horo_chart_tabs.py``, a PyQt module this service never imports.
# So nothing on the served path calls it today. If a future release calls it from
# a served entry point, these pins become per-call state rather than import-time
# state, and both appliers would have to move to the call boundary.
#
# THE CONVENTION THIS ENGINE DECLARES: swisseph's BIT_HINDU_RISING (896), which
# is the composite the Vedic (BPHS / Surya-Siddhanta) tradition wants -- the Sun's
# disc CENTRE at the TRUE, unrefracted horizon (geocentric, no ecliptic-latitude
# correction). This is the "madhya-bimba" sunrise of the classical panchanga, and
# it is what ``drik.sunrise``'s own docstring states ("centre of disc at horizon")
# and what the drik source comments call "geometric, i.e. true sunrise/set, so
# refraction is not considered". The civil/almanac convention (upper limb at the
# refracted horizon) is a real and defensible alternative -- it is what a secular
# ephemeris reports, and some panchanga makers use it -- but the choice between
# the two is SETTLED, not open: the geometric disc-centre (Surya-Siddhanta)
# convention is OWNER-RULED (2026-08-17), on the ground that it is the one the
# Siddhantic tithi arithmetic assumes. Changing it is an astronomical decision
# that moves every served day boundary, not an implementation detail.
#
# TWO LEVERS, not three -- there is no runtime bypass here analogous to the
# position word's ``_TROPICAL_MODE``. Measured, not read from documentation:
#
#   1. ``jhora.const.RISE_SET_HINDU_RISING`` / ``_USE_REFRACTION`` /
#      ``_USE_DISC_CENTER_FOR_RISING`` -- three module globals read by
#      ``jhora.utils.set_flags_for_rise_set()`` every time it is called. This is
#      the INHERITED DEFAULT. Measured, flipping each one moves the word to a
#      distinct value: hindu-rising off -> 769/770, refraction on -> 385/386,
#      disc-bottom -> 9089/9090.
#   2. ``drik.RISE_FLAGS`` / ``drik.SET_FLAGS`` -- two MUTABLE module globals,
#      built from (1) at drik's import time (before anything in this package has
#      run), read at call time by ``drik.sunrise`` (``rsmi=RISE_FLAGS``),
#      ``drik.sunset`` (``rsmi=SET_FLAGS``) and the two lunar equivalents.
#
# ``apply_rise_set_flags`` below compares (1) against this declaration and refuses
# to start on any disagreement -- the dependency-bump tripwire, exactly as
# ``apply_position_flags`` does for the position word -- then pins (2) and reads
# both back. It is called at import, after the position word, and
# ``bphs_core/__init__.py`` imports utils first, so the pins land before any
# sibling module uses drik.
#
# SCOPE, stated so it is not discovered later. This is the sunrise/sunset ``rsmi``
# convention word only. The ephemeris frame the same ``rise_trans`` call uses for
# the Sun's position (its ``flags`` argument) is ``drik.PLANET_FLAGS``, already
# pinned by ``apply_position_flags`` above. drik's unrelated module global
# ``_rise_flags`` (an ephemeris word, ``BIT_HINDU_RISING | FLG_TRUEPOS |
# FLG_SPEED``) is NOT on the served sunrise/sunset path -- those functions take
# ``rsmi=RISE_FLAGS``/``SET_FLAGS`` and ``flags=PLANET_FLAGS`` -- and is left out
# of this declaration deliberately.
#
# Contract: tests/test_rise_set_flags.py. Extend it, never weaken it. The
# dependency is pinned to an exact version in pyproject.toml for the same reason
# the position word needs it to be.
# ---------------------------------------------------------------------------
RISE_FLAGS = 897
SET_FLAGS = 898

# The shared convention, longhand, composed from named swisseph constants -- the
# same word RISE_FLAGS and SET_FLAGS share before the rise-vs-set direction bit is
# added. Kept alongside the literals on purpose (same rationale as
# POSITION_FLAG_COMPONENTS): the literal is the number a measurement can be
# compared against without running anything, and the names are what make the
# convention readable. ``apply_rise_set_flags`` asserts they agree, which is what
# would catch a swisseph release that renumbered a constant -- every name here
# would still read correctly while the word they compose changed.
#
# BIT_HINDU_RISING (896) already subsumes BIT_DISC_CENTER (256) and
# BIT_NO_REFRACTION (512) -- it is defined as disc-centre | no-refraction |
# geocentric-no-ecliptic-latitude (the 128 bit, which this swisseph build does
# not export a name for, so BIT_HINDU_RISING is the only name that covers it).
# The two subsets are named anyway, for intent; their OR with BIT_HINDU_RISING is
# still 896.
RISE_SET_CONVENTION_COMPONENTS: dict[str, int] = {
    "BIT_HINDU_RISING": swe.BIT_HINDU_RISING,      #   896  disc-centre, no refraction, geocentric
    "BIT_DISC_CENTER": swe.BIT_DISC_CENTER,        #   256  Sun's disc centre at the horizon
    "BIT_NO_REFRACTION": swe.BIT_NO_REFRACTION,    #   512  true (geometric) horizon, not apparent
}

# The direction bit, the ONLY thing that differs between the rise word and the set
# word: which crossing of the horizon is wanted.
RISE_SET_DIRECTION_COMPONENTS: dict[str, int] = {
    "CALC_RISE": swe.CALC_RISE,                    #     1  the rising instant  -> RISE_FLAGS
    "CALC_SET": swe.CALC_SET,                      #     2  the setting instant -> SET_FLAGS
}

# Every distinct swisseph rise/set flag, for rendering a word by name in an error
# message. Resolved with getattr so a swisseph that drops a name degrades to
# reporting it as an unnamed bit rather than failing to import. BIT_HINDU_RISING
# is listed first so its 896 covers the otherwise-unnamed 128 bit.
_RISE_SET_FLAG_NAMES = (
    "BIT_HINDU_RISING", "BIT_DISC_CENTER", "BIT_DISC_BOTTOM", "BIT_NO_REFRACTION",
    "BIT_GEOCTR_NO_ECL_LAT", "BIT_FIXED_DISC_SIZE",
    "CALC_RISE", "CALC_SET", "CALC_MTRANSIT", "CALC_ITRANSIT",
)


def describe_rise_set_flags(word: int) -> str:
    """Render a swisseph rise/set (``rsmi``) word as ``<int> = NAME|NAME|...``.

    The sibling of ``describe_position_flags`` for the ``rsmi`` namespace. A
    reviewer told "expected 897, got 385" has to decompose a bit word by hand
    under time pressure; told "the library dropped BIT_NO_REFRACTION" they know
    immediately that the horizon model moved from geometric to refracted. Bits
    swisseph does not name are reported as hex rather than dropped -- an unnamed
    bit is precisely the case where a silent renderer would make a real
    difference invisible.
    """
    named = [
        name
        for name in _RISE_SET_FLAG_NAMES
        if (bit := getattr(swe, name, 0)) and word & bit == bit
    ]
    covered = 0
    for name in named:
        covered |= getattr(swe, name)
    leftover = word & ~covered
    rendered = "|".join(named) if named else "<no named flags>"
    if leftover:
        rendered += f"|<unnamed bits {hex(leftover)}>"
    return f"{word} = {rendered}"


def apply_rise_set_flags() -> None:
    """Pin the astronomy library to RISE_FLAGS / SET_FLAGS, or refuse to run.

    Fail-closed throughout, and every step is read back after it is applied:
    calling a setter is not evidence it took effect, and the cost of being wrong
    is a day boundary nobody chose, dragging every panchanga limb with it.

    Idempotent, and cheap: it reads and writes module attributes and does not
    touch the ephemeris.
    """
    # (0) each declared word must equal its own decomposition
    convention = 0
    for bit in RISE_SET_CONVENTION_COMPONENTS.values():
        convention |= bit
    expected_rise = convention | swe.CALC_RISE
    expected_set = convention | swe.CALC_SET
    if RISE_FLAGS != expected_rise or SET_FLAGS != expected_set:
        raise RuntimeError(
            f"the declared rise/set words ({RISE_FLAGS} / {SET_FLAGS}) do not equal "
            f"the words their own named components compose "
            f"({expected_rise} / {expected_set}: "
            f"{describe_rise_set_flags(expected_rise)} / "
            f"{describe_rise_set_flags(expected_set)}). Either the declaration and "
            "its decomposition were edited apart, or a swisseph release renumbered "
            "one of these constants -- in which case every name in bphs_core/utils.py "
            "still reads correctly while the sunrise convention moved underneath it. "
            "Refusing to serve a day boundary this engine cannot name."
        )

    # (1) the library's own inherited words -- the dependency-bump tripwire
    builder = getattr(jhora_utils, "set_flags_for_rise_set", None)
    if builder is None:
        raise RuntimeError(
            "the astronomy library no longer exposes "
            "jhora.utils.set_flags_for_rise_set, so this engine can no longer tell "
            "which sunrise/sunset convention word the library would apply of its own "
            "accord. Refusing to continue rather than inheriting it unseen: that word "
            "decides whether every served sunrise is disc-centre or lower-limb and "
            "geometric or refracted, and every panchanga limb is measured from it. "
            "Re-establish the declaration against the new library API in the same "
            "change that moves the dependency pin."
        )
    inherited_rise = builder(flags_for_rise=True)
    inherited_set = builder(flags_for_rise=False)
    if inherited_rise != RISE_FLAGS or inherited_set != SET_FLAGS:
        raise RuntimeError(
            "the astronomy library's own sunrise/sunset convention word no longer "
            "matches this engine's declaration.\n"
            f"    declared by this engine: rise {describe_rise_set_flags(RISE_FLAGS)}"
            f" / set {describe_rise_set_flags(SET_FLAGS)}\n"
            f"    built by the library:    rise {describe_rise_set_flags(inherited_rise)}"
            f" / set {describe_rise_set_flags(inherited_set)}\n"
            f"    rise differs by:         "
            f"{describe_rise_set_flags(inherited_rise ^ RISE_FLAGS)}\n"
            "This is what a dependency bump looks like when it moves the day "
            "boundary: a release that flips const.RISE_SET_USE_REFRACTION or "
            "const.RISE_SET_USE_DISC_CENTER_FOR_RISING moves every served sunrise "
            "with no change in this repository and no golden able to see it. "
            "Refusing to start. Either revert the bump, or -- if the new convention "
            "is wanted -- change RISE_FLAGS/SET_FLAGS deliberately and re-record the "
            "electional goldens in the same reviewed change."
        )

    # (2) drik's mutable serving globals, built before this ran
    drik.RISE_FLAGS = RISE_FLAGS
    drik.SET_FLAGS = SET_FLAGS
    if drik.RISE_FLAGS != RISE_FLAGS or drik.SET_FLAGS != SET_FLAGS:
        raise RuntimeError(
            "pinning the declared rise/set words did not take effect: asked for "
            f"rise {describe_rise_set_flags(RISE_FLAGS)} / "
            f"set {describe_rise_set_flags(SET_FLAGS)} but drik now reports "
            f"rise {describe_rise_set_flags(drik.RISE_FLAGS)} / "
            f"set {describe_rise_set_flags(drik.SET_FLAGS)}. Those globals are the "
            "rsmi words drik.sunrise, drik.sunset, drik.moonrise and drik.moonset "
            "read at call time, so every served day boundary would be in an "
            "undeclared convention."
        )


apply_rise_set_flags()

EPHE_PATH = os.path.join(os.path.dirname(__file__), "../data/ephe")

# ---------------------------------------------------------------------------
# pyswisseph's state is THREAD-LOCAL, so it must be applied per thread.
#
# pyswisseph 2.10.3.2 ships swisseph's thread-safe (thread-local ``swed``)
# configuration: the ephemeris path and the sidereal/ayanamsa mode are
# per-THREAD, not per-process. Setting them once at import therefore configures
# only the importing thread. Every other thread starts with:
#
#   * no ephemeris path -> swe_calc silently falls back to the built-in Moshier
#     analytical ephemeris. It does NOT raise: it returns a plausible result
#     with SEFLG_MOSEPH set in retflag instead of SEFLG_SWIEPH.
#   * no sidereal mode  -> swisseph's default Fagan/Bradley ayanamsa, which
#     differs from Lahiri by ~0.88 degrees (53 arcmin) — enough to move a
#     nakshatra pada, and a sign near a boundary.
#
# That matters because this service does nearly all of its computing on
# non-importing threads: Starlette's threadpool for the synchronous ``def``
# ``/v1/*`` handlers, and the background scan-job pool in ``app/jobs.py``. The
# mounted Swiss ephemeris data was being bypassed on exactly the paths that
# serve real requests, while ``/healthz``'s ``ephe_loaded`` — a directory
# existence check — reported fine. (Now fixed: ``/healthz`` calls
# ``probe_ephemeris_source()`` below, the same retflag-based detector as the
# accuracy gate, instead of checking whether the directory exists.)
#
# Measured on a CI runner with the data files present (the ``swiss-ephemeris``
# job in .github/workflows/test.yml, which is what surfaced this):
#   main thread                      -> retflag 65602, SEFLG_SWIEPH set
#   worker thread, path not applied  -> retflag 65604, SEFLG_MOSEPH set
#   worker thread, path applied      -> retflag 65602, SEFLG_SWIEPH set
#
# ``_ensure_thread_ephemeris_state()`` applies both settings once per thread and
# ``serialized_ephemeris`` calls it, so every C-library entry point in this
# package is covered by construction rather than by remembering — and
# tests/test_ephemeris_lock.py already pins that every entry point carries that
# decorator.
# ---------------------------------------------------------------------------
_THREAD_EPHEMERIS_STATE = threading.local()


def _apply_ephemeris_state() -> None:
    """Point swisseph at the shipped data and select the Lahiri ayanamsa.

    One definition of "the state this package computes in", so the once-per-thread
    initialiser and the mid-computation restore below cannot drift apart.
    """
    swe.set_ephe_path(EPHE_PATH)
    # Initialize pyjhora ayanamsa mode
    drik.set_ayanamsa_mode('LAHIRI')


def _ensure_thread_ephemeris_state() -> None:
    """Apply the ephemeris path + Lahiri ayanamsa to the CALLING thread, once.

    Idempotent, and after the first call per thread it costs one attribute
    lookup — so it is safe on every serialized entry point.
    """
    if getattr(_THREAD_EPHEMERIS_STATE, "initialised", False):
        return
    _apply_ephemeris_state()
    _THREAD_EPHEMERIS_STATE.initialised = True


def restore_ephemeris_state() -> None:
    """Re-apply the ephemeris state after a deliberate read PAST the data files.

    Reading outside the shipped span does not merely get answered from the
    Moshier fallback for that one Julian Day — swisseph KEEPS the fallback, so a
    subsequent lookup at an IN-span JD silently answers analytically too.
    Measured on a fresh process at the scanned day's own noon::

        probe Moon at 2400-01-09       -> SWISS   (retflag 65602)
        read Moon at 2400-01-29        -> MOSHIER (retflag 65604)   # past the files
        probe Moon at 2400-01-09 again -> MOSHIER (retflag 65604)   # still in span!

    Re-applying the path clears it (the third probe returns 65602 again). That
    matters because ``_ensure_thread_ephemeris_state`` deliberately caches
    "initialised" per thread and so will NOT re-apply anything: nothing else in
    this package restores the engine once a wide search has knocked it over.

    Call this from any limb that searches OUTSIDE the day it was asked about —
    the eclipse finders are the measured case. It costs one ``swe.set_ephe_path``
    (~82 µs, against ~0.32 µs for a ``swe.calc_ut``), so it belongs at
    once-per-limb granularity and never inside a position loop.
    """
    _apply_ephemeris_state()


# Configure the importing thread eagerly, so a direct ``swe.*`` call made
# outside a @serialized_ephemeris entry point (a test, a REPL) behaves as before.
_ensure_thread_ephemeris_state()

# ---------------------------------------------------------------------------
# Process-wide serialization of Swiss-Ephemeris / pyjhora access.
#
# EPHEMERIS_LOCK is a process-wide RLock that every C-library entry point
# holds for the duration of its computation. The path/ayanamsa state it
# guards is THREAD-local (see above) -- pyswisseph's own thread-local
# ``swed`` struct already protects that from a cross-thread race -- so this
# lock is not protecting a shared process-global value. It exists for a
# separate reason: the underlying Swiss Ephemeris C library is not
# documented as safe for concurrent swe_calc/swe_houses calls from multiple
# threads, even once each thread's own state is correctly configured. Two
# thread pools can enter it concurrently in one process: Starlette's
# per-request pool for the synchronous ``def`` route handlers, and the
# background scan-job pool (app/jobs.py). Without serialization the failure
# mode is not necessarily a crash but a silently wrong chart for one of two
# concurrent requests — invisible, and unacceptable for a determinism-first
# engine.
#
# serialized_ephemeris also calls _ensure_thread_ephemeris_state() on EVERY
# invocation, not just once: a thread pool reuses worker threads across
# unrelated requests, so "this thread's first call" recurs for the life of
# the process, not only at startup. Doing that inside the decorator, at
# every entry point, makes the per-thread guarantee structural rather than a
# convention someone has to remember at each new call site.
#
# Every entry point that calls into swisseph/pyjhora must hold this lock
# (apply @serialized_ephemeris) at INNER, millisecond-bounded granularity —
# one chart, one day, one instant, one JD conversion. Never decorate a
# whole scan: a whole-scan hold (seconds to minutes at the API range caps)
# would block every interactive route and the async submit path for the
# scan's remaining duration, reversing the async-scan design's
# "submissions never wait on scan compute" property (see CLAUDE.md). It is
# an RLock so nested entry points — e.g. a per-instant scorer that builds
# a Chart — re-acquire it on the same thread without deadlock. The
# throughput cost of serializing is accepted: these are CPU-bound
# computations on a GIL-bound process, so true parallelism was never
# available; the lock only removes the correctness risk.
# ---------------------------------------------------------------------------
EPHEMERIS_LOCK = threading.RLock()


def serialized_ephemeris(fn):
    """Decorator: run ``fn`` while holding the process-wide ephemeris lock.

    Sets ``_holds_ephemeris_lock`` on the wrapper so the test suite can
    assert every C-library entry point is covered.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with EPHEMERIS_LOCK:
            # Inside the lock: pyswisseph's state is thread-local, so a worker
            # thread must be configured before it computes anything, or it
            # silently runs on the Moshier fallback with a Fagan/Bradley
            # ayanamsa. See _ensure_thread_ephemeris_state's rationale above.
            _ensure_thread_ephemeris_state()
            return fn(*args, **kwargs)

    wrapper._holds_ephemeris_lock = True
    return wrapper


@serialized_ephemeris
def probe_ephemeris_source(
    jd: float | None = None, body: int | None = None
) -> tuple[bool, int]:
    """(swiss_active, retflag) for a sidereal position requesting Swiss data.

    The single canonical Swiss-vs-Moshier detector in this package. A
    directory's existence says nothing about whether swisseph is actually
    reading it: ``os.path.isdir(EPHE_PATH)`` is True for an empty directory
    (exactly what ``mkdir -p data/ephe`` in the Dockerfile leaves behind
    before any volume mount), so a directory-existence check can report
    healthy while every worker thread silently computes on the Moshier
    fallback (CALC-1's original ``/healthz`` defect). This asks swisseph
    directly and reads the FLG_SWIEPH/FLG_MOSEPH bit in its retflag instead
    -- the only reliable detector, because a Swiss request with the data
    files absent still succeeds and returns a plausible result.

    ``body`` defaults to the Sun, which is what every historical caller
    asked for. It is a parameter because the data set is SPLIT across files:
    ``sepl_18.se1`` carries the planets and ``semo_18.se1`` the Moon. A
    Sun-only probe therefore reports FLG_SWIEPH on a data set that is
    missing the Moon file, while the nakshatra, its pada and every dasha in
    the engine quietly come from the fallback. ``app.ephemeris_guard`` asks
    about both.

    ``/healthz`` and ``/source`` (``app/main.py``), the boot guard
    (``app/ephemeris_guard.py``) and the accuracy gate
    (``tests/test_swiss_ephemeris.py``) all call this exact function, so
    there is exactly one classification implementation to keep correct --
    never re-derive ``swiss_active`` from a retflag by hand at a second
    call site.
    """
    if jd is None:
        jd = swe.julday(2000, 1, 1, 12.0)
    if body is None:
        body = swe.SUN
    _values, retflag = swe.calc_ut(jd, body, swe.FLG_SWIEPH | swe.FLG_SIDEREAL)
    swiss_active = bool(retflag & swe.FLG_SWIEPH) and not bool(retflag & swe.FLG_MOSEPH)
    return swiss_active, retflag


SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

# ---------------------------------------------------------------------------
# Retrogression of the shadow grahas: DECLARED, never inherited.
#
# BPHS reads Rahu and Ketu as permanently retrograde (vakri) -- they are the
# lunar nodes, and their motion is always contrary to the grahas. This engine
# serves them that way as a stated astrological decision.
#
# What was actually being served before this declaration existed, measured
# 2026-08-07 on the frozen resolve (pyjhora 4.8.6, pyswisseph 2.10.3.2):
# retrogression reaches a chart through ``drik.planets_in_retrograde``, and
# that function excludes BOTH nodes from its loop unconditionally --
#
#     _planet_list = {p: p_id for p, p_id in planet_list.items()
#                     if p not in [const._RAHU, const._KETU]}
#
# -- so it can never name them, and chart.py's ``pid in retro_planets`` was
# False for Rahu and Ketu on every date. Over 1461 charts (2000-01-01 ..
# 2019-12-27, 5-day steps) both shadow grahas came back retrograde on 0, while
# the same sweep saw Saturn retrograde on 35.93% and Mercury on 19.16% -- the
# sweep could observe retrogression and simply never saw it here. The engine
# was reporting both shadow grahas as permanently DIRECT: the exact inverse of
# the classical reading, on every chart it had ever served.
#
# That zero was structural, not a sampling artefact and not an
# ephemeris-runtime artefact: it reproduced identically against the real Swiss
# data files and against the built-in Moshier fallback.
#
# THE LIBRARY CHANGED THAT IN 4.8.7, and the declaration is what absorbed it.
# The exclusion line above now reads ``if p not in [const._SUN, const._MOON]``,
# so ``drik.planets_in_retrograde`` reports the nodes' COMPUTED direction
# instead of omitting them (the 4.8.7 changelog, which lives only in drik.py's
# module docstring, calls this "Handling Rahu/Ketu retrograde/stationary/
# speed-info for true/mean nodes revised"; its new docstring adds "Rahu/Ketu as
# True nodes - retrograde, stationary or even direct"). Sun and Moon took their
# place in the filter, which changes nothing -- neither ever has negative
# longitude speed, so neither was ever appended.
#
# Measured on the 4.8.7 resolve over 400 instants from 1990-01-01 at 37-day
# steps: the library now reports Rahu retrograde on 72.25% and DIRECT on 27.75%,
# while this engine serves retrograde on 100% of charts. Nothing served moved on
# the bump -- because the flag is declared here and applied by NAME through
# ``graha_is_retrograde``, which ignores ``computed`` for these two. Had it been
# inherited, 4.8.7 would have flipped Rahu/Ketu retrogression on roughly a
# quarter of all charts with nothing in the diff to say so. The override is
# therefore MORE load-bearing than when it was written: it used to turn an
# absence into True, and now overrules a live, contrary answer.
#
# Why this is DECLARED rather than derived from the ephemeris, which is the
# obvious-looking alternative: under the declared TRUE (osculating) node the
# astronomical speed sign is not constant. Measured against the real Swiss
# data over 350400 hourly samples (1990-01-01 .. +40y), the true node's
# longitude speed is positive -- direct -- on 25.82% of them, peaking at
# +0.128202129 deg/day at 2029-06-21 00:00 UT, while the mean node is
# retrograde on 100% of the same span. Deriving served retrogression from the
# speed would therefore report Rahu direct on roughly a quarter of charts;
# the classical reading is a deliberate override of that signal, not a
# restatement of it. Second reason not to derive it: near the turning points
# the sign is ephemeris-source-dependent -- that same 2029-06-21 instant reads
# -0.001408427 deg/day under Moshier -- so a derived flag would not even be
# stable across the two runtimes this repo supports.
#
# Changing this set is an astrological model decision, not an implementation
# detail: it moves ``is_retrograde`` on every served chart. Contract:
# tests/test_shadow_graha_retrogression.py; extend it, never weaken it.
# ---------------------------------------------------------------------------
PERPETUALLY_RETROGRADE_GRAHAS = frozenset({"Rahu", "Ketu"})


def _verify_perpetually_retrograde_grahas() -> None:
    """Refuse to run if the declaration names a graha this engine does not serve.

    The declaration is matched by NAME against ``PLANETS`` at chart-construction
    time. A graha renamed or dropped upstream would make its entry here match
    nothing, silently restoring the library's value with no error anywhere -- a
    control switching itself off when its input goes missing, which is precisely
    the failure this engine refuses. Fail closed at import instead.
    """
    unknown = sorted(PERPETUALLY_RETROGRADE_GRAHAS - set(PLANETS))
    if unknown:
        raise RuntimeError(
            f"PERPETUALLY_RETROGRADE_GRAHAS names {unknown}, which this engine does "
            f"not serve as a graha (PLANETS = {PLANETS}). The declaration is applied "
            "by name, so an unknown name matches nothing and would silently hand "
            "those grahas back to the astronomy library -- which reports both lunar "
            "nodes as never retrograde. Refusing to start rather than serving the "
            "inverse of the declared reading."
        )


_verify_perpetually_retrograde_grahas()


def graha_is_retrograde(graha: str, *, computed: bool) -> bool:
    """Resolve one graha's served retrogression, by NAME.

    ``computed`` is what the astronomy library reported for this graha.
    Members of ``PERPETUALLY_RETROGRADE_GRAHAS`` override it unconditionally --
    including when the library agrees -- so the served value never depends on
    whether a dependency happens to include the nodes in its own calculation.
    Every other graha is passed through untouched.

    Taken by graha NAME, never by an integer id: the two id spaces around this
    engine are not interchangeable (see the boundary below), and Rahu's pyjhora
    planet id is another id space's Uranus.
    """
    if graha in PERPETUALLY_RETROGRADE_GRAHAS:
        return True
    return computed


# ---------------------------------------------------------------------------
# The graha-name -> swisseph-body BOUNDARY.
#
# Two integer id spaces coexist around this engine and they are NOT
# interchangeable:
#
#   * pyjhora's planet indices — the order of PLANETS above (Sun 0, Moon 1,
#     Mars 2, Mercury 3, Jupiter 4, Venus 5, Saturn 6, Rahu 7, Ketu 8). This
#     is the space pyjhora's chart OUTPUTS use (``charts.rasi_chart``,
#     ``drik.dhasavarga``, ``drik.planets_in_retrograde`` return these).
#   * swisseph body ids — what ``swe.calc_ut`` and ``drik.sidereal_longitude``
#     CONSUME (Sun 0, Moon 1, Mercury 2, Venus 3, Mars 4, Jupiter 5, Saturn 6,
#     Uranus 7, Neptune 8, the lunar node 10/11). pyjhora's own docstring on
#     ``sidereal_longitude`` is explicit: "The sequence number of 0 to 8 for
#     planets is not followed by swiss ephemeris".
#
# Sun, Moon and Saturn share the same value in both spaces, which is what
# makes the conflation survivable: a spot check of those three looks right
# while every other graha silently becomes a DIFFERENT CELESTIAL BODY —
# index 2 ("Mars") computes Mercury, 3 ("Mercury") computes Venus, 4
# ("Jupiter") computes Mars, 5 ("Venus") computes Jupiter, 7 ("Rahu")
# computes Uranus and 8 ("Ketu") computes Neptune. Measured with the pinned
# dependency set at 2026-07-31 00:00 UT: index 7 returned 40.7495 deg
# (Uranus) where the true node stood at 305.5916 deg.
#
# The rule this boundary enforces: raw integer body ids never cross a module
# edge. ``graha_sidereal_longitude`` below is the ONLY sanctioned route from
# a graha to ``drik.sidereal_longitude``, and it is keyed by graha NAME — a
# key that exists in neither integer space, so neither kind of int can be
# passed to it at all (either raises KeyError immediately). The table is
# written out longhand from explicit ``swe.*`` constants; never rebuild it
# from ``enumerate(PLANETS)``. tests/test_graha_body_ids.py enforces both
# halves: the served longitudes are asserted per-graha against independent
# computations, and an AST scan fails any new ``sidereal_longitude`` /
# ``calc_ut`` call site outside this module.
# ---------------------------------------------------------------------------
_GRAHA_SWE_BODY: dict[str, int] = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    # The declared lunar node model (see LUNAR_NODE_MODEL above), never a
    # hardcoded 10/11 — the node body is a model DECISION, not a constant.
    "Rahu": LUNAR_NODE_BODY,
}


@serialized_ephemeris
def graha_sidereal_longitude(jd_utc: float, graha: str) -> float:
    """Sidereal (Lahiri) longitude of *graha* at a UTC Julian Day, in [0, 360).

    The single sanctioned boundary between graha names and swisseph body ids
    (rationale above). *jd_utc* must be a true UTC Julian Day —
    ``drik.sidereal_longitude`` requires UTC, unlike pyjhora's place-aware
    functions which take a local-clock JD and subtract the timezone
    themselves (see the Julian Day discipline in CLAUDE.md).

    Ketu is served as exactly Rahu + 180 deg on the declared lunar node
    model. Raises KeyError for anything that is not one of the nine graha
    names — deliberately including every integer, from either id space.
    """
    if graha == "Ketu":
        return (graha_sidereal_longitude(jd_utc, "Rahu") + 180.0) % 360.0
    body = _GRAHA_SWE_BODY.get(graha)
    if body is None:
        raise KeyError(
            f"unknown graha {graha!r}: expected one of "
            f"{[*_GRAHA_SWE_BODY, 'Ketu']}. Integer ids are deliberately "
            "rejected — utils.PLANETS indices and swisseph body ids are "
            "different id spaces (index 2 is Mars in one and Mercury in the "
            "other), and a raw int cannot say which space it belongs to."
        )
    return drik.sidereal_longitude(jd_utc, body)


NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

SIGN_LORDS: dict[str, str] = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
    "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
    "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
    "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
}

# Classical BPHS dignity tables
_EXALTATION: dict[str, str] = {
    "Sun": "Aries", "Moon": "Taurus", "Mars": "Capricorn",
    "Mercury": "Virgo", "Jupiter": "Cancer", "Venus": "Pisces", "Saturn": "Libra",
}
_DEBILITATION: dict[str, str] = {
    "Sun": "Libra", "Moon": "Scorpio", "Mars": "Cancer",
    "Mercury": "Pisces", "Jupiter": "Capricorn", "Venus": "Virgo", "Saturn": "Aries",
}
_OWN_SIGNS: dict[str, list[str]] = {
    "Sun": ["Leo"], "Moon": ["Cancer"], "Mars": ["Aries", "Scorpio"],
    "Mercury": ["Gemini", "Virgo"], "Jupiter": ["Sagittarius", "Pisces"],
    "Venus": ["Taurus", "Libra"], "Saturn": ["Capricorn", "Aquarius"],
}
_MOOLATRIKONA: dict[str, str] = {
    "Sun": "Leo", "Moon": "Taurus", "Mars": "Aries",
    "Mercury": "Virgo", "Jupiter": "Sagittarius", "Venus": "Libra", "Saturn": "Aquarius",
}
_FRIENDLY: dict[str, list[str]] = {
    "Sun": ["Moon", "Mars", "Jupiter"],
    "Moon": ["Sun", "Mercury"],
    "Mars": ["Sun", "Moon", "Jupiter"],
    "Mercury": ["Sun", "Venus"],
    "Jupiter": ["Sun", "Moon", "Mars"],
    "Venus": ["Mercury", "Saturn"],
    "Saturn": ["Mercury", "Venus"],
}
_ENEMY: dict[str, list[str]] = {
    "Sun": ["Venus", "Saturn"],
    "Moon": [],  # Moon has no natural enemies in the BPHS friendship table
    "Mars": ["Mercury"],
    "Mercury": ["Moon"],
    "Jupiter": ["Mercury", "Venus"],
    "Venus": ["Sun", "Moon"],
    "Saturn": ["Sun", "Moon", "Mars"],
}


def longitude_to_sign_and_degree(longitude: float) -> tuple[str, float]:
    longitude = longitude % 360
    return SIGNS[int(longitude // 30)], longitude % 30


def longitude_to_nakshatra(longitude: float) -> str:
    longitude = longitude % 360
    return NAKSHATRAS[int(longitude / (360 / 27))]


def get_sign_lord(sign: str) -> str:
    return SIGN_LORDS.get(sign, "Unknown")


def get_planet_dignity(planet: str, sign: str) -> str:
    if planet in ("Rahu", "Ketu"):
        return "neutral"
    if _EXALTATION.get(planet) == sign:
        return "exalted"
    if _DEBILITATION.get(planet) == sign:
        return "debilitated"
    if sign == _MOOLATRIKONA.get(planet):
        return "moolatrikona"
    if sign in _OWN_SIGNS.get(planet, []):
        return "own sign"
    sign_lord = get_sign_lord(sign)
    if sign_lord in _FRIENDLY.get(planet, []):
        return "friendly"
    if sign_lord in _ENEMY.get(planet, []):
        return "enemy"
    return "neutral"


_WATER_SIGNS = {"Cancer", "Scorpio", "Pisces"}
_FIRE_SIGNS = {"Leo", "Sagittarius", "Aries"}
_GANDANTA_PADA = 360 / 27 / 4  # one nakshatra pada = 3°20' = 3.3333...°


def check_gandanta(sign: str, degrees: float) -> tuple[bool, float]:
    """Return (is_gandanta, proximity_degrees) for a planet at sign/degrees.

    Gandanta zones are the last nakshatra pada of each water sign and
    first pada of the adjacent fire sign (the water→fire junction points
    in the nakshatra wheel: Cancer/Leo, Scorpio/Sagittarius, Pisces/Aries).

    proximity_degrees is the distance to the exact boundary (0 = exactly on cusp).
    """
    if sign in _WATER_SIGNS:
        proximity = 30.0 - degrees  # distance to end of water sign
        return proximity <= _GANDANTA_PADA, round(proximity, 4)
    if sign in _FIRE_SIGNS:
        proximity = degrees  # distance from start of fire sign
        return proximity <= _GANDANTA_PADA, round(proximity, 4)
    return False, round(min(degrees, 30.0 - degrees), 4)


def make_place(name: str, lat: float, lon: float, tz_offset: float) -> drik.Place:
    return drik.Place(name, lat, lon, tz_offset)


def nakshatra_pada_lord(longitude: float) -> str:
    """Return the Vimshottari Nakshatra Pada Lord for a sidereal longitude.

    In pure BPHS, a Nakshatra (13°20') is divided into 4 equal padas (quarters)
    of 3°20' each. There are 108 padas in total (27 nakshatras * 4).
    These 108 padas map sequentially to the 12 signs from Aries to Pisces (9 full cycles).
    The Pada Lord is the lord of the Navamsha sign for that pada.
    """
    longitude = longitude % 360

    # Each pada is exactly 3°20' (200 minutes = 3.33333333333 degrees)
    # Total padas = 108. 360 / 108 = 10/3
    pada_size = 10.0 / 3.0

    # Calculate absolute pada index (0 to 107)
    absolute_pada = int(longitude / pada_size)

    # The signs cycle Aries to Pisces (0 to 11) repeatedly.
    # Pada 0 (Ashwini 1) is Aries.
    sign_index = absolute_pada % 12

    navamsha_sign = SIGNS[sign_index]
    return get_sign_lord(navamsha_sign)


