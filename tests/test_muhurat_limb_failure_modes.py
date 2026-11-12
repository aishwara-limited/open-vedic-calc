"""Per-limb failure-mode contract for ``compute_muhurat_for_day``.

Project decision, 2026-08-17: **a limb failure that can change WHICH time is
recommended must RAISE (fail loud); only genuinely supplementary limbs may
degrade, and then only behind an explicit per-limb flag.**

The module used to answer every limb failure the same way — a log line plus a
default, a dropped window, or a ``None`` — so a day assembled from a broken
frame was indistinguishable on the wire from a day assembled from a good one.
Two properties close that, and this file is their contract:

* Every limb whose failure moves the recommendation raises
  :class:`~bphs_core.muhurat.MuhurtaLimbError`, which names the limb.
* Every remaining limb degrades **visibly**: the served field falls back to its
  documented sentinel, the limb's own name is appended to ``degraded_limbs``,
  and the summary ``degraded`` flag is derived from that list, so the two can
  never disagree.

Why the split is drawn where it is — measured against the scan pipeline, not
assumed. ``bphs_core/lagna_shuddhi.py`` builds the entire candidate-minute set
for a day from ``auspicious_muhurtas`` + the favourable ``chogadiya`` windows
(``_candidate_minutes``); it hard-excludes on the Rahu/Yamaganda/Gulika windows
and, per activity, on Durmuhurtam/Varjyam, the Vishti karana, the eclipse flag
and the adhika-maasa flag; it scores on the tithi/yoga and derives the hora lord
and vaara from the served ``sunrise``/``date``. (The tithi, karana and yoga it
reads are evaluated at the candidate instant, not taken from the day's names;
the day's tithi/karana NAMES still raise because they ARE the served day
panchanga.) A limb feeding any of those decides which minute is recommended, and a dropped window or a ``None`` there does not make
the engine cautious — it silently deletes a veto or a candidate. The limbs with
**zero** reads anywhere in the scan pipeline (moonrise, moonset, the four
end-times, the amrita windows, the 30-muhurta display table, the personal
balam strings) are the ones that may degrade.

``TestEveryDrikLimbIsClassified`` is the guard on the split itself: it discovers
the ``drik`` entry points by PARSING the module (not grepping it), requires each
one to carry a recorded classification, and drives each to failure to confirm
the recorded outcome is the one that actually happens. A limb added later
without a classification fails here rather than shipping silent.
"""
import ast
import datetime as dt
import pathlib

import pytest

from bphs_core import muhurat as m
from bphs_core import utils

PLACE = utils.make_place("Sample City", 7.0, 80.0, 5.5)
TARGET = dt.date(2026, 5, 26)

# A latitude/date where the Sun neither rises nor sets. See
# TestDayFrameSentinelIsNotAClock for what the library returns here.
POLAR_PLACE = utils.make_place("Polar Sample", 78.0, 15.0, 1.0)
POLAR_DATE = dt.date(2026, 6, 21)


def _raise(*_a, **_k):
    raise RuntimeError("ephemeris unavailable")


# Several ``drik`` entry points call one another INTERNALLY — re-measured on the
# pinned pyjhora 4.8.7: the body of ``drik.karana`` calls ``drik.tithi``, and the
# body of ``drik.varjyam`` calls ``drik.nakshatra``. The relationship is unchanged
# from 4.8.6. It is recorded as a caller/callee pair rather than as a location in
# the vendored file, because on that bump the relationship held while the
# locations moved — so the pair is what survives a bump, and the pair is what is
# re-read on the next one. A permanently
# patched function therefore does not simulate "this limb failed"; it simulates
# "the library is broken", and the failure surfaces on a DIFFERENT limb than the
# one under test (patching ``nakshatra`` to raise forever fails ``varjyam``,
# which raises, so the nakshatra-end degradation is never reached).
#
# ``compute_muhurat_for_day`` calls each limb exactly once, in the order the
# module documents, so sabotaging only the FIRST call targets precisely the limb
# that owns it and leaves every later internal call intact.

def _fail_first(real):
    """Raise on the first call, delegate to *real* thereafter."""
    calls = {"n": 0}

    def wrapped(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ephemeris unavailable")
        return real(*a, **k)

    return wrapped


def _stub_first(real, value):
    """Return *value* on the first call, delegate to *real* thereafter."""
    calls = {"n": 0}

    def wrapped(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return value
        return real(*a, **k)

    return wrapped


def _patch_first_failure(monkeypatch, attr):
    monkeypatch.setattr(m.drik, attr, _fail_first(getattr(m.drik, attr)))


RAISE = "raise"
DEGRADE = "degrade"

# The recorded classification, keyed by the ``drik`` entry point the limb calls.
#
#   RAISE   -> (RAISE, <MuhurtaLimbError.limb>)
#   DEGRADE -> (DEGRADE, <token appended to degraded_limbs>)
#
# ``next_solar_eclipse`` / ``next_lunar_eclipse`` are two entry points behind one
# handler, hence one shared limb name.
LIMB_CLASSIFICATION: dict[str, tuple[str, str]] = {
    # --- the day frame: everything else is measured from it ---
    "sunrise": (RAISE, "sunrise"),
    "sunset": (RAISE, "sunset"),
    # --- primary panchanga limbs the scorer reads by NAME ---
    "tithi": (RAISE, "tithi"),
    "karana": (RAISE, "karana"),
    # --- candidate-window sources: _candidate_minutes is built from these ---
    "abhijit_muhurta": (RAISE, "abhijit_muhurta"),
    "brahma_muhurtha": (RAISE, "brahma_muhurtha"),
    "vijaya_muhurtha": (RAISE, "vijaya_muhurtha"),
    "godhuli_muhurtha": (RAISE, "godhuli_muhurtha"),
    "nishita_muhurtha": (RAISE, "nishita_muhurtha"),
    "gauri_choghadiya": (RAISE, "chogadiya"),
    # --- absolute classical vetoes ---
    "raahu_kaalam": (RAISE, "rahu_kaalam"),
    "yamaganda_kaalam": (RAISE, "yamaganda_kaalam"),
    "gulikai_kaalam": (RAISE, "gulikai_kaalam"),
    # --- per-activity vetoes: a dropped window silently clears the veto ---
    "durmuhurtam": (RAISE, "durmuhurtam"),
    "varjyam": (RAISE, "varjyam"),
    "panchaka_rahitha": (RAISE, "panchaka"),
    "next_solar_eclipse": (RAISE, "eclipse"),
    "next_lunar_eclipse": (RAISE, "eclipse"),
    "lunar_month": (RAISE, "adhik_maasa"),
    # --- supplementary: zero reads in the scan pipeline ---
    "moonrise": (DEGRADE, "moonrise"),
    "moonset": (DEGRADE, "moonset"),
    "nakshatra": (DEGRADE, "panchanga.nakshatra_end"),
    "yogam": (DEGRADE, "panchanga.yogam_end"),
    "amrita_gadiya": (DEGRADE, "amrita_periods"),
    "muhurthas": (DEGRADE, "all_muhurtas"),
}

# ``drik`` attributes the module touches that are not limb computations: the
# Place type used in annotations and the ayanamsa setter. Asserted to be present
# below, so a stale exclusion cannot quietly shrink the swept set.
NON_LIMB_DRIK_ATTRS = {"Place", "set_ayanamsa_mode"}


def _drik_attrs_used() -> set[str]:
    """Every ``drik.<attr>`` the muhurat module references, by PARSING it.

    A regex over the source would be defeated by the attribute names that appear
    inside this module's (extensive) comments and docstrings; the AST sees only
    real attribute accesses.
    """
    tree = ast.parse(pathlib.Path(m.__file__).read_text(encoding="utf-8"))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "drik"
    }


# ---------------------------------------------------------------------------
# The classification is complete, and it is the one that actually happens
# ---------------------------------------------------------------------------

class TestEveryDrikLimbIsClassified:
    def test_exclusions_are_real(self):
        """A name excluded from the sweep must actually be used by the module."""
        used = _drik_attrs_used()
        assert NON_LIMB_DRIK_ATTRS <= used, (
            f"stale exclusion(s): {NON_LIMB_DRIK_ATTRS - used}"
        )

    def test_every_limb_carries_a_classification(self):
        """A new ``drik`` limb with no recorded failure mode fails here.

        Floors what it compared: 'no unclassified limbs' is vacuously true of an
        empty discovery.
        """
        used = _drik_attrs_used() - NON_LIMB_DRIK_ATTRS
        assert len(used) >= 20, f"AST discovery found only {len(used)} limbs"
        assert used == set(LIMB_CLASSIFICATION), (
            f"unclassified: {used - set(LIMB_CLASSIFICATION)}; "
            f"stale: {set(LIMB_CLASSIFICATION) - used}"
        )

    @pytest.mark.parametrize(
        "attr", sorted(k for k, v in LIMB_CLASSIFICATION.items() if v[0] == RAISE)
    )
    def test_recommendation_affecting_limb_raises(self, monkeypatch, attr):
        expected_limb = LIMB_CLASSIFICATION[attr][1]
        _patch_first_failure(monkeypatch, attr)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == expected_limb
        # The message must name the limb — a caller reading only str(exc) has to
        # be able to tell WHICH limb failed.
        assert expected_limb in str(exc.value)
        # The original failure is preserved for diagnosis, never discarded.
        assert isinstance(exc.value.__cause__, RuntimeError)

    @pytest.mark.parametrize(
        "attr", sorted(k for k, v in LIMB_CLASSIFICATION.items() if v[0] == DEGRADE)
    )
    def test_supplementary_limb_degrades_with_an_explicit_flag(
        self, monkeypatch, attr
    ):
        expected_token = LIMB_CLASSIFICATION[attr][1]
        _patch_first_failure(monkeypatch, attr)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["degraded"] is True
        assert expected_token in out["degraded_limbs"], (
            f"{attr} degraded without naming itself: {out['degraded_limbs']}"
        )


# ---------------------------------------------------------------------------
# The day frame
# ---------------------------------------------------------------------------

class TestDayFrameSentinelIsNotAClock:
    """A no-rise/no-set day must not be served as a clock time.

    ``drik.sunrise``/``sunset`` do NOT raise where the Sun neither rises nor
    sets — they return a large negative sentinel (measured across |lat| 67..89 x
    3 longitudes x 10 dates: 372 of 600 samples out of range, every one in
    [-59073516.0, -59064996.0]; the other 228 were real events). ``fh % 24``
    turns that sentinel into a plausible wall-clock string, so the pre-decision
    code served Svalbard 2026-06-21 as sunrise 13:00 / sunset 13:00 with
    ``degraded: False``, ``hard_gate_failed: False``, 30 muhurtas, 16 chogadiya
    windows and three zero-width absolute-veto windows — a complete, clean-
    looking recommendation built on a frame that does not exist.

    The exception handler could never have caught it: nothing raised.
    """

    def test_polar_day_raises_naming_the_edge(self):
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(POLAR_PLACE, POLAR_DATE)
        assert exc.value.limb == "sunrise"
        # The edge is named, so the failure is diagnosable rather than generic.
        assert "rise" in str(exc.value).lower()

    def test_ordinary_day_is_unaffected(self):
        """The bound must not reject legitimate events.

        Measured over 5980 rise/set samples (lat -66..66 step 6, 5 longitudes,
        13 dates): min 0.0033 h, max 26.0241 h, none outside [0, 48). Events
        after local midnight legitimately exceed 24, which is why the bound is
        one full wrap wide and not [0, 24).
        """
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["degraded"] is False
        assert out["degraded_limbs"] == []
        assert len(out["sunrise"]) == 5 and len(out["sunset"]) == 5

    def test_out_of_range_sunrise_hours_raise(self, monkeypatch):
        """The sentinel is rejected by VALUE, not by which function produced it."""
        real = m.drik.sunrise
        monkeypatch.setattr(m.drik, "sunrise", _stub_first(real, [-59069099.0, "", 0.0]))
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "sunrise"

    def test_out_of_range_moon_hours_degrade(self, monkeypatch):
        """The same sentinel on a supplementary limb degrades instead."""
        real = m.drik.moonrise
        monkeypatch.setattr(m.drik, "moonrise", _stub_first(real, [-59069099.0, "", 0.0]))
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["moonrise"] is None
        assert "moonrise" in out["degraded_limbs"]


# ---------------------------------------------------------------------------
# Value vs end-time: one call, two failure modes
# ---------------------------------------------------------------------------

class TestValueAndEndTimeAreClassifiedSeparately:
    """``drik.tithi``/``karana`` yield both a NAME and an END TIME.

    The name is a primary limb of the recommendation (the scorer reads the tithi
    name for rikta/amavasya and the karana name for the Vishti veto); the end
    time has zero reads anywhere in the pipeline. So the same call carries two
    different failure modes, and they are handled separately rather than both
    collapsing to a degraded day.
    """

    def test_tithi_end_alone_degrades(self, monkeypatch):
        # A well-formed index with an unusable end field: the NAME survives.
        monkeypatch.setattr(m.drik, "tithi", _stub_first(m.drik.tithi, (5, 0.0, None)))
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchanga"]["tithi"] is not None
        assert out["panchanga"]["tithi_end"] is None
        assert "panchanga.tithi_end" in out["degraded_limbs"]

    def test_karana_end_alone_degrades(self, monkeypatch):
        monkeypatch.setattr(m.drik, "karana", _stub_first(m.drik.karana, (3, 0.0, None)))
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchanga"]["karana"] is not None
        assert out["panchanga"]["karana_end"] is None
        assert "panchanga.karana_end" in out["degraded_limbs"]

    def test_tithi_name_failure_raises(self, monkeypatch):
        """An out-of-range index is a NAME failure, not an end-time failure."""
        monkeypatch.setattr(m.drik, "tithi", _stub_first(m.drik.tithi, (99, 0.0, 7.5)))
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "tithi"

    def test_nakshatra_name_survives_an_end_time_failure(self, monkeypatch):
        """The nakshatra/yoga NAMES come from the longitudes, not from drik, so
        only their end-times can degrade."""
        _patch_first_failure(monkeypatch, "nakshatra")
        _patch_first_failure(monkeypatch, "yogam")
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchanga"]["nakshatra"] in utils.NAKSHATRAS
        assert out["panchanga"]["yogam"] in m.YOGAS
        assert out["panchanga"]["nakshatra_end"] is None
        assert out["panchanga"]["yogam_end"] is None
        assert {"panchanga.nakshatra_end", "panchanga.yogam_end"} <= set(
            out["degraded_limbs"]
        )


# ---------------------------------------------------------------------------
# Personal balam: 'Unknown' stays, but stops being silent
# ---------------------------------------------------------------------------

class TestPersonalBalamDegradesExplicitly:
    """'Unknown' is a VISIBLE degradation downstream (penalty + band cap at
    Fair), so the limb keeps degrading — but it used to do so with no log line
    and no flag at all, which is the half this decision changes."""

    def test_bad_birth_nakshatra_names_the_limb(self):
        out = m.compute_muhurat_for_day(
            PLACE, TARGET,
            birth_nakshatra="NotANakshatra", birth_moon_sign="Taurus",
        )
        assert out["personal_balam"]["tara_bala"] == "Unknown"
        assert "personal_balam.tara_bala" in out["degraded_limbs"]
        assert out["degraded"] is True

    def test_bad_birth_moon_sign_names_the_limb(self):
        out = m.compute_muhurat_for_day(
            PLACE, TARGET,
            birth_nakshatra="Rohini", birth_moon_sign="NotASign",
        )
        assert out["personal_balam"]["chandra_bala"] == "Unknown"
        assert "personal_balam.chandra_bala" in out["degraded_limbs"]


# ---------------------------------------------------------------------------
# The summary flag and the per-limb list cannot disagree
# ---------------------------------------------------------------------------

class TestDegradedFlagIsDerived:
    def test_clean_day_has_neither(self):
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["degraded"] is False
        assert out["degraded_limbs"] == []

    @pytest.mark.parametrize(
        "attr", sorted(k for k, v in LIMB_CLASSIFICATION.items() if v[0] == DEGRADE)
    )
    def test_flag_equals_list_emptiness(self, monkeypatch, attr):
        """``degraded`` is DERIVED from ``degraded_limbs`` — a limb that sets one
        without the other cannot exist."""
        _patch_first_failure(monkeypatch, attr)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["degraded"] == bool(out["degraded_limbs"])

    def test_limbs_are_reported_once_each(self, monkeypatch):
        _patch_first_failure(monkeypatch, "moonrise")
        _patch_first_failure(monkeypatch, "moonset")
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        limbs = out["degraded_limbs"]
        assert sorted(limbs) == sorted(set(limbs))
        assert {"moonrise", "moonset"} <= set(limbs)


# ---------------------------------------------------------------------------
# The vetoes that used to resolve to None now cannot
# ---------------------------------------------------------------------------

class TestUnverifiableVetoesRaise:
    """``is_eclipse_day`` / ``is_adhik_maasa`` / ``panchaka_free`` used to carry
    ``None`` for 'could not be computed'. Downstream, ``None`` vetoes — which
    means an unverifiable limb silently DELETED candidate days from the scan
    while the response looked well formed. The flags stay nullable on the wire
    (the consumer-side fail-closed guard is still the right behaviour for a
    payload that carries one), but this producer no longer emits ``None``."""

    def test_eclipse_finder_failure_raises(self, monkeypatch):
        _patch_first_failure(monkeypatch, "next_solar_eclipse")
        _patch_first_failure(monkeypatch, "next_lunar_eclipse")
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "eclipse"

    def test_adhik_maasa_failure_raises(self, monkeypatch):
        _patch_first_failure(monkeypatch, "lunar_month")
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "adhik_maasa"

    def test_panchaka_failure_raises(self, monkeypatch):
        _patch_first_failure(monkeypatch, "panchaka_rahitha")
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "panchaka"

    def test_clean_day_resolves_every_veto_to_a_bool(self):
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["is_eclipse_day"] in (True, False)
        assert out["is_adhik_maasa"] in (True, False)
        assert out["panchaka_free"] in (True, False)


# ---------------------------------------------------------------------------
# The error type itself
# ---------------------------------------------------------------------------

class TestMuhurtaLimbError:
    def test_carries_the_limb_and_the_date(self):
        err = m.MuhurtaLimbError("sunrise", dt.date(2026, 5, 26), "hint text")
        assert err.limb == "sunrise"
        assert "sunrise" in str(err)
        assert "2026-05-26" in str(err)
        assert "hint text" in str(err)

    def test_is_not_swallowed_by_a_bare_handler_upstream(self, monkeypatch):
        """A limb that raises must not be re-wrapped by a later guard into a
        degraded day — the raise has to leave the function."""
        _patch_first_failure(monkeypatch, "raahu_kaalam")
        with pytest.raises(m.MuhurtaLimbError):
            m.compute_muhurat_for_day(PLACE, TARGET)


class TestGuardsDoNotAbsorbALimbError:
    """The guards themselves, exercised directly.

    Both context managers re-raise a ``MuhurtaLimbError`` untouched. That is the
    property that makes 'this limb raises' true END TO END rather than true only
    until some enclosing guard catches it: a ``_degradable`` block that absorbed
    one would silently convert a recommendation-affecting failure back into a
    degraded day, which is the exact shape this decision removes.
    """

    def test_degradable_does_not_absorb_a_limb_error(self):
        limbs: list[str] = []
        with pytest.raises(m.MuhurtaLimbError):
            with m._degradable("some.field", limbs, "some_event"):
                raise m.MuhurtaLimbError("inner", TARGET)
        assert limbs == []

    def test_degradable_records_an_ordinary_failure(self):
        limbs: list[str] = []
        with m._degradable("some.field", limbs, "some_event"):
            raise RuntimeError("ordinary failure")
        assert limbs == ["some.field"]

    def test_degradable_records_each_field_once(self):
        """A limb guarded twice (e.g. a retry) reports once, so the list stays a
        set of names rather than a failure count."""
        limbs: list[str] = []
        for _ in range(3):
            with m._degradable("some.field", limbs, "some_event"):
                raise RuntimeError("ordinary failure")
        assert limbs == ["some.field"]

    def test_require_does_not_rewrap_a_limb_error(self):
        """An inner limb keeps its own identity — the outer guard must not
        relabel it and hide which limb actually failed."""
        inner = m.MuhurtaLimbError("inner", TARGET)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            with m._require("outer", TARGET, "outer_event"):
                raise inner
        assert exc.value is inner
        assert exc.value.limb == "inner"

    def test_require_message_without_a_hint(self):
        with pytest.raises(m.MuhurtaLimbError) as exc:
            with m._require("outer", TARGET, "outer_event"):
                raise RuntimeError("boom")
        assert exc.value.hint == ""
        assert "outer" in str(exc.value)


class TestTheEndpointSurfacesTheFailure:
    """End to end: a recommendation-affecting limb failure must not be servable
    as a well-formed day.

    The point of raising is what the CALLER sees. A limb error is surfaced by
    the synchronous route as a structured 422 naming the failed limb (register
    #285) rather than being rendered into a 200 carrying a partial day, and
    rather than an opaque 500 the caller cannot attribute to a limb — 'an empty
    field a consumer cannot distinguish from a real answer is worse than a 500'
    is this repo's own standing rule, and this is the case it was written for.
    The route envelope itself is pinned in tests/test_muhurat_limb_error_route.py;
    this case proves the real engine raise reaches that envelope end to end.
    """

    def _request(self):
        from tests.conftest import SAMPLE_A
        return {**SAMPLE_A, "start_date": "2026-05-26", "end_date": "2026-05-26"}

    def test_clean_day_serves_200_with_the_new_field(self):
        from tests.test_coverage import client
        r = client.post("/v1/muhurat", json=self._request())
        assert r.status_code == 200
        day = r.json()["days"][0]
        assert day["degraded"] is False
        assert day["degraded_limbs"] == []

    def test_limb_failure_is_not_served_as_a_200(self, monkeypatch):
        from bphs_core import muhurat as mod
        from tests.test_coverage import client
        _patch_first_failure(monkeypatch, "gauri_choghadiya")
        assert mod.drik is m.drik  # one shared module object, so the patch applies
        # gauri_choghadiya feeds the chogadiya windows — a recommendation-
        # affecting limb — so it RAISES MuhurtaLimbError, which the route surfaces
        # as a structured 422 naming the limb (register #285): never a 200 with a
        # partial day, never an opaque 500.
        r = client.post("/v1/muhurat", json=self._request())
        assert r.status_code == 422, r.text
        body = r.json()
        assert "days" not in body  # not served as a well-formed day
        detail = body["detail"]
        assert detail["code"] == "muhurat_limb_error"
        assert detail["limb"] == "chogadiya"


class TestEventHoursValidator:
    def test_accepts_a_legitimate_event(self):
        assert m._event_hours(6.5) == 6.5
        # After local midnight — legitimately past 24 (measured max 26.0241).
        assert m._event_hours(25.5) == 25.5

    @pytest.mark.parametrize("bad", [-59069099.0, -0.5, 48.0, 96.0, float("nan")])
    def test_rejects_out_of_band_values(self, bad):
        with pytest.raises(ValueError):
            m._event_hours(bad)

    @pytest.mark.parametrize("bad", ["06:00", None, True, [6.0]])
    def test_rejects_non_numeric(self, bad):
        """``True`` is rejected explicitly: bool is a subclass of int, so a
        stray flag would otherwise validate as hour 1."""
        with pytest.raises(TypeError):
            m._event_hours(bad)
