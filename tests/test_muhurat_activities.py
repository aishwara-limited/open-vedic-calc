"""Per-activity rule-table + day-gate coverage for the 14-type muhurat taxonomy.

These exercise the data-driven ``_ACTIVITY_RULES`` table and the eclipse /
Adhika-Maasa / Vishti / Durmuhurtam hard-veto gates directly, so every activity
type is asserted individually. The day-level vetoes return before any lagna
lookup, so those tests need no valid chart; the Vishti veto is a KARANA, which
is evaluated at the instant itself, so its tests use real instants whose karana
is asserted independently from the ephemeris (tests/_panchanga_reference.py).

Known reference dates (LAHIRI ayanamsa, the mode the service runs in):
  - Adhika Shravana 2023: 2023-07-18 .. 2023-08-16 (interior days are adhika).
  - 2026-03-03 total lunar eclipse — visible from India.
  - 2027-08-02 total solar eclipse — visible from India.
  - 2026-08-12 total solar eclipse — NOT visible from India (no grahana dosha).
"""
import datetime as dt
import typing

import swisseph as swe
from jhora.panchanga import drik

from bphs_core import lagna_shuddhi as ls
from bphs_core import muhurat
from tests import _panchanga_reference as ref

_DELHI = drik.Place("Delhi", 28.6, 77.2, 5.5)
# A benign instant well clear of any inauspicious window in the synthetic days.
_JD = swe.julday(2026, 5, 10, 6.0)
_NOON = 6 * 60  # 06:00 in minutes-of-day
# 2026-12-29 18:00 at UTC+5:30, inside a Vishti karana that began about 13:30
# local (asserted from the ephemeris in the tests that use it).
_VISHTI_JD = swe.julday(2026, 12, 29, 18.0 - 5.5)


def _day(**over) -> dict:
    """Synthetic day_data with no inauspicious windows unless overridden."""
    d = {
        "date": "2026-05-10",
        "sunrise": "05:45",
        "inauspicious_periods": [],
        "auspicious_muhurtas": [],
        "chogadiya": [],
        "panchanga": {
            "tithi": "Shukla Panchami", "yogam": "Siddhi",
            "karana": "Bava", "vaara": "Monday",
        },
        "is_eclipse_day": False,
        "is_adhik_maasa": False,
    }
    d.update(over)
    return d


# ---------------------------------------------------------------------------
# Rule-table integrity — every taxonomy value resolves to a rule
# ---------------------------------------------------------------------------

def test_every_activity_literal_has_a_rule():
    values = set(typing.get_args(ls.ActivityCategory))
    assert len(values) == 15  # generic + 14
    for v in values:
        assert ls._rule_for(v) is ls._ACTIVITY_RULES[v]


def test_unknown_activity_falls_back_to_generic():
    assert ls._rule_for("does_not_exist") is ls._GENERIC_RULE


def test_rule_hard_exclude_invariants():
    assert ls._rule_for("marriage").hard_excludes == {"eclipse", "adhik_maasa", "vishti"}
    assert "durm_varj" in ls._rule_for("surgery").hard_excludes
    # Samskaras + permanence activities bar eclipse + Adhika Maasa.
    for a in ("griha_pravesh", "business", "shop_opening", "property",
              "namkaran", "mundan", "annaprashan", "upanayana"):
        assert {"eclipse", "adhik_maasa"} <= ls._rule_for(a).hard_excludes, a
    # Normal activities only bar a (locally-visible) eclipse.
    for a in ("travel", "vehicle", "new_job", "education"):
        assert ls._rule_for(a).hard_excludes == {"eclipse"}, a
    # generic vetoes nothing (parity with prior behaviour).
    assert ls._rule_for("generic").hard_excludes == frozenset()


def test_travel_and_vehicle_weight_chogadiya_higher():
    assert ls._rule_for("travel").chogadiya_bonus == 0.15
    assert ls._rule_for("vehicle").chogadiya_bonus == 0.15
    assert ls._rule_for("generic").chogadiya_bonus == 0.08


# ---------------------------------------------------------------------------
# Event-navamsha factor is table-driven (sign-nature per activity)
# ---------------------------------------------------------------------------

def test_event_navamsha_vargottama_strongest():
    assert ls._event_navamsha_factor("Aries", "Aries", "marriage") == (True, 0.08)


def test_event_navamsha_sign_nature_from_table():
    # marriage prefers fixed signs; Taurus is fixed.
    assert ls._event_navamsha_factor("Taurus", "Aries", "marriage") == (True, 0.05)
    # travel prefers movable; Cancer is movable.
    assert ls._event_navamsha_factor("Cancer", "Aries", "travel") == (True, 0.05)
    # generic has no sign-nature preference → benefic-lagna fallback only.
    suitable, delta = ls._event_navamsha_factor("Taurus", "Aries", "generic")
    assert (suitable, delta) == (True, 0.03)  # Taurus is benefic-ruled


# ---------------------------------------------------------------------------
# Hard-veto gates (return 0.0 before any ephemeris lookup)
# ---------------------------------------------------------------------------

def test_marriage_vetoed_in_adhika_maasa():
    score, detail = ls._score_instant(
        _JD, "Aries", "Mars", _day(is_adhik_maasa=True), _NOON, "marriage")
    assert score == 0.0 and detail["hard_excluded"]


def test_marriage_vetoed_on_visible_eclipse():
    score, detail = ls._score_instant(
        _JD, "Aries", "Mars", _day(is_eclipse_day=True), _NOON, "marriage")
    assert score == 0.0 and detail["hard_excluded"]


def test_marriage_vetoed_on_vishti_karana():
    assert ref.karana_at(_VISHTI_JD) == "Vishti"
    score, detail = ls._score_instant(
        _VISHTI_JD, "Aries", "Mars", _day(), _NOON, "marriage")
    assert score == 0.0 and detail["hard_excluded"]


def test_vishti_veto_reads_the_instant_not_the_day_panchanga():
    """A day panchanga naming Vishti does not veto an instant whose own karana
    is not Vishti -- and a clean day panchanga does not shield one that is."""
    assert ref.karana_at(_JD) not in ("Vishti", None)
    vishti_day = _day(panchanga={"tithi": "x", "yogam": "Siddhi",
                                 "karana": "Vishti", "vaara": "Monday"})
    _, d_day = ls._score_instant(_JD, "Aries", "Mars", vishti_day, _NOON, "marriage")
    assert not d_day["hard_excluded"]
    _, d_inst = ls._score_instant(_VISHTI_JD, "Aries", "Mars", _day(), _NOON, "marriage")
    assert d_inst["hard_excluded"]


def test_travel_vetoes_eclipse_but_not_adhika():
    _, d_ecl = ls._score_instant(
        _JD, "Aries", "Mars", _day(is_eclipse_day=True), _NOON, "travel")
    assert d_ecl["hard_excluded"]
    _, d_adh = ls._score_instant(
        _JD, "Aries", "Mars", _day(is_adhik_maasa=True), _NOON, "travel")
    assert not d_adh["hard_excluded"]  # normal activities ignore Adhika Maasa


def test_generic_never_hard_excluded_by_new_gates():
    for flags in ({"is_eclipse_day": True}, {"is_adhik_maasa": True}):
        _, detail = ls._score_instant(
            _JD, "Aries", "Mars", _day(**flags), _NOON, "generic")
        assert not detail["hard_excluded"], flags
    # ...and an instant inside a real Vishti karana is not vetoed for generic.
    assert ref.karana_at(_VISHTI_JD) == "Vishti"
    _, detail = ls._score_instant(
        _VISHTI_JD, "Aries", "Mars", _day(), _NOON, "generic")
    assert not detail["hard_excluded"]


def test_surgery_vetoes_durmuhurtam_generic_does_not():
    day = _day(inauspicious_periods=[
        {"label": "Durmuhurtam Period 1", "start": "05:55", "end": "06:10"}])
    _, d_surg = ls._score_instant(_JD, "Aries", "Mars", day, _NOON, "surgery")
    assert d_surg["hard_excluded"]
    _, d_gen = ls._score_instant(_JD, "Aries", "Mars", day, _NOON, "generic")
    assert not d_gen["hard_excluded"]  # generic only penalises, never vetoes


# ---------------------------------------------------------------------------
# Day-level gates against known reference dates
# ---------------------------------------------------------------------------

def test_adhik_maasa_gate_known_dates():
    assert muhurat._is_adhik_maasa(
        swe.julday(2023, 8, 1, 12.0), _DELHI, dt.date(2023, 8, 1)
    ) is True
    assert muhurat._is_adhik_maasa(
        swe.julday(2026, 5, 10, 12.0), _DELHI, dt.date(2026, 5, 10)
    ) is False


def test_eclipse_gate_is_location_aware():
    # 2026-03-03 lunar + 2027-08-02 solar are visible from India.
    assert muhurat.compute_muhurat_for_day(_DELHI, dt.date(2026, 3, 3))["is_eclipse_day"] is True
    assert muhurat.compute_muhurat_for_day(_DELHI, dt.date(2027, 8, 2))["is_eclipse_day"] is True
    # 2026-08-12 solar is NOT visible from India → no grahana dosha there.
    assert muhurat.compute_muhurat_for_day(_DELHI, dt.date(2026, 8, 12))["is_eclipse_day"] is False
    # A plain day carries neither gate.
    plain = muhurat.compute_muhurat_for_day(_DELHI, dt.date(2026, 5, 10))
    assert plain["is_eclipse_day"] is False and plain["is_adhik_maasa"] is False
