"""The graha-name -> swisseph-body boundary: id-space conflation guard.

Two integer id spaces coexist around this engine and are NOT interchangeable:

  * ``utils.PLANETS`` indices (pyjhora's planet numbering): Sun 0, Moon 1,
    Mars 2, Mercury 3, Jupiter 4, Venus 5, Saturn 6, Rahu 7, Ketu 8.
  * swisseph body ids (what ``drik.sidereal_longitude`` consumes): Sun 0,
    Moon 1, Mercury 2, Venus 3, Mars 4, Jupiter 5, Saturn 6, Uranus 7,
    Neptune 8, with Rahu the declared lunar node body (``utils.LUNAR_NODE_BODY``).

Sun, Moon and Saturn share the same value in both spaces, so a conflation
survives spot checks while silently serving the WRONG CELESTIAL BODY for
everything else: index 2 ("Mars") computes Mercury, 3 ("Mercury") computes
Venus, 4 ("Jupiter") computes Mars, 5 ("Venus") computes Jupiter, 7 ("Rahu")
computes Uranus and 8 ("Ketu") computes Neptune. Measured on the pinned
dependency set at 2026-07-31 00:00 UT, "Rahu"-as-index-7 returned 40.7495 deg
(Uranus) against the true node's 305.5916 deg — the wrong body, not a small
error.

The sanctioned boundary is ``utils.graha_sidereal_longitude(jd_utc, name)``:
it is keyed by graha NAME, which exists in neither integer space, so neither
kind of raw int can cross it. Every test below asserts the POSITIVE signal —
that the longitude served for a graha is that graha's, against an expected
value computed independently through explicit ``swe.*`` constants — never
merely that a number came back (a wrong-body longitude is a perfectly
plausible number, which is exactly how the conflation survived).

All expected values are computed at test runtime through the same ephemeris
the engine is using, so every assertion holds under BOTH runtimes (Swiss data
present, or the Moshier fallback).
"""
import ast
import datetime
from pathlib import Path

import pytest
import swisseph as swe
from jhora.panchanga import drik

from bphs_core import lagna_shuddhi as ls
from bphs_core import transits as tr
from bphs_core import utils
from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData
from tests.conftest import *  # noqa: F401,F403 — env vars before app imports

# The instant used throughout: 2026-05-26 08:00 IST (the suite's standard
# electional test instant). All positions below are runtime-computed at this JD.
_TZ = 5.5
_JD = swe.julday(2026, 5, 26, 8.0 - _TZ)

# Independent name -> swisseph body reference, written out longhand from
# explicit swe constants — NEVER derived from utils.PLANETS indices and NEVER
# read from the production mapping under test.
_REFERENCE_BODY = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
}


def _expected_longitude(graha: str, jd: float) -> float:
    """Reference sidereal longitude for *graha*, via explicit swe constants."""
    if graha == "Rahu":
        return drik.sidereal_longitude(jd, utils.LUNAR_NODE_BODY)
    if graha == "Ketu":
        return (drik.sidereal_longitude(jd, utils.LUNAR_NODE_BODY) + 180.0) % 360.0
    return drik.sidereal_longitude(jd, _REFERENCE_BODY[graha])


def _minimal_snapshot() -> ChartSnapshot:
    """Minimal ChartSnapshot — the transit computation needs only the Moon."""
    rasi = {
        "Moon": PlanetData(
            planet="Moon", sign="Aries", degrees=5.0,
            nakshatra="Ashwini", dignity="neutral", house=1,
            conjunctions=[], aspects=[], is_retrograde=False,
        )
    }
    return ChartSnapshot(
        person=PersonalData(
            name="T", birth_date=datetime.date(2000, 1, 1),
            birth_time=datetime.time(12, 0), birth_place="X",
            latitude=13.0, longitude=77.6, timezone_offset_hours=_TZ,
        ),
        rasi_chart=rasi, hora_chart={}, drekkana_chart={}, navamsa_chart={},
        decamsa_chart={}, dwadasamsa_chart={}, chaturvimsa_chart={},
        trimshamsa_chart={}, saptamsa_chart={}, shashtyamsa_chart={},
        lagna="Aries", lagna_lord="Mars", ayanamsa_value=0.0,
        house_cusps=[(i * 30.0) for i in range(12)],
    )


def _base_day_data(**over):
    dd = {
        "date": "2026-05-26",
        "sunrise": "06:00",
        "inauspicious_periods": [],
        "auspicious_muhurtas": [],
        "chogadiya": [],
        "panchanga": {"tithi": "Shukla Panchami", "yogam": "Siddhi",
                      "karana": "Bava", "vaara": "Tuesday"},
        "is_eclipse_day": False,
        "is_adhik_maasa": False,
    }
    dd.update(over)
    return dd


# ---------------------------------------------------------------------------
# The boundary function itself
# ---------------------------------------------------------------------------

class TestGrahaBoundary:
    def test_boundary_table_pins_explicit_swisseph_constants(self):
        """The name->body table must be the explicit swe constants (plus the
        declared lunar node), never something rebuilt from utils.PLANETS
        indices — that rebuild is precisely the defect this boundary closes."""
        assert utils._GRAHA_SWE_BODY == {
            "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS,
            "Mercury": swe.MERCURY, "Jupiter": swe.JUPITER,
            "Venus": swe.VENUS, "Saturn": swe.SATURN,
            "Rahu": utils.LUNAR_NODE_BODY,
        }

    def test_computes_the_named_graha_for_all_nine(self):
        for graha in utils.PLANETS:
            got = utils.graha_sidereal_longitude(_JD, graha)
            want = _expected_longitude(graha, _JD)
            assert got == pytest.approx(want, abs=1e-9), (
                f"graha_sidereal_longitude served a longitude {got:.4f} for "
                f"{graha} that is not {graha}'s ({want:.4f})"
            )

    def test_rejects_integer_ids_from_either_space(self):
        """Raw ints must not cross the boundary: 2 is Mars in one id space and
        Mercury in the other, and accepting either recreates the conflation."""
        for bad in (0, 1, 2, 4, 7, 8, 11):
            with pytest.raises(KeyError):
                utils.graha_sidereal_longitude(_JD, bad)

    def test_rejects_unknown_names(self):
        with pytest.raises(KeyError):
            utils.graha_sidereal_longitude(_JD, "Uranus")

    def test_holds_the_ephemeris_lock(self):
        assert getattr(utils.graha_sidereal_longitude,
                       "_holds_ephemeris_lock", False)


class TestGrahaLatitudeBoundary:
    """``utils.graha_ecliptic_latitude``: the same name-keyed boundary, read
    by Shadbala to decide a planetary war (Surya Siddhanta 7.18-21)."""

    def test_computes_the_named_graha(self):
        for graha, body in _REFERENCE_BODY.items():
            want = swe.calc_ut(_JD, body, utils.POSITION_FLAGS)[0][1]
            assert utils.graha_ecliptic_latitude(_JD, graha) == pytest.approx(want, abs=1e-12)
        # Distinct bodies, distinct latitudes: an id-space slip would repeat one.
        lats = {g: utils.graha_ecliptic_latitude(_JD, g) for g in ("Mars", "Mercury", "Venus")}
        assert len(set(lats.values())) == 3

    @pytest.mark.parametrize("bad", [0, 1, 2, 4, 7, "Rahu", "Ketu", "Uranus"])
    def test_rejects_ints_nodes_and_unknown_names(self, bad):
        with pytest.raises(KeyError):
            utils.graha_ecliptic_latitude(_JD, bad)

    def test_holds_the_ephemeris_lock(self):
        assert getattr(utils.graha_ecliptic_latitude, "_holds_ephemeris_lock", False)


# ---------------------------------------------------------------------------
# Transits: every served placement is the named graha's position
# ---------------------------------------------------------------------------

class TestTransitPlacementsAreTheNamedGrahas:
    def test_each_placement_matches_independent_computation(self):
        at = datetime.datetime(2026, 5, 26, 8, 0, 0)
        transits = tr.get_current_transits(_minimal_snapshot(), at,
                                           timezone_offset_hours=_TZ)
        assert set(transits) == set(utils.PLANETS)
        for graha in utils.PLANETS:
            want = _expected_longitude(graha, _JD)
            want_sign, want_deg = utils.longitude_to_sign_and_degree(want)
            want_nak = utils.longitude_to_nakshatra(want)
            got = transits[graha]
            assert got.sign == want_sign, (
                f"transit {graha} served sign {got.sign}, but {graha} is in "
                f"{want_sign} — the wrong celestial body was computed"
            )
            assert got.nakshatra == want_nak
            assert got.degrees == pytest.approx(want_deg % 30.0, abs=1e-3)

    def test_rahu_is_declared_node_and_ketu_exactly_opposite(self):
        at = datetime.datetime(2026, 5, 26, 8, 0, 0)
        transits = tr.get_current_transits(_minimal_snapshot(), at,
                                           timezone_offset_hours=_TZ)
        rahu_want = drik.sidereal_longitude(_JD, utils.LUNAR_NODE_BODY)
        rahu_got = (utils.SIGNS.index(transits["Rahu"].sign) * 30.0
                    + transits["Rahu"].degrees)
        ketu_got = (utils.SIGNS.index(transits["Ketu"].sign) * 30.0
                    + transits["Ketu"].degrees)
        assert rahu_got == pytest.approx(rahu_want, abs=1e-3)
        assert ketu_got == pytest.approx((rahu_want + 180.0) % 360.0, abs=1e-3)


# ---------------------------------------------------------------------------
# Lagna shuddhi: lord placement and malefic count use the named grahas
# ---------------------------------------------------------------------------

class TestScoreInstantUsesTheNamedGrahas:
    def test_lord_house_and_dignity_are_the_lords_own(self):
        """Lagna Aries -> lord Mars. The lord's transit house and dignity must
        derive from MARS's longitude (via explicit swe.MARS), not from
        whatever body index 2 denotes in some other id space (Mercury)."""
        mars_lon = drik.sidereal_longitude(_JD, swe.MARS)
        mars_sign_idx = int(mars_lon // 30) % 12
        want_house = (mars_sign_idx - utils.SIGNS.index("Aries")) % 12 + 1
        want_dignity = utils.get_planet_dignity(
            "Mars", utils.SIGNS[mars_sign_idx])

        _, detail = ls._score_instant(
            _JD, "Aries", "Mars", _base_day_data(), 480, "generic")
        assert detail["lagna_lord_house"] == want_house
        assert detail["lagna_lord_dignity"] == want_dignity

    def test_malefic_count_is_of_the_actual_malefics(self):
        """malefics_in_lagna must count Sun/Mars/Saturn/Rahu/Ketu — computed
        from their own bodies — never Mercury, Uranus or Neptune (what
        indices 2, 7 and 8 denote in swisseph's id space; Uranus and Neptune
        are not grahas in this system at all)."""
        lagna = "Taurus"
        lagna_idx = utils.SIGNS.index(lagna)
        want = sum(
            1 for graha in ("Sun", "Mars", "Saturn", "Rahu", "Ketu")
            if int(_expected_longitude(graha, _JD) // 30) % 12 == lagna_idx
        )
        _, detail = ls._score_instant(
            _JD, lagna, utils.get_sign_lord(lagna), _base_day_data(),
            480, "generic")
        assert detail["malefics_in_lagna"] == want

    def test_graha_computation_failure_surfaces_not_swallowed(self, monkeypatch):
        """A graha whose position cannot be computed must SURFACE as an error,
        never be silently scored as if the lord/malefic limb were fine —
        wrong astrology reported as fine is the fail-closed defect."""
        def _raise(*a, **k):
            raise RuntimeError("ephemeris unavailable")
        monkeypatch.setattr(ls.drik, "sidereal_longitude", _raise)
        with pytest.raises(RuntimeError):
            ls._score_instant(
                _JD, "Aries", "Mars", _base_day_data(), 480, "generic")

    def test_lord_limb_failure_propagates_even_when_all_else_computes(
            self, monkeypatch):
        """Only the LORD's body fails; every other graha computes normally.
        The lord must be a graha the malefic loop never asks for (Mercury —
        lagna Gemini), otherwise the malefic loop's own propagation would
        mask a re-swallowed lord limb: with a malefic lord like Mars, a
        raise-on-that-body patch still escapes through the malefic loop and
        the lord swallow goes undetected. Mutation-verified: re-wrapping
        ONLY the lord block in ``except: pass`` turns exactly this test red."""
        real = ls.drik.sidereal_longitude

        def _mercury_raises(jd, body, *a, **k):
            if body == swe.MERCURY:
                raise RuntimeError("ephemeris unavailable")
            return real(jd, body, *a, **k)

        monkeypatch.setattr(ls.drik, "sidereal_longitude", _mercury_raises)
        with pytest.raises(RuntimeError):
            ls._score_instant(
                _JD, "Gemini", "Mercury", _base_day_data(), 480, "generic")

    def test_malefic_limb_failure_propagates_even_when_lord_computes(
            self, monkeypatch):
        """Only the node body fails (Rahu; Ketu derives from it); the lagna
        lord (Moon, for a Cancer lagna — a body the malefic loop never asks
        for) computes normally. The malefic loop's failure must propagate on
        its own, not ride on the lord limb's."""
        real = ls.drik.sidereal_longitude

        def _node_raises(jd, body, *a, **k):
            if body == utils.LUNAR_NODE_BODY:
                raise RuntimeError("ephemeris unavailable")
            return real(jd, body, *a, **k)

        monkeypatch.setattr(ls.drik, "sidereal_longitude", _node_raises)
        with pytest.raises(RuntimeError):
            ls._score_instant(
                _JD, "Cancer", "Moon", _base_day_data(), 480, "generic")


# ---------------------------------------------------------------------------
# The class guard: no raw body-id ephemeris calls outside the boundary
# ---------------------------------------------------------------------------

_PRODUCTION_PACKAGES = ("bphs_core", "app")
_BOUNDARY_FILE = Path("bphs_core") / "utils.py"
_FORBIDDEN_CALLS = {"sidereal_longitude", "calc_ut"}


def _body_id_calls(tree: ast.AST) -> list[int]:
    """Line numbers of calls to any forbidden per-body ephemeris function.

    Parses the AST (never a text scan): comments and string literals cannot
    defeat it, and both call shapes are covered — ``drik.sidereal_longitude(...)``
    (Attribute) and a bare ``sidereal_longitude(...)`` after a from-import (Name).
    """
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else None)
        if name in _FORBIDDEN_CALLS:
            lines.append(node.lineno)
    return lines


class TestNoRawBodyIdCallsOutsideBoundary:
    def test_only_utils_calls_per_body_ephemeris_functions(self):
        """``drik.sidereal_longitude`` and ``swe.calc_ut`` take a swisseph body
        id, so every call site is a place where the two id spaces can be
        conflated again. Exactly one module — bphs_core/utils.py — is allowed
        to make those calls; everything else must go through the name-keyed
        boundary (``utils.graha_sidereal_longitude`` /
        ``utils.probe_ephemeris_source``)."""
        repo_root = Path(__file__).resolve().parent.parent
        scanned = 0
        offenders: list[str] = []
        boundary_calls = 0
        for package in _PRODUCTION_PACKAGES:
            pkg_dir = repo_root / package
            assert pkg_dir.is_dir(), f"production package {package} not found"
            for py in sorted(pkg_dir.rglob("*.py")):
                rel = py.relative_to(repo_root)
                tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(rel))
                scanned += 1
                hits = _body_id_calls(tree)
                if rel == _BOUNDARY_FILE:
                    boundary_calls = len(hits)
                elif hits:
                    offenders.append(f"{rel}:{','.join(map(str, hits))}")

        # Positive assertions first — a scan that inspected nothing, or a
        # detector that cannot detect, must fail rather than vacuously pass.
        assert scanned >= 15, f"only {scanned} files scanned — wrong root?"
        assert boundary_calls >= 1, (
            "the detector found no per-body ephemeris call even inside "
            "bphs_core/utils.py — the guard is no longer detecting anything"
        )
        assert not offenders, (
            "per-body ephemeris calls outside the sanctioned boundary "
            f"(bphs_core/utils.py): {offenders}. Route them through "
            "utils.graha_sidereal_longitude(jd_utc, graha_name) — raw body "
            "ids conflate utils.PLANETS indices with swisseph ids."
        )
