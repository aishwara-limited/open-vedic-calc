"""Fail-closed semantics for the panchanga pipeline.

Covers the direct longitude-based limb computation and every fail-closed path:
a tithi crash, a hard-gate (Rahu/Yama/Gulika) failure, eclipse/adhika-maasa
'could not be computed', the Amavasya naming + veto, and the
Unknown-vs-NoBirthData band/penalty split. The mandate for an electional engine
is that a missing limb means 'not recommendable / visibly degraded', never
'fine'.

Failure-mode decision, 2026-08-17 — this file is STRENGTHENED by it, not
weakened. The mandate above is unchanged; what changed is how loudly the
producer states it. A limb whose failure can change WHICH time is recommended
now RAISES ``MuhurtaLimbError`` instead of resolving to a degraded value:
the tithi/karana names, the three absolute vetoes (which used to set
``hard_gate_failed``), and the eclipse / adhika-maasa / panchaka flags (which
used to resolve to ``None``). An exception is the most visible form of 'not
recommendable' available, and it removes the reader's opportunity to
mis-handle a null. The consumer-side gates that read those values fail closed
exactly as before — ``_score_instant`` still hard-excludes on
``hard_gate_failed`` and on ``is_eclipse_day``/``is_adhik_maasa`` being
``None`` — and those gates are still asserted below, because a day payload
built by anything other than this producer can still carry them.

The per-limb classification for all of ``compute_muhurat_for_day`` is pinned by
tests/test_muhurat_limb_failure_modes.py.

Branch anchors below are named by function in bphs_core/lagna_shuddhi.py:

The ``# <symbol>: ...`` comments in this file are CITATIONS into that module,
resolved on every CI run by ``ci/tests/test_stable_anchor_citations.py``.  The
declaration line above is the Form B header lifted to module scope, which is
what gives a comment -- a construct with no enclosing AST scope to inherit an
owner from -- a machine-readable one.  A scope declares exactly ONE subject
module, so an anchor into any other (``bphs_core/muhurat.py``, for instance) is
spelled in full as ``<path>.py::<symbol>`` rather than as a bare comment opener,
and prose that is not a citation is not written in the ``Word: ...`` shape.

All ``drik`` monkeypatching targets ``bphs_core.muhurat.drik`` (for muhurat) or
``bphs_core.lagna_shuddhi.drik`` (for the scorer). Both attributes name the ONE
shared ``jhora.panchanga.drik`` module object, so a patch placed on it is also
seen by ``utils.graha_sidereal_longitude`` — the name -> body boundary the
per-graha longitude calls now route through.
"""
import logging
from datetime import date

import pytest

from bphs_core import lagna_shuddhi as ls
from bphs_core import muhurat as m
from bphs_core import utils

PLACE = utils.make_place("Sample City", 7.0, 80.0, 5.5)
TARGET = date(2026, 5, 26)


def _raise(*_a, **_k):
    raise RuntimeError("ephemeris unavailable")


# ---------------------------------------------------------------------------
# Direct nakshatra / yoga computation from sidereal longitudes
# ---------------------------------------------------------------------------

class TestDirectLimbComputation:
    def test_get_tithi_name_30_is_amavasya(self):
        assert m.get_tithi_name(30) == "Krishna Amavasya"

    def test_nakshatra_from_moon_real_ephemeris(self):
        """Returns a valid nakshatra name and a 1..27 index against the real
        ephemeris on TARGET."""
        import swisseph as swe
        jd = swe.julday(TARGET.year, TARGET.month, TARGET.day, 12.0)
        name, idx = m._nakshatra_from_moon(jd)
        assert name in utils.NAKSHATRAS
        assert 1 <= idx <= 27
        # name and the 1-based index must agree
        assert utils.NAKSHATRAS[idx - 1] == name

    def test_yoga_from_sun_moon_real_ephemeris(self):
        import swisseph as swe
        jd = swe.julday(TARGET.year, TARGET.month, TARGET.day, 12.0)
        name, idx = m._yoga_from_sun_moon(jd)
        assert name in m.YOGAS
        assert 1 <= idx <= 27
        assert m.YOGAS[idx - 1] == name


# ---------------------------------------------------------------------------
# Tithi crash fails closed (no propagation, degraded, name None)
# ---------------------------------------------------------------------------

class TestTithiFailClosed:
    def test_tithi_zero_division_raises(self, monkeypatch, caplog):
        """A tithi crash surfaces as a named limb error, still logging its event.

        This used to serve ``tithi: None`` on a degraded day. The scorer reads
        the tithi NAME (rikta / Amavasya), so a null there scored the day as
        merely 'not suitable' — a quieter and materially different statement
        than 'this day could not be computed'.
        """
        def _zero_div(*_a, **_k):
            raise ZeroDivisionError("division by zero at exact phase boundary")

        monkeypatch.setattr(m.drik, "tithi", _zero_div)
        with caplog.at_level(logging.WARNING, logger="bphs_core.muhurat"):
            with pytest.raises(m.MuhurtaLimbError) as exc:
                m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "tithi"
        assert isinstance(exc.value.__cause__, ZeroDivisionError)
        assert any("muhurat_tithi_failed" in r.message for r in caplog.records)

    def test_karana_failure_fails_closed(self, monkeypatch):
        """The karana NAME carries the Bhadra (Vishti) veto, which the scorer
        applies as ``karana == "Vishti"``. A null name read there as the empty
        string, so an unverifiable Bhadra silently became a clean one."""
        monkeypatch.setattr(m.drik, "karana", _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "karana"

    def test_a_failed_end_time_alone_still_only_degrades(self, monkeypatch):
        """The refinement half of the same call is NOT recommendation-affecting:
        the four panchanga end-times have zero reads in the scan pipeline."""
        real = m.drik.tithi
        calls = {"n": 0}

        def _bad_end(*a, **k):
            calls["n"] += 1
            # drik.karana calls drik.tithi internally, so sabotage only the
            # muhurat module's own (first) call.
            return (5, 0.0, None) if calls["n"] == 1 else real(*a, **k)

        monkeypatch.setattr(m.drik, "tithi", _bad_end)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchanga"]["tithi"] is not None
        assert out["panchanga"]["tithi_end"] is None
        assert out["degraded"] is True
        assert "panchanga.tithi_end" in out["degraded_limbs"]


# ---------------------------------------------------------------------------
# Hard gate (Rahu/Yama/Gulika) failure flags the day
# ---------------------------------------------------------------------------

class TestHardGateFailClosed:
    """The three absolute vetoes now raise instead of flagging the day.

    ``hard_gate_failed`` made every candidate instant of the day score 0.0 —
    unrecommendable, which was right. Raising states the same thing where it
    cannot be read as a computed result, and it stops a day built on an
    unverifiable veto from travelling any further.
    """

    def test_all_three_failures_raise(self, monkeypatch):
        for fn in ("raahu_kaalam", "yamaganda_kaalam", "gulikai_kaalam"):
            monkeypatch.setattr(m.drik, fn, _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "rahu_kaalam"   # the first of the three

    def test_single_hard_gate_failure_raises(self, monkeypatch):
        """Any ONE of the three failing is enough (the veto is unverifiable)."""
        monkeypatch.setattr(m.drik, "gulikai_kaalam", _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "gulikai_kaalam"

    def test_happy_path_hard_gate_not_failed(self):
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["hard_gate_failed"] is False

    def test_consumer_side_gate_still_fails_closed_on_the_flag(self):
        """The scorer's ``hard_gate_failed`` branch stays live and asserted.

        This producer can no longer set the flag, but the field remains on the
        wire and the gate remains correct for any day payload that carries it —
        removing either would be a breaking change AND the loss of a
        defence-in-depth layer.
        """
        dd = _base_day_data(hard_gate_failed=True)
        score, detail = _score(dd)
        assert detail["hard_excluded"] is True
        assert score == 0.0


# ---------------------------------------------------------------------------
# The 30-muhurta limb: an empty list must never be servable as a clean result
#
# This limb served ``all_muhurtas: []`` behind HTTP 200 on EVERY request while
# reporting ``degraded: False``. The parser indexed the library's entry name as
# a float hour, and a bare ``except Exception`` turned the resulting TypeError
# into a log line. Two properties close it: an environmental failure degrades
# the day VISIBLY, and a shape the contract does not allow SURFACES instead of
# being served as silence.
# ---------------------------------------------------------------------------

class TestMuhurthasFailClosed:
    def test_library_failure_degrades_the_day(self, monkeypatch, caplog):
        monkeypatch.setattr(m.drik, "muhurthas", _raise)
        with caplog.at_level(logging.WARNING, logger="bphs_core.muhurat"):
            out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["all_muhurtas"] == []
        # The empty list alone is indistinguishable from a real result — the
        # degraded flag is what makes it readable as a failure.
        assert out["degraded"] is True
        assert any("muhurat_muhurthas_failed" in r.message for r in caplog.records)

    def test_happy_path_serves_all_thirty_and_is_not_degraded(self):
        """The positive half of the contract: the real library yields 30 named
        windows and does NOT degrade the day."""
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert len(out["all_muhurtas"]) == 30
        assert [w["label"] for w in out["all_muhurtas"]] == m._MUHURTA_NAMES
        assert out["degraded"] is False

    def test_contract_break_propagates_rather_than_serving_empty(self, monkeypatch):
        """A shape the library contract does not allow is a defect, not weather.

        Degrading it to an empty list is exactly what kept this invisible, so it
        raises instead.
        """
        monkeypatch.setattr(
            m.drik, "muhurthas", lambda *_a, **_k: [(6.0, 6.8)] * 30
        )
        with pytest.raises((TypeError, ValueError)):
            m.compute_muhurat_for_day(PLACE, TARGET)


# ---------------------------------------------------------------------------
# Eclipse / Adhika Maasa fail closed to None
# ---------------------------------------------------------------------------

class TestEclipseAdhikNone:
    """These used to resolve to ``None`` for 'could not be computed'.

    Downstream ``None`` VETOES (``is_eclipse_day in (True, None)``), which is
    the right reading of a null — but it meant an unverifiable finder silently
    deleted candidate days from a scan while the response stayed well formed and
    reported nothing. The producer now raises; the consumer-side null gate is
    unchanged and still asserted (TestScoreInstantFailClosed below).
    """

    def test_eclipse_failure_raises(self, monkeypatch):
        monkeypatch.setattr(m.drik, "next_solar_eclipse", _raise)
        monkeypatch.setattr(m.drik, "next_lunar_eclipse", _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "eclipse"

    def test_adhik_maasa_failure_raises(self, monkeypatch):
        monkeypatch.setattr(m.drik, "lunar_month", _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "adhik_maasa"

    def test_clean_day_answers_both_gates(self):
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["is_eclipse_day"] in (True, False)
        assert out["is_adhik_maasa"] in (True, False)


# ---------------------------------------------------------------------------
# compute_balam_at_jd: NoBirthData vs Unknown
# ---------------------------------------------------------------------------

class TestBalamSentinels:
    def test_no_birth_data_returns_nobirthdata(self):
        assert ls.compute_balam_at_jd(2460000.0, None, None) == (
            "NoBirthData", "NoBirthData",
        )

    def test_failed_compute_returns_unknown(self, monkeypatch):
        """Birth data present but the longitude computation raises -> 'Unknown'
        for both limbs (genuine computation failure, fail closed)."""
        monkeypatch.setattr(ls.drik, "sidereal_longitude", _raise)
        tara, chandra = ls.compute_balam_at_jd(2460000.0, "Rohini", "Taurus")
        assert tara == "Unknown"
        assert chandra == "Unknown"


# ---------------------------------------------------------------------------
# _score_instant fail-closed paths
# ---------------------------------------------------------------------------

def _base_day_data(**over):
    dd = {
        "date": "2026-05-26",
        "sunrise": "06:00",
        "inauspicious_periods": [],
        "auspicious_muhurtas": [],
        "chogadiya": [],
        "panchanga": {"tithi": "Shukla Panchami", "yogam": "Siddhi",
                      "karana": "Bava", "vaara": "Tuesday"},
    }
    dd.update(over)
    return dd


def _score(day_data, activity="generic", **kw):
    time_mins = 480  # 08:00
    jd = ls._jd_for_local("2026-05-26", time_mins, 5.5)
    return ls._score_instant(jd, "Aries", "Mars", day_data, time_mins, activity, **kw)


class TestScoreInstantFailClosed:
    def test_day_level_panchanga_names_are_not_scored(self):
        """The tithi, karana and yoga are evaluated AT THE INSTANT, so a day
        payload's names -- missing, Amavasya, Vishti or an avoided yoga -- move
        neither the score nor the detail. (They used to be read for every
        minute of the day; tests/test_muhurat_instant_panchanga.py pins the
        instant values against the ephemeris.)"""
        score_ok, detail_ok = _score(_base_day_data())
        for panchanga in (
            {"tithi": None, "yogam": None, "karana": None, "vaara": "Tuesday"},
            {"tithi": "Krishna Amavasya", "yogam": "Vyatipata",
             "karana": "Vishti", "vaara": "Tuesday"},
        ):
            # Marriage vetoes Vishti; the eclipse and Adhika Maasa flags are
            # answered False so only the karana could veto this instant.
            score, detail = _score(
                _base_day_data(panchanga=panchanga, is_eclipse_day=False,
                               is_adhik_maasa=False),
                "marriage",
            )
            score_g, detail_g = _score(_base_day_data(panchanga=panchanga))
            assert (score_g, detail_g) == (score_ok, detail_ok), panchanga
            assert detail["tithi"] == detail_ok["tithi"]
            assert detail["hard_excluded"] is False

    def test_instant_limb_failure_raises(self, monkeypatch):
        """A Sun or Moon longitude that cannot be computed fails the scorer
        loudly: there is no 'could not be computed' arm left to score around
        it, so a broken ephemeris can never be served as a ranked instant."""
        import swisseph as swe
        real = ls.drik.sidereal_longitude

        def _moon_raises(jd, body, *a, **k):
            if body == swe.MOON:
                raise RuntimeError("ephemeris unavailable")
            return real(jd, body, *a, **k)

        monkeypatch.setattr(ls.drik, "sidereal_longitude", _moon_raises)
        with pytest.raises(RuntimeError, match="ephemeris unavailable"):
            _score(_base_day_data())

    def test_hard_gate_failed_excludes_instant(self):
        dd = _base_day_data(hard_gate_failed=True)
        score, detail = _score(dd)
        assert detail["hard_excluded"] is True
        assert score == 0.0

    def test_amavasya_tithi_not_suitable(self, monkeypatch):
        """An instant in Amavasya is unsuitable and carries exactly the 0.10
        penalty. The instant's limbs are fixed through the scorer's own seam
        (the real InstantPanchanga shape) so the one difference is the tithi."""
        def limbs(tithi):
            return lambda jd: m.InstantPanchanga(tithi, "Bava", "Siddhi")

        monkeypatch.setattr(ls, "panchanga_at_instant", limbs("Shukla Panchami"))
        score_ok, detail_ok = _score(_base_day_data())
        monkeypatch.setattr(ls, "panchanga_at_instant", limbs("Krishna Amavasya"))
        score_ama, detail = _score(_base_day_data())
        assert detail_ok["panchanga_suitable"] is True
        assert detail["panchanga_suitable"] is False
        assert detail["tithi"] == "Krishna Amavasya"
        assert score_ama == pytest.approx(score_ok - 0.10)

    def test_eclipse_none_excludes_samskara(self):
        """For an activity that excludes eclipse (e.g. marriage), an unknown
        (None) eclipse status vetoes; an explicit False does NOT. adhik_maasa is
        held at False so only the eclipse limb is under test (marriage also
        excludes adhik_maasa, whose absence would itself veto)."""
        dd_none = _base_day_data(is_eclipse_day=None, is_adhik_maasa=False)
        _, detail_none = _score(dd_none, activity="marriage")
        assert detail_none["hard_excluded"] is True

        dd_false = _base_day_data(is_eclipse_day=False, is_adhik_maasa=False)
        _, detail_false = _score(dd_false, activity="marriage")
        assert detail_false["hard_excluded"] is False

    def test_adhik_none_excludes_samskara(self):
        dd = _base_day_data(is_eclipse_day=False, is_adhik_maasa=None)
        _, detail = _score(dd, activity="marriage")
        assert detail["hard_excluded"] is True

    def test_unknown_tara_penalised_and_caps_band(self):
        """A failed Tara/Chandra compute (birth data present) penalises the score
        and the resulting sample caps at Fair via derive_band.

        The failure is injected through the balam limb's OWN inputs -- a birth
        nakshatra and a birth sign the tables do not hold -- rather than by
        failing the Moon's ephemeris read. That read now also feeds the
        tithi, karana and yoga at the instant, which propagate a failure (see
        test_instant_limb_failure_raises), as the lagna-lord and malefic limbs
        do (tests/test_graha_body_ids.py). The balam limbs keep their
        catch-into-'Unknown' because 'Unknown' is a *visible* degradation
        (penalty + band cap), not a silent one.
        """
        dd = _base_day_data(is_eclipse_day=False, is_adhik_maasa=False)
        score, detail = _score(
            dd, birth_nakshatra="NotANakshatra", birth_moon_sign="NotASign",
        )
        assert detail["tara_bala"] == "Unknown"
        assert detail["chandra_bala"] == "Unknown"
        # band caps at Fair even though the score might otherwise be higher.
        sample = dict(detail)
        sample["score"] = max(score, 0.9)
        assert ls.derive_band(0.9, {**detail, "score": 0.9}) == "Fair"
