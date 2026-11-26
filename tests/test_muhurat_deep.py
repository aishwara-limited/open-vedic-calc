"""Deep unit tests for bphs_core.muhurat.

These target the branches of ``compute_muhurat_for_day`` and its helpers that
the endpoint-level tests in ``test_coverage.py`` never reach:

  * the per-limb failure handlers — exercised by monkeypatching the relevant
    ``drik`` function to raise. Since the failure-mode decision of 2026-08-17
    these are no longer uniform: a limb that can change WHICH time is
    recommended raises ``MuhurtaLimbError``, and a supplementary limb degrades
    behind an explicit per-limb flag. The classification itself is pinned by
    tests/test_muhurat_limb_failure_modes.py; the tests here exercise the
    branches around it;
  * the personalised Tara-/Chandra-bala block, including both the "no natal
    Moon supplied" skip and the two failure fallbacks;
  * the ``get_karana_name`` fixed-karana table, the ``get_tithi_name`` Krishna
    branch, and the ``float_hours_to_hhmm`` minute-rounding carry;
  * the 30-muhurta limb, against the REAL ``drik.muhurthas`` — its wire shape,
    the served windows, and the two failure modes (environmental → visibly
    degraded; contract break → raises).

Monkeypatching ``drik`` is used to simulate FAILURE, never to invent a success
shape: a fabricated return validates the parser against a fiction. Where a test
needs real library output it calls the library, and ``TestMuhurthaLibraryShape``
pins that output positionally — both the per-entry shape and the ORDER of the 30
entries — so a dependency bump that moves either fails loudly here. The order is
load-bearing because the served label is assigned by index
(``_MUHURTA_NAMES[i]``) and the library's own name for slot ``i`` is discarded.

All ``drik`` monkeypatching targets ``bphs_core.muhurat.drik`` — the name the
module actually looks up at call time.
"""
import itertools
import re
from datetime import date

import pytest
import swisseph as swe
from jhora import (
    utils as jutils,  # the library formatter the served clock must agree with
)

from bphs_core import muhurat as m
from bphs_core import utils

PLACE = utils.make_place("Sample City", 7.0, 80.0, 5.5)
TARGET = date(2026, 5, 26)

# The LOCAL-noon JD compute_muhurat_for_day builds for its pyjhora event calls
# (muhurat.py step 1). Tests that read the library directly must use the same
# transport, never a tz-pre-subtracted one — see the Julian Day discipline note
# in bphs_core/chart.py.
_JD_LOCAL_NOON = swe.julday(TARGET.year, TARGET.month, TARGET.day, 12.0)

_HHMM = re.compile(r"[0-2]\d:[0-5]\d")


# The POSITIONAL signature of the 30-fold division, index by index:
#
#     (label this repo serves, the library's own key, the library's flag)
#
# Why this table exists. ``drik.muhurthas`` builds its list, in effect, as
# ``[(key, flag[key], slot[i]) for i, key in enumerate(const.muhurthas_of_the_day)]``
# — the time slots are derived from the index, the names come from the dict's
# insertion order. ``bphs_core.muhurat`` then discards ``entry[0]`` and labels
# slot *i* with ``_MUHURTA_NAMES[i]``. So the served label is only correct while
# the library's key order is exactly this one, and NOTHING in the served output
# reveals a drift: comparing the served labels to ``_MUHURTA_NAMES`` is
# tautological, because that is where they were copied from. Measured
# 2026-08-05: transposing the keys at index 1 and 2 of
# ``const.muhurthas_of_the_day`` served window 1 as "Ahi" where the library
# called it ``mithra`` and window 2 as "Mitra" where the library called it
# ``aahi``, with ``degraded: False`` — and the 82 tests then covering this limb
# (this file plus test_panchanga_fail_closed.py) all stayed green.
#
# This is the same defect class as the two planet-id spaces (repo CLAUDE.md,
# Engine conventions): positional identity carried across a library boundary.
#
# The library's own NAMES carry that identity, and the flags cannot carry it
# alone. Names are dict keys, so they are unique and EVERY transposition moves
# the sequence: 29/29 adjacent, 435/435 overall. The flag column takes only two
# values across the 30 positions, so most neighbouring pairs share one — and a
# transposition of two SAME-FLAG neighbours is invisible to it. That is the
# whole failure mode, and it costs the flag column most of its discrimination:
# 11 of the 29 adjacent transpositions (37.9%), 189 of the 435 (43.4%).
# Transposing index 1 and 2 happens to be caught (flags 0 and 1 differ), but
# transposing index 0 and 1 — ``rudra``/``aahi``, both flag 0 — is not, and it
# mislabels two windows just as thoroughly. The flag is kept as a SECOND,
# transliteration-independent signature: it is the one column that moves when a
# key holds its position while its auspiciousness value changes, which the name
# column cannot see.
#
# Every count in the paragraph above is COMPUTED from this table by
# ``TestSignatureColumnDiscrimination`` below and asserted there — cite what
# that test computes, and never re-count the table by hand into prose. A
# hand-counted run length stood in this very sentence, wrong, and was copied
# into CLAUDE.md and the change description before anyone re-derived it; three
# readers passed over it because re-reading a tally is not re-deriving it.
#
# Re-record only on a deliberate, reviewed dependency bump (pyjhora is pinned
# ``==4.8.7``), and re-derive the label correspondence when you do — a blind
# re-record would launder exactly the reorder this pins. Re-checked unchanged on
# the 4.8.6 -> 4.8.7 bump: that release revised the node retrogression and
# speed-info limbs, and left ``jhora.const.muhurthas_of_the_day`` untouched, so
# this table was verified rather than re-recorded.
_MUHURTA_POSITIONAL_SIGNATURE = (
    ("Rudra",       "rudra",           0),
    ("Ahi",         "aahi",            0),
    ("Mitra",       "mithra",          1),
    ("Pitri",       "pithra",          0),
    ("Vasu",        "vasu",            1),
    ("Vara",        "varaaha",         1),
    ("Vishwadeva",  "vishvedeva",      1),
    ("Vidhi",       "vidhi",           1),
    ("Sathamukhi",  "sathamukhi",      1),
    ("Puruhuta",    "puruhootha",      0),
    ("Vahni",       "vaahini",         0),
    ("Naktanchara", "nakthanakaara",   0),
    ("Varuna",      "varuna",          1),
    ("Aryaman",     "aaryaman",        1),
    ("Bhaga",       "bhaga",           0),
    ("Girish",      "girisha",         1),
    ("Ajapad",      "ajapaadha",       0),
    ("Ahirbudhnya", "aahirbhudhnya",   1),
    ("Pusa",        "pushya",          1),
    ("Ashwini",     "ashvini",         1),
    ("Yama",        "yama",            0),
    ("Agni",        "agni",            1),
    ("Vidhatri",    "vidharth",        1),
    ("Chanda",      "kanda",           1),
    ("Aditi",       "adhithi",         1),
    ("Jiva",        "jeeva",           1),
    ("Visnu",       "vishnu",          1),
    ("Dyumani",     "dhyumadadhyuthi", 1),
    ("Brahma",      "brahma",          1),
    ("Samudra",     "samudhra",        1),
)


# Reading the C library from a test is a compute path like any other: it must
# hold the ephemeris lock and carry the per-thread path/ayanamsa state, or it
# can answer from the Moshier fallback while the code under test answers from
# Swiss — and the two disagree by more than the assertions' tolerance.
@utils.serialized_ephemeris
def _library_muhurthas():
    return m.drik.muhurthas(_JD_LOCAL_NOON, PLACE)


@utils.serialized_ephemeris
def _library_sunrise_sunset_hours():
    return (
        m.drik.sunrise(_JD_LOCAL_NOON, PLACE)[0],
        m.drik.sunset(_JD_LOCAL_NOON, PLACE)[0],
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestPureHelpers:
    def test_get_karana_name_fixed(self):
        """Fixed-karana indices map to their special names.

        Covers the ``FIXED_KARANAS`` lookup branch of ``get_karana_name``.
        """
        assert m.get_karana_name(1) == "Kimstughna"
        assert m.get_karana_name(58) == "Shakuni"
        assert m.get_karana_name(59) == "Chatushpada"
        assert m.get_karana_name(60) == "Naga"

    def test_get_karana_name_movable(self):
        """Non-fixed indices cycle through the 7 movable karanas."""
        # idx 2 -> KARANAS[0] == "Bava"
        assert m.get_karana_name(2) == "Bava"
        # idx 8 -> KARANAS[(8-2)%7] == KARANAS[6] == "Vishti"
        assert m.get_karana_name(8) == "Vishti"

    def test_get_tithi_name_shukla_and_krishna(self):
        assert m.get_tithi_name(1) == "Shukla Prathama"
        assert m.get_tithi_name(15) == "Shukla Purnima"
        assert m.get_tithi_name(16) == "Krishna Prathama"
        # idx 30 IS produced at exact new moon (ceil(moon_phase/12) == 30), so it
        # is special-cased to "Krishna Amavasya" (TITHIS[29], the new-moon entry)
        # rather than wrapping to TITHIS[14] ("Purnima"). idx 29 (Chaturdashi) is
        # unchanged.
        assert m.get_tithi_name(30) == "Krishna Amavasya"
        assert m.get_tithi_name(29) == "Krishna Chaturdashi"

    def test_float_hours_to_hhmm_basic(self):
        assert m.float_hours_to_hhmm(6.5) == "06:30"
        assert m.float_hours_to_hhmm(0.0) == "00:00"

    def test_float_hours_to_hhmm_minute_carry(self):
        """A residual second that rounds to 60 carries the minute (and the hour).

        The minute is truncated, but the residual second is rounded to whole
        seconds first (matching pyjhora's ``to_dms``); when that rounds to 60 the
        minute rolls over, and a 60th minute rolls the hour over in turn.
        """
        # 5.9999h -> 5h 59m, residual 59.94s -> rounds to 60 -> carries to 06:00
        assert m.float_hours_to_hhmm(5.9999) == "06:00"
        # 23.9999h carries all the way and wraps the hour back to 00:00
        assert m.float_hours_to_hhmm(23.9999) == "00:00"

    def test_float_hours_to_hhmm_wraps_past_24(self):
        assert m.float_hours_to_hhmm(25.0) == "01:00"


# ---------------------------------------------------------------------------
# Happy path — confirms the success branches and full response shape
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_full_day_structure(self):
        out = m.compute_muhurat_for_day(
            PLACE, TARGET,
            birth_nakshatra="Rohini", birth_moon_sign="Taurus",
        )
        assert out["date"] == "2026-05-26"
        # panchanga limbs present
        for key in ("tithi", "nakshatra", "yogam", "karana", "vaara"):
            assert out["panchanga"][key]
        assert out["panchanga"]["vaara"] == "Tuesday"
        # auspicious / inauspicious lists are populated by the real ephemeris
        assert isinstance(out["auspicious_muhurtas"], list)
        assert isinstance(out["inauspicious_periods"], list)
        assert isinstance(out["chogadiya"], list)
        # personalised balam computed because natal Moon supplied
        assert out["personal_balam"] is not None
        assert "tara_bala" in out["personal_balam"]
        assert "chandra_bala" in out["personal_balam"]
        assert out["personal_balam"]["chandra_bala"] in (
            "Good", "Neutral", "Inauspicious (Avoid)",
        )

    def test_personal_balam_skipped_when_no_natal_moon(self):
        """``personal`` stays None without natal Moon data.

        Covers the false arc of ``compute_muhurat_for_day``'s
        ``if birth_nakshatra and birth_moon_sign:`` guard — both are required.
        """
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["personal_balam"] is None
        # only nakshatra given -> still skipped (both required)
        out2 = m.compute_muhurat_for_day(PLACE, TARGET, birth_nakshatra="Rohini")
        assert out2["personal_balam"] is None
        out3 = m.compute_muhurat_for_day(PLACE, TARGET, birth_moon_sign="Taurus")
        assert out3["personal_balam"] is None


# ---------------------------------------------------------------------------
# Defensive except branches — monkeypatch each drik call to raise
# ---------------------------------------------------------------------------

def _raise(*_a, **_k):
    raise RuntimeError("ephemeris unavailable")


class _BadStringElement:
    """Wraps a real ``drik.sunrise``/``sunset`` result tuple, delegating every
    index access to the real value EXCEPT element [0] (the float local-time
    hours that muhurat now renders as ``float_hours_to_hhmm(...[0])``), which
    raises — simulating the extreme-latitude failure the sunrise/sunset
    ``except`` fallbacks exist for.

    [0] is also what ``drik.muhurthas``/``chogadiya``/``trikalam``/``abhijit``
    read internally, so every limb derived from the failed event degrades too —
    which is the realistic shape of a genuine sunrise/sunset failure (the day
    cannot be divided without it). Each of those drik calls is individually
    guarded in ``compute_muhurat_for_day``, so the response stays well formed and
    the sunrise/sunset ``except`` fallbacks fire; element [2] (the JD, read by
    ``drik.tithi`` only under ``force_tithi_at_sunrise``) is left intact."""

    def __init__(self, real):
        self._real = real

    def __getitem__(self, key):
        if key == 0:
            raise RuntimeError("no event-time hours available")
        return self._real[key]


def _wrap_bad_string(real_fn):
    def wrapped(*a, **k):
        return _BadStringElement(real_fn(*a, **k))
    return wrapped


class TestSunMoonRiseFallbacks:
    def test_sunrise_failure_raises(self, monkeypatch):
        """The day frame has no stand-in.

        muhurat renders sunrise/sunset from the float hours (drik.*()[0]);
        sabotaging exactly that element makes the extraction raise (the JD at
        [2] is preserved — see _BadStringElement). The "06:00" / "18:00"
        defaults this used to assert are gone: they did not degrade the answer,
        they fabricated a day frame that the chogadiya and muhurta divisions are
        cut from and that the scan derives every hora lord from.
        """
        monkeypatch.setattr(m.drik, "sunrise", _wrap_bad_string(m.drik.sunrise))
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "sunrise"

    def test_sunset_failure_raises(self, monkeypatch):
        monkeypatch.setattr(m.drik, "sunset", _wrap_bad_string(m.drik.sunset))
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "sunset"

    def test_moonrise_moonset_fallbacks(self, monkeypatch):
        """The moon events are display-only, so they still degrade — but they
        now name themselves rather than degrading anonymously."""
        monkeypatch.setattr(m.drik, "moonrise", _raise)
        monkeypatch.setattr(m.drik, "moonset", _raise)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["moonrise"] is None
        assert out["moonset"] is None
        assert {"moonrise", "moonset"} <= set(out["degraded_limbs"])


class TestAuspiciousFallbacks:
    """An omitted auspicious window is not a smaller answer, it is a different one.

    The scan builds its entire candidate-minute set from these windows plus the
    favourable chogadiya (lagna_shuddhi._candidate_minutes), so dropping one
    deletes candidate minutes and moves the recommended instant; dropping all
    five used to serve an empty list behind HTTP 200 — a day with no candidates
    at all and nothing on the wire saying why.
    """

    @pytest.mark.parametrize("fn", [
        "abhijit_muhurta", "brahma_muhurtha", "vijaya_muhurtha",
        "godhuli_muhurtha", "nishita_muhurtha",
    ])
    def test_single_auspicious_failure_raises(self, monkeypatch, fn):
        monkeypatch.setattr(m.drik, fn, _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == fn

    def test_all_auspicious_failures_raise(self, monkeypatch):
        for fn in ("abhijit_muhurta", "brahma_muhurtha", "vijaya_muhurtha",
                   "godhuli_muhurtha", "nishita_muhurtha"):
            monkeypatch.setattr(m.drik, fn, _raise)
        with pytest.raises(m.MuhurtaLimbError):
            m.compute_muhurat_for_day(PLACE, TARGET)


class TestChogadiyaFallback:
    def test_chogadiya_failure_raises(self, monkeypatch):
        """The favourable chogadiya windows are the other half of the candidate
        set, so an empty division is not a servable answer."""
        monkeypatch.setattr(m.drik, "gauri_choghadiya", _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "chogadiya"

    def test_chogadiya_unknown_type_label(self, monkeypatch):
        """An out-of-range chogadiya type code maps to the 'Unknown' label."""
        def fake_chogadiya(*_a, **_k):
            return [(99, "08:00:00", "09:30:00")]
        monkeypatch.setattr(m.drik, "gauri_choghadiya", fake_chogadiya)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["chogadiya"] == [
            {"start": "08:00", "end": "09:30", "label": "Unknown"}
        ]


class TestInauspiciousFallbacks:
    @pytest.mark.parametrize("fn,limb", [
        ("raahu_kaalam", "rahu_kaalam"),
        ("yamaganda_kaalam", "yamaganda_kaalam"),
        ("gulikai_kaalam", "gulikai_kaalam"),
        ("durmuhurtam", "durmuhurtam"),
    ])
    def test_single_inauspicious_failure_raises(self, monkeypatch, fn, limb):
        """All five reach the scorer as a WINDOW it matches labels against, so a
        dropped window is a veto that silently does not fire — the three kaalams
        absolutely, Durmuhurtam/Varjyam per activity."""
        monkeypatch.setattr(m.drik, fn, _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == limb

    def test_durmuhurtam_short_list_skips_both_periods(self, monkeypatch):
        """A <2-element durmuhurtam list yields no entries.

        Covers the false arcs of both ``len(dm) >= 2`` and ``len(dm) >= 4`` in
        ``compute_muhurat_for_day``'s durmuhurtam block.
        """
        monkeypatch.setattr(m.drik, "durmuhurtam", lambda *_a, **_k: ["07:00:00"])
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        labels = {p["label"] for p in out["inauspicious_periods"]}
        assert "Durmuhurtam Period 1" not in labels
        assert "Durmuhurtam Period 2" not in labels

    def test_durmuhurtam_one_period_only(self, monkeypatch):
        """len==2 -> only Period 1; len<4 skips Period 2."""
        monkeypatch.setattr(
            m.drik, "durmuhurtam", lambda *_a, **_k: ["07:00:00", "08:00:00"]
        )
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        labels = {p["label"] for p in out["inauspicious_periods"]}
        assert "Durmuhurtam Period 1" in labels
        assert "Durmuhurtam Period 2" not in labels

    def test_durmuhurtam_two_periods(self, monkeypatch):
        monkeypatch.setattr(
            m.drik, "durmuhurtam",
            lambda *_a, **_k: ["07:00:00", "08:00:00", "13:00:00", "14:00:00"],
        )
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        labels = {p["label"] for p in out["inauspicious_periods"]}
        assert "Durmuhurtam Period 1" in labels
        assert "Durmuhurtam Period 2" in labels


    def test_varjyam_failure_raises(self, monkeypatch):
        """The Varjyam windows are cut from the solved nakshatra span; a span
        that cannot be solved is a veto that cannot be verified, so it raises."""
        monkeypatch.setattr(m, "nakshatra_span", _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "varjyam"


class TestAmritaFollowsTheVarjyamSpan:
    def test_amrita_is_cut_from_the_same_star_as_the_varjyam(self):
        """Display-only, and cut from the span the Varjyam veto already
        solved: one window, never a degraded limb of its own."""
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert [w["label"] for w in out["amrita_periods"]] == ["Amrita Gadiya"]
        assert "amrita_periods" not in out["degraded_limbs"]


class TestPanchakaFallback:
    def test_panchaka_failure_raises(self, monkeypatch):
        """A failed panchaka computation fails closed by RAISING.

        It used to serve ``panchaka_free: None`` and rely on the consumer to
        read that null as a veto — but a veto flag that asks its reader to guess
        is the same silent-drop shape as an omitted window, and nothing in this
        service could tell whether the reader guessed right. Never a
        falsely-clean default of True, then or now.
        """
        monkeypatch.setattr(m.drik, "panchaka_rahitha", _raise)
        with pytest.raises(m.MuhurtaLimbError) as exc:
            m.compute_muhurat_for_day(PLACE, TARGET)
        assert exc.value.limb == "panchaka"

    def test_panchaka_dosha_spanning_noon_marks_not_free(self, monkeypatch):
        """A non-zero dosha window spanning local noon clears panchaka_free."""
        monkeypatch.setattr(
            m.drik, "panchaka_rahitha",
            lambda *_a, **_k: [(3, 10.0, 14.0)],  # dosha 3, brackets 12:00
        )
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchaka_free"] is False

    def test_panchaka_zero_dosha_keeps_free(self, monkeypatch):
        monkeypatch.setattr(
            m.drik, "panchaka_rahitha",
            lambda *_a, **_k: [(0, 10.0, 14.0)],  # dosha 0 -> still free
        )
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchaka_free"] is True


class TestPersonalBalamFallbacks:
    def test_tara_bala_fallback_on_bad_nakshatra(self):
        """An unknown birth nakshatra makes NAKSHATRAS.index raise -> 'Unknown'
        ('could not be computed'), aligning with compute_balam_at_jd. NOT
        'Neutral' (which would falsely read as a computed, benign result)."""
        out = m.compute_muhurat_for_day(
            PLACE, TARGET,
            birth_nakshatra="NotANakshatra", birth_moon_sign="Taurus",
        )
        assert out["personal_balam"]["tara_bala"] == "Unknown"
        assert "personal_balam.tara_bala" in out["degraded_limbs"]

    def test_chandra_bala_fallback_on_bad_sign(self):
        """An unknown birth Moon sign makes SIGNS.index raise -> 'Unknown'."""
        out = m.compute_muhurat_for_day(
            PLACE, TARGET,
            birth_nakshatra="Rohini", birth_moon_sign="NotASign",
        )
        assert out["personal_balam"]["chandra_bala"] == "Unknown"
        assert "personal_balam.chandra_bala" in out["degraded_limbs"]

    # The transit Moon on 2026-05-26 (noon, Lahiri) sits in Virgo (sign idx 5).
    # Picking the birth Moon sign therefore selects each chandra-bala category
    # deterministically against the *real* ephemeris — no patching needed, so
    # the unguarded drik.tithi/nakshatra/yogam/karana calls keep working:
    #   Aries  -> diff 6  -> Good
    #   Taurus -> diff 5  -> Neutral
    #   Gemini -> diff 4  -> Inauspicious (Avoid)
    @pytest.mark.parametrize("birth_sign,expected", [
        ("Aries",  "Good"),
        ("Taurus", "Neutral"),
        ("Gemini", "Inauspicious (Avoid)"),
    ])
    def test_chandra_bala_categories(self, birth_sign, expected):
        out = m.compute_muhurat_for_day(
            PLACE, TARGET,
            birth_nakshatra="Rohini", birth_moon_sign=birth_sign,
        )
        assert out["personal_balam"]["chandra_bala"] == expected


class TestMuhurthaLibraryShape:
    """Pin the REAL ``drik.muhurthas`` output — per-entry shape AND entry order.

    These assertions run against the library itself — no monkeypatch — because
    the served field is only as correct as this output. The predecessor of this
    class fabricated ``(6.0, 6.8)`` 2-tuples that the library has never
    returned, so the parser was validated against a fiction and the real shape
    was never exercised at all.

    "Shape" alone is not the contract. ``bphs_core.muhurat`` labels slot *i*
    with ``_MUHURTA_NAMES[i]`` and discards the library's own name, so the
    entry ORDER is load-bearing and a reorder mislabels windows silently — it
    breaks no shape check, raises nothing, and leaves ``degraded`` False. The
    order is therefore pinned explicitly, against
    ``_MUHURTA_POSITIONAL_SIGNATURE``; per-entry shape checks and this sequence
    pin are separate tests so a failure says which one moved.
    """

    def test_entry_shape_is_name_flag_bounds(self):
        entries = _library_muhurthas()
        assert len(entries) == 30
        for entry in entries:
            assert isinstance(entry, tuple), entry
            assert len(entry) == 3, entry
            name, flag, bounds = entry
            assert isinstance(name, str) and name, entry
            assert flag in (0, 1), entry
            assert isinstance(bounds, tuple) and len(bounds) == 2, entry
            assert all(isinstance(b, float) for b in bounds), entry

    def test_thirty_windows_partition_a_whole_day_from_sunrise(self):
        """15 day + 15 night muhurtas tile sunrise..next sunrise contiguously."""
        bounds = [e[2] for e in _library_muhurthas()]
        sunrise_h, sunset_h = _library_sunrise_sunset_hours()
        # Entry 0 opens at sunrise; entry 15 opens at sunset.
        assert bounds[0][0] == pytest.approx(sunrise_h, abs=1e-9)
        assert bounds[15][0] == pytest.approx(sunset_h, abs=1e-9)
        # Contiguous: each window ends exactly where the next begins.
        for i in range(29):
            assert bounds[i][1] == pytest.approx(bounds[i + 1][0], abs=1e-9)
        # The 30 windows span one whole day.
        assert bounds[-1][1] - bounds[0][0] == pytest.approx(24.0, abs=0.01)

    def test_entry_sequence_is_pinned_position_by_position(self):
        """The library's own ``(name, flag)`` sequence, pinned index by index.

        This is what makes positional labelling sound. A reorder upstream
        changes nothing a shape check can see: every entry still matches the
        contracted 3-tuple, the count is still 30, the windows still tile the
        day contiguously — only the names have moved across fixed time slots.
        """
        entries = _library_muhurthas()
        assert [(e[0], e[1]) for e in entries] == [
            (library_name, flag)
            for _label, library_name, flag in _MUHURTA_POSITIONAL_SIGNATURE
        ]


# A transposition of positions i and j moves a signature column if and only if
# that column's values at i and j differ. So "how much does this column
# discriminate" is exactly a count over index pairs — a computation, not a
# tally to be read off the table by eye.
_LIBRARY_NAMES = tuple(row[1] for row in _MUHURTA_POSITIONAL_SIGNATURE)
_LIBRARY_FLAGS = tuple(row[2] for row in _MUHURTA_POSITIONAL_SIGNATURE)
_ALL_PAIRS = tuple(itertools.combinations(range(len(_MUHURTA_POSITIONAL_SIGNATURE)), 2))
_ADJACENT_PAIRS = tuple(
    (i, i + 1) for i in range(len(_MUHURTA_POSITIONAL_SIGNATURE) - 1)
)


def _transpositions_detected_by(column, pairs):
    """Those of ``pairs`` whose transposition would change ``column``."""
    return tuple((i, j) for i, j in pairs if column[i] != column[j])


class TestSignatureColumnDiscrimination:
    """Why the NAMES carry positional identity and the FLAGS cannot alone.

    Which column to pin is a measurable property of
    ``_MUHURTA_POSITIONAL_SIGNATURE``, so it is measured here. Every
    discrimination figure quoted in prose — this module's header comment and the
    Determinism section of this repo's CLAUDE.md — is one of the numbers
    asserted below, and prose should cite what this computes rather than count
    the table again. It exists because a hand-counted statistic in exactly that
    sentence was wrong, survived two review rounds, and had been copied into
    three places by the time it was caught.
    """

    def test_the_pair_universe_is_what_the_percentages_divide_by(self):
        assert len(_MUHURTA_POSITIONAL_SIGNATURE) == 30
        assert len(_ADJACENT_PAIRS) == 29
        assert len(_ALL_PAIRS) == 435

    def test_names_are_unique_so_every_transposition_moves_them(self):
        assert len(set(_LIBRARY_NAMES)) == len(_LIBRARY_NAMES)
        assert len(_transpositions_detected_by(_LIBRARY_NAMES, _ADJACENT_PAIRS)) == 29
        assert len(_transpositions_detected_by(_LIBRARY_NAMES, _ALL_PAIRS)) == 435

    def test_flags_take_two_values_so_most_neighbours_share_one(self):
        """The failure mode is same-flag neighbours; it is the majority case."""
        assert set(_LIBRARY_FLAGS) == {0, 1}
        detected = _transpositions_detected_by(_LIBRARY_FLAGS, _ADJACENT_PAIRS)
        blind = len(_ADJACENT_PAIRS) - len(detected)
        # "most neighbouring pairs share a flag" — the property the prose states.
        assert blind > len(_ADJACENT_PAIRS) / 2
        assert blind == 18
        assert len(detected) == 11  # 37.9% of 29
        assert len(_transpositions_detected_by(_LIBRARY_FLAGS, _ALL_PAIRS)) == 189  # 43.4%

    def test_the_worked_examples_in_the_prose_are_the_measured_ones(self):
        """``rudra``/``aahi`` is invisible to the flags; ``aahi``/``mithra`` is not.

        One sampled pair is why a flags-only pin looks sufficient: the pair that
        first came up happens to straddle a flag change. Its left-hand neighbour
        does not, and mislabels two windows just as thoroughly.
        """
        flag_blind = set(_ADJACENT_PAIRS) - set(
            _transpositions_detected_by(_LIBRARY_FLAGS, _ADJACENT_PAIRS)
        )
        assert _LIBRARY_NAMES[0:2] == ("rudra", "aahi")
        assert _LIBRARY_FLAGS[0] == _LIBRARY_FLAGS[1]
        assert (0, 1) in flag_blind
        assert (0, 1) in _transpositions_detected_by(_LIBRARY_NAMES, _ADJACENT_PAIRS)

        assert _LIBRARY_NAMES[1:3] == ("aahi", "mithra")
        assert _LIBRARY_FLAGS[1] != _LIBRARY_FLAGS[2]
        assert (1, 2) not in flag_blind


class TestSingleClockConvention:
    """Register #176 — a period boundary must render as the event it is derived
    from, on ONE clock.

    The 30-muhurta night division opens at sunset: ``drik.muhurthas`` builds it
    as ``sunset_hours + j*night_muhurtha``, so entry 15 opens at exactly
    ``sunset_hours`` — the identical float the served ``sunset`` field renders.
    They must read the same HH:MM.

    Root cause: ``float_hours_to_hhmm`` ROUNDED to the nearest minute, while
    every time pyjhora renders itself (sunrise/sunset/moonrise/moonset,
    chogadiya, rahu-kala, yamagandam, gulika, abhijit, durmuhurtam — all via
    ``utils.to_dms`` sliced ``[:5]``) TRUNCATES to the minute the instant falls
    in. So an instant at 18:17:58 served as ``sunset`` "18:17" but opened its
    night muhurta at "18:18". The fix renders the helper on the library's own
    truncate-the-minute convention, so a float-hour boundary and a drik-string
    event can never disagree.
    """

    # -- the convention itself, independent of the ephemeris --------------------

    @pytest.mark.parametrize("x", [
        0.0, 6.5, 12.0, 18.0, 23.5,
        # half-minute-second boundaries, where truncate and round DIVERGE:
        18 + (17 * 60 + 29) / 3600,   # 18:17:29
        18 + (17 * 60 + 30) / 3600,   # 18:17:30  round -> 18:18, truncate -> 18:17
        18 + (17 * 60 + 31) / 3600,   # 18:17:31
        18 + (17 * 60 + 45) / 3600,   # 18:17:45
        18 + (17 * 60 + 59) / 3600,   # 18:17:59
        5 + (59 * 60 + 45) / 3600,    # 05:59:45  (minute-carry region)
        23 + (59 * 60 + 59) / 3600,   # 23:59:59  (hour + day wrap)
        25 + (30 * 60 + 40) / 3600,   # 25:30:40  (>24h night muhurta -> 01:30)
    ])
    def test_formatter_is_the_library_string_convention(self, x):
        """``float_hours_to_hhmm`` renders exactly as pyjhora's own ``to_dms``
        string sliced to HH:MM — the convention the served sunrise/sunset/
        chogadiya/rahu-kala strings already use. Locking this equivalence is what
        guarantees a float-hour boundary and a drik-string event never diverge,
        including for the ``[:5]`` sites this helper does not itself format.
        """
        assert m.float_hours_to_hhmm(x) == jutils.to_dms(x % 24)[:5]

    def test_half_minute_second_stays_in_its_own_minute(self):
        """The divergent case, pinned as literals: an instant at :30-:59 seconds
        renders in the minute it FALLS IN, not the next one (round would carry)."""
        base = 18 + 17 / 60          # 18:17:00
        assert m.float_hours_to_hhmm(base + 29 / 3600) == "18:17"
        assert m.float_hours_to_hhmm(base + 30 / 3600) == "18:17"
        assert m.float_hours_to_hhmm(base + 45 / 3600) == "18:17"
        assert m.float_hours_to_hhmm(base + 59 / 3600) == "18:17"

    # -- the served invariant, against the real library -------------------------

    def test_served_sunset_field_equals_the_night_muhurta_it_opens(self):
        """Register #176 exactly: the served ``sunset`` and the night muhurta it
        opens are one instant, so one HH:MM. Also the day muhurta it closes."""
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["all_muhurtas"][15]["start"] == out["sunset"]
        assert out["all_muhurtas"][15]["label"] == "Girish"
        assert out["all_muhurtas"][14]["end"] == out["sunset"]

    def test_served_sunrise_field_equals_the_first_muhurta_it_opens(self):
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["all_muhurtas"][0]["start"] == out["sunrise"]
        assert out["all_muhurtas"][0]["label"] == "Rudra"

    def test_served_sunset_value_stays_the_library_native_rendering(self):
        """The fix moves the WINDOW to match the EVENT, never the reverse: the
        served sunset is still pyjhora's own truncate-the-minute rendering, so no
        downstream consumer of the sunrise/sunset strings shifts."""
        jd = swe.julday(TARGET.year, TARGET.month, TARGET.day, 12.0)
        ss_f = m.drik.sunset(jd, PLACE)[0]
        sr_f = m.drik.sunrise(jd, PLACE)[0]
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["sunset"] == jutils.to_dms(ss_f)[:5]
        assert out["sunrise"] == jutils.to_dms(sr_f)[:5]

    @pytest.mark.parametrize("day", [24, 25, 26])
    def test_boundary_matches_event_across_a_spread_of_dates(self, day):
        """A spread whose sunsets fall at :33 / :45 / :58 seconds — the band
        where the OLD rounding rendered the night window a minute PAST the sunset
        it opens at (18:17:58 -> sunset '18:17' vs window '18:18'). Divergent
        under both ephemeris runtimes; the invariant holds regardless."""
        target = date(2026, 5, day)
        out = m.compute_muhurat_for_day(PLACE, target)
        assert out["all_muhurtas"][15]["start"] == out["sunset"]
        assert out["all_muhurtas"][14]["end"] == out["sunset"]
        assert out["all_muhurtas"][0]["start"] == out["sunrise"]


class TestAllMuhurtas:
    """The SERVED ``all_muhurtas`` field, driven by the real library."""

    def test_all_thirty_muhurtas_are_served(self):
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        served = out["all_muhurtas"]
        # Not merely non-empty: exactly the 30 named muhurtas, in order.
        assert len(served) == 30
        assert [w["label"] for w in served] == m._MUHURTA_NAMES
        assert out["degraded"] is False

    def test_each_served_label_names_the_library_slot_it_is_attached_to(self):
        """The end-to-end statement the tautological assertions cannot make.

        ``[w["label"] for w in served] == m._MUHURTA_NAMES`` is true by
        construction — the labels are copied from that list — so it holds just
        as well when every window is serving under a neighbour's name. What
        must actually hold is that served label *i* is this repo's
        transliteration of the muhurta the LIBRARY put in slot *i*; that pairing
        is fixed by ``_MUHURTA_POSITIONAL_SIGNATURE`` and asserted here against
        the unpatched library.
        """
        served = m.compute_muhurat_for_day(PLACE, TARGET)["all_muhurtas"]
        entries = _library_muhurthas()
        assert len(served) == len(entries) == len(_MUHURTA_POSITIONAL_SIGNATURE)
        assert [(w["label"], e[0]) for w, e in zip(served, entries)] == [
            (label, library_name)
            for label, library_name, _flag in _MUHURTA_POSITIONAL_SIGNATURE
        ]

    def test_served_windows_carry_wall_clock_boundaries(self):
        """Every boundary is HH:MM, and the windows chain end -> next start."""
        served = m.compute_muhurat_for_day(PLACE, TARGET)["all_muhurtas"]
        for w in served:
            assert _HHMM.fullmatch(w["start"]), w
            assert _HHMM.fullmatch(w["end"]), w
        for i in range(29):
            assert served[i]["end"] == served[i + 1]["start"]

    def test_first_muhurta_opens_at_sunrise_and_sixteenth_at_sunset(self):
        """The served boundaries are the library's own sunrise/sunset division.

        Anchors the served strings to independently computed values rather than
        to constants, so the assertion holds under both ephemeris runtimes.
        """
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        served = out["all_muhurtas"]
        sunrise_h, sunset_h = _library_sunrise_sunset_hours()
        assert served[0]["start"] == m.float_hours_to_hhmm(sunrise_h)
        assert served[0]["label"] == "Rudra"
        assert served[15]["start"] == m.float_hours_to_hhmm(sunset_h)
        assert served[15]["label"] == "Girish"

    def test_post_midnight_night_muhurtas_wrap_to_wall_clock(self):
        """Night boundaries legitimately exceed 24h; they render as wall clock.

        The final muhurta closes at the next sunrise, so its rendered end must
        equal the rendering of that > 24h float — not a truncated 23:59.
        """
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        last_end_h = _library_muhurthas()[-1][2][1]
        assert last_end_h > 24.0, "fixture assumes the day wraps past midnight"
        assert out["all_muhurtas"][-1]["end"] == m.float_hours_to_hhmm(last_end_h)

    def test_library_failure_serves_empty_but_degrades_visibly(self, monkeypatch):
        """An unavailable ephemeris is an ENVIRONMENTAL failure: the limb is
        dropped, but the day is flagged so an empty list is never mistaken for
        'this day genuinely has no muhurtas'."""
        monkeypatch.setattr(m.drik, "muhurthas", _raise)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["all_muhurtas"] == []
        assert out["degraded"] is True

    @pytest.mark.parametrize("bad,why", [
        ([(6.0, 6.8)] * 30, "2-tuples of floats (the shape the old fixture invented)"),
        ([("rudra", 0, 6.0)] * 30, "bounds not a pair"),
        ([("rudra", 0, (6.0,))] * 30, "bounds pair of the wrong length"),
        ([("rudra", 0, ("6.0", "6.8"))] * 30, "bounds not floats"),
        ([7.5] * 30, "scalars, not tuples"),
    ])
    def test_wrong_entry_shape_raises_rather_than_serving_silence(
        self, monkeypatch, bad, why
    ):
        """A library-contract break must SURFACE.

        Serving 200 + an empty field is indistinguishable from a real result and
        is exactly how this stayed invisible; a raised error is visible and
        recoverable.
        """
        monkeypatch.setattr(m.drik, "muhurthas", lambda *_a, **_k: bad)
        with pytest.raises((TypeError, ValueError)):
            m.compute_muhurat_for_day(PLACE, TARGET)

    @pytest.mark.parametrize("count", [0, 29, 31])
    def test_wrong_entry_count_raises(self, monkeypatch, count):
        """The 30-fold division is contractual — a different count would silently
        mislabel windows against ``_MUHURTA_NAMES``."""
        entry = ("rudra", 0, (6.0, 6.8))
        monkeypatch.setattr(m.drik, "muhurthas", lambda *_a, **_k: [entry] * count)
        with pytest.raises(ValueError):
            m.compute_muhurat_for_day(PLACE, TARGET)


# ---------------------------------------------------------------------------
# FIX #5 — degraded flag surfaces when sunrise or sunset fails
# ---------------------------------------------------------------------------

class TestDegradedFlag:
    def test_happy_path_not_degraded(self):
        """Normal ephemeris -> degraded is False."""
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["degraded"] is False

    def test_happy_path_names_no_degraded_limbs(self):
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["degraded_limbs"] == []

    def test_sunrise_failure_raises_and_logs(self, monkeypatch, caplog):
        """The day frame raises, and still emits its observability event."""
        import logging
        monkeypatch.setattr(m.drik, "sunrise", _wrap_bad_string(m.drik.sunrise))
        with caplog.at_level(logging.WARNING, logger="bphs_core.muhurat"):
            with pytest.raises(m.MuhurtaLimbError):
                m.compute_muhurat_for_day(PLACE, TARGET)
        assert any("muhurat_sunrise_failed" in r.message for r in caplog.records)

    def test_sunset_failure_raises_and_logs(self, monkeypatch, caplog):
        import logging
        monkeypatch.setattr(m.drik, "sunset", _wrap_bad_string(m.drik.sunset))
        with caplog.at_level(logging.WARNING, logger="bphs_core.muhurat"):
            with pytest.raises(m.MuhurtaLimbError):
                m.compute_muhurat_for_day(PLACE, TARGET)
        assert any("muhurat_sunset_failed" in r.message for r in caplog.records)

    def test_moonrise_failure_sets_degraded_and_names_the_limb(self, monkeypatch):
        """moonrise failing degrades. It used to leave ``degraded`` False, so a
        lost display field was served as a clean day."""
        monkeypatch.setattr(m.drik, "moonrise", _raise)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["degraded"] is True
        assert out["degraded_limbs"] == ["moonrise"]
        assert out["moonrise"] is None


# ---------------------------------------------------------------------------
# Root-cause: nakshatra/yoga NAME comes from the sidereal longitudes directly,
# so a corrupt pyjhora index never wraps a wrong name — a valid name is always
# produced. Their end times are solved separately; an unsolvable end only
# invalidates the end-time → day is degraded.
# ---------------------------------------------------------------------------

class TestNakshatraYogaIndexGuard:
    def test_nakshatra_end_failure_still_names_via_longitude(self, monkeypatch):
        """An end time that cannot be solved does NOT touch the name (computed
        from the Moon's longitude); only the end-time is lost and the day
        degrades."""
        real = m._limb_end_hours

        def fail_nakshatra(angle_at, *a, **k):
            if angle_at is m._moon_longitude:
                raise ValueError("unsolvable")
            return real(angle_at, *a, **k)

        monkeypatch.setattr(m, "_limb_end_hours", fail_nakshatra)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchanga"]["nakshatra"] in utils.NAKSHATRAS
        assert out["panchanga"]["nakshatra_end"] is None
        assert out["degraded"] is True

    def test_nakshatra_valid_index_returns_name(self):
        """Normal path: valid index returns the correct nakshatra name."""
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchanga"]["nakshatra"] in utils.NAKSHATRAS

    def test_yoga_end_failure_still_names_via_longitude(self, monkeypatch):
        """An unsolvable yoga end does NOT touch the name (computed from the
        Sun+Moon longitude sum); only the end-time is lost -> degraded."""
        real = m._limb_end_hours

        def fail_yoga(angle_at, *a, **k):
            if angle_at is m._sun_moon_sum:
                raise ValueError("unsolvable")
            return real(angle_at, *a, **k)

        monkeypatch.setattr(m, "_limb_end_hours", fail_yoga)
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchanga"]["yogam"] in m.YOGAS
        assert out["panchanga"]["yogam_end"] is None
        assert out["degraded"] is True

    def test_yoga_valid_index_returns_name(self):
        """Normal path: valid index returns the correct yoga name."""
        out = m.compute_muhurat_for_day(PLACE, TARGET)
        assert out["panchanga"]["yogam"] in m.YOGAS


# ---------------------------------------------------------------------------
# FIX #9 — hard_excluded flag in _score_instant detail
# ---------------------------------------------------------------------------

class TestHardExcluded:
    def test_hard_excluded_true_in_rahu_kala(self):
        """detail['hard_excluded'] is True when instant falls in Rahu Kala."""
        from bphs_core import lagna_shuddhi as ls

        # Build a minimal day_data where the entire day is Rahu Kala
        day_data = {
            "date": "2026-05-26",
            "sunrise": "06:00",
            "inauspicious_periods": [
                {"label": "Rahu Kala", "start": "00:00", "end": "23:59"},
            ],
            "auspicious_muhurtas": [],
            "chogadiya": [],
        }
        # Any minute of the day is inside Rahu Kala
        time_mins = 480  # 08:00
        jd = ls._jd_for_local("2026-05-26", time_mins, 5.5)
        _, detail = ls._score_instant(jd, "Aries", "Mars", day_data, time_mins, "generic")
        assert detail["hard_excluded"] is True
        assert detail["in_rahu_kala"] is True

    def test_hard_excluded_false_outside_inauspicious(self):
        """detail['hard_excluded'] is False for a clean instant."""
        from bphs_core import lagna_shuddhi as ls

        day_data = {
            "date": "2026-05-26",
            "sunrise": "06:00",
            "inauspicious_periods": [],
            "auspicious_muhurtas": [],
            "chogadiya": [],
        }
        time_mins = 480  # 08:00
        jd = ls._jd_for_local("2026-05-26", time_mins, 5.5)
        _, detail = ls._score_instant(jd, "Aries", "Mars", day_data, time_mins, "generic")
        assert detail["hard_excluded"] is False
