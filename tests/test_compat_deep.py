"""Deep unit tests for bphs_core.compat.

The endpoint-level ``/v1/compat`` tests only ever drive two fixed charts, so the
per-kuta scoring functions exercise just one branch each. These tests call every
kuta calculator (``_varna``, ``_vasya``, ``_tara``, ``_yoni``, ``_graha_maitri``,
``_gana``, ``_bhakoot``, ``_nadi``) directly with crafted sign/nakshatra inputs
to cover all score tiers and interpretation strings, plus the Mangal-dosha
cancellation rules, the nakshatra-compatibility prose branches, and every
``composite_strength_notes`` rank combination.

Mangal-dosha and composite-strength tests build a minimal ``ChartSnapshot`` the
same way ``tests/test_calc_regressions.py`` does.

Branch anchors below are named by function in bphs_core/compat.py:

The ``# <symbol>: ...`` comments marking individual score tiers and prose
branches are CITATIONS into that module, not free prose.  The declaration line
above is what makes them machine-readable: it is the same header a class
docstring uses to declare its subject, lifted to module scope so that a comment
-- which has no enclosing scope to inherit an owner from -- has one.  Every such
comment in this file is resolved against ``bphs_core/compat.py`` on every CI run
by ``ci/tests/test_stable_anchor_citations.py``, so a rename over there reddens
here instead of quietly leaving a comment pointing at nothing.

The consequence, stated so it is not discovered as a surprise: inside a declared
file a ``# Word: ...`` comment opener IS an anchor.  Prose that is not a citation
must not be written in that shape, and an anchor into any OTHER module is spelled
in full as ``<path>.py::<symbol>``.
"""
import datetime

import pytest

from bphs_core import compat
from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData

# ---------------------------------------------------------------------------
# Minimal chart builder (mirrors tests/test_calc_regressions.py)
# ---------------------------------------------------------------------------

def _mock_chart(planets: dict[str, dict], lagna: str = "Aries",
                lagna_lord: str = "Mars",
                birth_date=datetime.date(2000, 1, 1),
                birth_time=datetime.time(12, 0)) -> ChartSnapshot:
    rasi = {
        p: PlanetData(
            planet=p,
            sign=d.get("sign", "Aries"),
            degrees=d.get("degrees", 0.0),
            nakshatra=d.get("nakshatra", "Ashwini"),
            dignity=d.get("dignity", "neutral"),
            house=d.get("house", 1),
            conjunctions=d.get("conjunctions", []),
            aspects=d.get("aspects", []),
            is_retrograde=d.get("is_retrograde", False),
        )
        for p, d in planets.items()
    }
    return ChartSnapshot(
        person=PersonalData(
            name="Synthetic", birth_date=birth_date,
            birth_time=birth_time, birth_place="X",
            latitude=0.0, longitude=0.0, timezone_offset_hours=0.0,
        ),
        rasi_chart=rasi, hora_chart={}, drekkana_chart={}, navamsa_chart={},
        decamsa_chart={}, dwadasamsa_chart={}, chaturvimsa_chart={},
        trimshamsa_chart={}, saptamsa_chart={}, shashtyamsa_chart={},
        lagna=lagna, lagna_lord=lagna_lord, ayanamsa_value=0.0,
        house_cusps=[(i * 30.0) for i in range(12)],
    )


# ---------------------------------------------------------------------------
# Varna kuta (max 1.0)
# ---------------------------------------------------------------------------

class TestVarna:
    """Varna kuta is now DIRECTIONAL: sign_a=groom, sign_b=bride.
    Score = 1.0 iff groom_varna >= bride_varna, else 0.0.
    (Old non-directional min/max ratio scoring is replaced by fix 6.)
    """
    def test_same_varna(self):
        # Cancer & Scorpio are both Brahmin (level 4): groom >= bride -> 1.0
        score, interp = compat._varna("Cancer", "Scorpio")
        assert score == 1.0
        assert "share the Brahmin varna" in interp

    def test_groom_higher_varna(self):
        # Cancer (groom=Brahmin=4) vs Aries (bride=Kshatriya=3): groom > bride -> 1.0
        # Old (non-directional): round(3/4, 4) = 0.75 — now 1.0
        score, interp = compat._varna("Cancer", "Aries")
        assert score == 1.0, (
            "Groom Brahmin (4) >= Bride Kshatriya (3): directional score must be 1.0"
        )
        assert "groom's varna is higher" in interp.lower() or "auspicious" in interp.lower()

    def test_groom_lower_varna(self):
        # Aries (groom=Kshatriya=3) vs Cancer (bride=Brahmin=4): groom < bride -> 0.0
        score, interp = compat._varna("Aries", "Cancer")
        assert score == 0.0, (
            "Groom Kshatriya (3) < Bride Brahmin (4): directional score must be 0.0"
        )
        assert "bride's varna is higher" in interp.lower() or "inauspicious" in interp.lower()

    def test_groom_highest_varna(self):
        # Cancer (groom=Brahmin=4) vs Gemini (bride=Shudra=1): groom >> bride -> 1.0
        # Old (non-directional): round(1/4, 4) = 0.25 — now 1.0
        score, interp = compat._varna("Cancer", "Gemini")
        assert score == 1.0, (
            "Groom Brahmin (4) >= Bride Shudra (1): directional score must be 1.0"
        )

    def test_lowest_groom_varna(self):
        # Gemini (groom=Shudra=1) vs Cancer (bride=Brahmin=4): groom << bride -> 0.0
        score, interp = compat._varna("Gemini", "Cancer")
        assert score == 0.0


# ---------------------------------------------------------------------------
# Vasya kuta (max 2.0)
# ---------------------------------------------------------------------------

class TestVasya:
    def test_same_group(self):
        # Aries & Taurus both chatushpada -> _vasya: `ga == gb` same-group tier (2.0)
        score, interp = compat._vasya("Aries", "Taurus")
        assert score == 2.0
        assert "same vasya group" in interp

    def test_a_controlled_by_b(self):
        # _VASYA_CONTROLS["Leo"] == {"Aries"} -> sign_a=Aries controlled by b=Leo
        score, interp = compat._vasya("Aries", "Leo")  # _vasya: `sign_a in controlled_by_b` tier (1.0)
        assert score == 1.0
        assert "supportive power dynamic" in interp

    def test_b_controlled_by_a(self):
        # _VASYA_CONTROLS["Leo"] == {"Aries"} -> sign_b=Aries controlled by a=Leo
        score, interp = compat._vasya("Leo", "Aries")  # _vasya: `sign_b in controlled_by_a` tier (0.5)
        assert score == 0.5
        assert "Partial vasya relationship" in interp

    def test_no_affinity(self):
        # Gemini (nara) & Cancer (jalchar), no control either way
        score, interp = compat._vasya("Gemini", "Cancer")
        assert score == 0.0
        assert "no natural affinity" in interp


# ---------------------------------------------------------------------------
# Tara kuta (max 3.0)
# ---------------------------------------------------------------------------

class TestTara:
    # The classical rule (Muhurta Chintamani, Vivaha-prakarana): count
    # inclusively each way, divide by nine, and only the remainders 3, 5 and 7
    # are inauspicious.  The exhaustive 27 x 27 check against that rule lives in
    # tests/test_ashtakoota_classical_tables.py; these pin the two tiers and
    # their interpretation strings.
    _BAD = {3, 5, 7}

    def _find(self, want_ab: bool, want_ba: bool):
        from bphs_core import utils
        for i, na in enumerate(utils.NAKSHATRAS):
            for j, nb in enumerate(utils.NAKSHATRAS):
                cab = (j - i) % 27 + 1
                cba = (i - j) % 27 + 1
                if ((cab % 9) not in self._BAD) == want_ab and \
                        ((cba % 9) not in self._BAD) == want_ba:
                    return na, nb
        raise AssertionError("no such nakshatra pair")

    def test_both_favorable(self):
        score, interp = compat._tara(*self._find(True, True))  # _tara: `fav_ab and fav_ba` tier (3.0)
        assert score == 3.0
        assert "strong karmic resonance" in interp

    def test_same_star_is_janma_and_favorable(self):
        # Remainder 1 both ways (Janma) is not one of 3, 5, 7 -> full 3.0.
        score, interp = compat._tara("Ashwini", "Ashwini")
        assert score == 3.0
        assert "strong karmic resonance" in interp

    def test_one_favorable(self):
        score, interp = compat._tara(*self._find(True, False))  # _tara: one-favourable return (1.5)
        assert score == 1.5
        assert "mixed star compatibility" in interp


# ---------------------------------------------------------------------------
# Yoni kuta (max 4.0)
# ---------------------------------------------------------------------------

class TestYoni:
    def test_same_animal(self):
        # Ashwini & Shatabhisha are both 'horse' -> _yoni: `animal_a == animal_b` tier (4.0)
        score, interp = compat._yoni("Ashwini", "Shatabhisha")
        assert score == 4.0
        assert "horse yoni" in interp

    def test_enemy_animals(self):
        # Ashwini=horse, Swati=buffalo -> _yoni: `pair in _YONI_ENEMIES` tier (0.0)
        score, interp = compat._yoni("Ashwini", "Swati")
        assert score == 0.0
        assert "natural enemies" in interp

    def test_neutral_animals(self):
        # Ashwini=horse, Bharani=elephant -> neutral
        score, interp = compat._yoni("Ashwini", "Bharani")
        assert score == 2.0
        assert "neutral toward each other" in interp

    def test_missing_yoni_data(self):
        # Unknown nakshatra -> NAKSHATRA_YONI.get returns None
        # -> _yoni: `not ya or not yb` missing-data guard (2.0)
        score, interp = compat._yoni("Ashwini", "Bogus")
        assert score == 2.0
        assert "moderate" in interp


# ---------------------------------------------------------------------------
# Graha Maitri kuta (max 5.0)
# ---------------------------------------------------------------------------

class TestGrahaMaitri:
    def test_same_lord(self):
        # Aries & Scorpio both ruled by Mars -> identical lord -> 5.0
        score, interp = compat._graha_maitri("Aries", "Scorpio")
        assert score == 5.0
        assert "mutual natural friends" in interp

    def test_mutual_friends(self):
        # Leo(Sun) & Cancer(Moon): Sun-Moon mutual friends -> 5.0
        score, interp = compat._graha_maitri("Leo", "Cancer")
        assert score == 5.0
        assert "mutual natural friends" in interp

    def test_friendly_neutral(self):
        # Find a pair whose maitri score is exactly 4.0 (friend/neutral).
        pair = _find_maitri_pair(4.0)
        score, interp = compat._graha_maitri(*pair)  # _graha_maitri: `score >= 4.0` friendly-neutral tier
        assert score == 4.0
        assert "friendly-neutral bond" in interp

    def test_neutral(self):
        pair = _find_maitri_pair(3.0)
        score, interp = compat._graha_maitri(*pair)  # _graha_maitri: `score >= 3.0` neutral tier
        assert score == 3.0
        assert "neutral to each other" in interp

    def test_mixed_tense(self):
        pair = _find_maitri_pair(1.0)
        score, interp = compat._graha_maitri(*pair)  # _graha_maitri: `score >= 1.0` mixed/mildly-tense tier
        assert score == 1.0
        assert "mixed or mildly tense" in interp

    def test_enemies(self):
        pair = _find_maitri_pair(0.0)
        score, interp = compat._graha_maitri(*pair)  # _graha_maitri: else natural-enemies tier
        assert score == 0.0
        assert "natural enemies" in interp


def _find_maitri_pair(target: float):
    """Find a (sign_a, sign_b) whose graha-maitri score == target."""
    from bphs_core import utils
    for sa in utils.SIGNS:
        for sb in utils.SIGNS:
            la = utils.SIGN_LORDS[sa]
            lb = utils.SIGN_LORDS[sb]
            if la == lb:
                continue
            if compat._maitri_score(la, lb) == target:
                return sa, sb
    raise AssertionError(f"no sign pair yields maitri score {target}")


# ---------------------------------------------------------------------------
# Gana kuta (max 6.0)
# ---------------------------------------------------------------------------

class TestGana:
    def test_same_gana(self):
        # Ashwini & Mrigashira both deva -> _gana: `ga == gb` same-gana tier (6.0)
        score, interp = compat._gana("Ashwini", "Mrigashira")
        assert score == 6.0
        assert "deva gana" in interp

    def test_deva_manushya(self):
        # Ashwini(deva) & Bharani(manushya) -> 5.0
        score, interp = compat._gana("Ashwini", "Bharani")
        assert score == 5.0
        assert "generally compatible" in interp

    def test_manushya_rakshasa(self):
        # Bharani(manushya) & Krittika(rakshasa) -> 0.0
        score, interp = compat._gana("Bharani", "Krittika")
        assert score == 0.0
        assert "deep mutual respect" in interp

    def test_deva_rakshasa(self):
        # Ashwini(deva) & Krittika(rakshasa) -> _gana: deva+rakshasa fall-through return (0.0)
        score, interp = compat._gana("Ashwini", "Krittika")
        assert score == 0.0
        assert "fundamentally mismatched" in interp


# ---------------------------------------------------------------------------
# Bhakoot kuta (max 7.0)
# ---------------------------------------------------------------------------

class TestBhakoot:
    def test_dosha_present(self):
        # 2-12 dosha: Aries(0) & Pisces(11): count_ab=12, count_ba=2
        score, interp = compat._bhakoot("Aries", "Pisces")
        assert score == 0.0
        assert "bhakoot dosha" in interp

    def test_no_dosha(self):
        # Aries & Aries: count 1-1, not in dosha_pairs -> _bhakoot: no-dosha return (7.0)
        score, interp = compat._bhakoot("Aries", "Aries")
        assert score == 7.0
        assert "free of bhakoot dosha" in interp


# ---------------------------------------------------------------------------
# Nadi kuta (max 8.0)
# ---------------------------------------------------------------------------

class TestNadi:
    def test_same_nadi_dosha(self):
        # Ashwini and Ardra are both Aadi (serpentine order: Aadi, Madhya,
        # Antya, Antya, Madhya, Aadi) -> same nadi -> dosha.
        score, interp = compat._nadi("Ashwini", "Ardra")
        assert score == 0.0
        assert "nadi dosha" in interp

    def test_different_nadi(self):
        # Ashwini(Aadi) & Bharani(Madhya): different nadi -> _nadi: fall-through
        # past the `na == nb` dosha branch (8.0)
        score, interp = compat._nadi("Ashwini", "Bharani")
        assert score == 8.0
        assert "fully compatible" in interp


# ---------------------------------------------------------------------------
# Mangal dosha
# ---------------------------------------------------------------------------

class TestMangalDosha:
    def test_no_mars_no_dosha(self):
        # Chart with no Mars -> _mangal_dosha_raw: `mars is None` guard -> (False, none, [])
        has, sev, reasons = compat._mangal_dosha_raw(_mock_chart({"Sun": {}}))
        assert has is False
        assert sev == "none"
        assert reasons == []

    def test_mars_benign_house_no_dosha(self):
        # Mars in 3rd house -> not a dosha house
        snap = _mock_chart({"Mars": {"sign": "Gemini", "house": 3}})
        has, sev, reasons = compat._mangal_dosha_raw(snap)
        assert has is False
        assert sev == "none"

    def test_mars_strong_dosha_8th(self):
        snap = _mock_chart({"Mars": {"sign": "Gemini", "house": 8}})
        has, sev, _ = compat._mangal_dosha_raw(snap)
        assert has is True
        assert sev == "strong"

    def test_dosha_without_lagna_or_moon_cancellation(self):
        """False arc of _mangal_dosha_raw's Mars-ruled lagna-or-Moon cancellation
        check: a dosha chart whose lagna and Moon are neither Aries nor Scorpio
        skips that cancellation and falls through to the 2nd-house check."""
        snap = _mock_chart(
            {
                "Mars": {"sign": "Gemini", "house": 7},   # mild dosha, no own-sign
                "Moon": {"sign": "Taurus", "house": 1},   # not Aries/Scorpio
            },
            lagna="Taurus", lagna_lord="Venus",           # not Aries/Scorpio
        )
        has, sev, reasons = compat._mangal_dosha_raw(snap)
        assert has is True
        assert sev == "mild"
        # none of the cancellation rules apply -> no reasons recorded
        assert reasons == []

    def test_mars_mild_dosha_with_own_sign_cancellation(self):
        snap = _mock_chart({"Mars": {"sign": "Aries", "house": 7}})
        has, sev, reasons = compat._mangal_dosha_raw(snap)
        assert has is True
        assert sev == "mild"
        assert any("own sign or exalted" in r for r in reasons)

    def test_jupiter_aspect_cancellation(self):
        snap = _mock_chart({
            "Mars": {"sign": "Gemini", "house": 7,
                     "aspects": ["Jupiter"]},
        })
        _, _, reasons = compat._mangal_dosha_raw(snap)
        assert any("Jupiter" in r for r in reasons)

    def test_lagna_or_moon_cancellation(self):
        snap = _mock_chart(
            {"Mars": {"sign": "Gemini", "house": 4}},
            lagna="Aries",
        )
        _, _, reasons = compat._mangal_dosha_raw(snap)
        assert any("lagna or Moon sign" in r for r in reasons)

    def test_second_house_gemini_cancellation(self):
        # Mars in 2nd house in Gemini -> _mangal_dosha_raw: `mars.house == 2`
        # Gemini/Virgo cancellation branch
        snap = _mock_chart({"Mars": {"sign": "Gemini", "house": 2}})
        _, _, reasons = compat._mangal_dosha_raw(snap)
        assert any("2nd house" in r for r in reasons)

    def test_mutual_cancellation(self):
        snap_a = _mock_chart({"Mars": {"sign": "Gemini", "house": 8}})
        snap_b = _mock_chart({"Mars": {"sign": "Cancer", "house": 12}})
        info_a, info_b = compat.compute_mangal_dosha(snap_a, snap_b)
        assert info_a.has_dosha and info_b.has_dosha
        assert "mutually cancels" in info_a.cancellation
        assert "mutually cancels" in info_b.cancellation

    def test_one_sided_dosha_no_mutual(self):
        snap_a = _mock_chart({"Mars": {"sign": "Gemini", "house": 7}})
        snap_b = _mock_chart({"Mars": {"sign": "Gemini", "house": 3}})  # no dosha
        info_a, info_b = compat.compute_mangal_dosha(snap_a, snap_b)
        assert info_a.has_dosha is True
        assert info_b.has_dosha is False
        assert info_b.severity == "none"


# ---------------------------------------------------------------------------
# Nakshatra compatibility prose
# ---------------------------------------------------------------------------

class TestNakshatraProse:
    def test_same_gana_friend_lords_high_tara(self):
        # nakshatra_compatibility_prose: `ga == gb` gana sentence, mutual-friend
        # rashi-lord sentence, `tara_sc >= 2.5` sentence.
        # Leo(Sun) & Cancer(Moon): Sun & Moon mutual friends.
        prose = compat.nakshatra_compatibility_prose(
            "Ashwini", "Mrigashira", "Leo", "Cancer", 3.0
        )
        assert "deva gana" in prose
        assert "mutual friends" in prose
        assert "karmic ease" in prose

    def test_deva_manushya_enemy_lords_partial_tara(self):
        # nakshatra_compatibility_prose: deva+manushya gana sentence, enemy
        # rashi-lord sentence, `tara_sc > 0` (sub-2.5) sentence.
        # Venus & Sun are enemies (Sun's enemies include Venus).
        prose = compat.nakshatra_compatibility_prose(
            "Ashwini", "Bharani", "Taurus", "Leo", 1.5
        )
        assert "deva and manushya" in prose
        assert "tension" in prose
        assert "partially favorable" in prose

    def test_mismatched_gana_neutral_lords_zero_tara(self):
        # nakshatra_compatibility_prose: gana else-branch sentence (deva+rakshasa),
        # neutral rashi-lord sentence, tara else-branch sentence (tara_sc not > 0).
        # Saturn & Jupiter are neutral to each other.
        prose = compat.nakshatra_compatibility_prose(
            "Ashwini", "Krittika", "Capricorn", "Sagittarius", 0.0
        )
        assert "calls for patience" in prose
        assert "neutral bond" in prose
        assert "friction" in prose


# ---------------------------------------------------------------------------
# Dasha overlaps + quality
# ---------------------------------------------------------------------------

class TestDashaOverlaps:
    def test_dasha_quality_categories(self):
        assert compat._dasha_quality("Mars", "Mars") == "favorable"
        # Sun & Moon mutual friends -> favorable
        assert compat._dasha_quality("Sun", "Moon") == "favorable"
        # Saturn & Sun: Saturn sees Sun as enemy -> challenging
        assert compat._dasha_quality("Saturn", "Sun") == "challenging"
        # find a neutral pair
        assert compat._dasha_quality("Jupiter", "Saturn") == "neutral"

    def test_compute_dasha_overlaps_shape(self):
        snap_a = _mock_chart(
            {"Moon": {"sign": "Taurus", "degrees": 10.0, "nakshatra": "Rohini"}},
            birth_date=datetime.date(1990, 1, 1),
        )
        snap_b = _mock_chart(
            {"Moon": {"sign": "Cancer", "degrees": 5.0, "nakshatra": "Pushya"}},
            birth_date=datetime.date(1992, 1, 1),
        )
        overlaps = compat.compute_dasha_overlaps(
            snap_a, snap_b, datetime.date(2026, 1, 1)
        )
        assert len(overlaps) > 0
        # sorted by start date
        starts = [o.start_date for o in overlaps]
        assert starts == sorted(starts)
        for o in overlaps:
            assert o.quality in ("favorable", "neutral", "challenging")


# ---------------------------------------------------------------------------
# Composite strength notes (patch compute_all_bhavabala for deterministic ranks)
# ---------------------------------------------------------------------------

class TestCompositeStrength:
    def _patch_ranks(self, monkeypatch, rank_a, rank_b):
        """Patch strength.compute_all_bhavabala to return controlled house-7 ranks.

        compute_all_bhavabala is imported lazily inside composite_strength_notes
        (``from .strength import compute_all_bhavabala``), so it must be patched
        on the source module. It is called once for snap_a then snap_b.
        """
        from bphs_core import strength

        def make_results(rank):
            if rank is None:
                # omit house 7 entirely -> incomplete-data path
                return [strength.BhavabalaResult(h, 1.0, 1.0, 0.0, "average")
                        for h in range(1, 13) if h != 7]
            return [strength.BhavabalaResult(
                        h, 1.0, 1.0, 0.0, rank if h == 7 else "average")
                    for h in range(1, 13)]

        seq = [make_results(rank_a), make_results(rank_b)]
        calls = {"i": 0}

        def fake(_snap):
            r = seq[calls["i"]]
            calls["i"] += 1
            return r

        monkeypatch.setattr(strength, "compute_all_bhavabala", fake)

    def _snaps(self):
        a = _mock_chart({"Moon": {"sign": "Aries"}})
        b = _mock_chart({"Moon": {"sign": "Aries"}})
        return a, b

    def test_both_strong(self, monkeypatch):
        self._patch_ranks(monkeypatch, "strong", "strong")
        a, b = self._snaps()
        note = compat.composite_strength_notes(a, b)
        assert "Both charts have strong 7th-house" in note

    def test_a_strong_only(self, monkeypatch):
        self._patch_ranks(monkeypatch, "strong", "average")
        a, b = self._snaps()
        note = compat.composite_strength_notes(a, b)
        # composite_strength_notes: `ra == "strong"` branch
        assert "Person A's 7th-house bhavabala is strong" in note

    def test_b_strong_only(self, monkeypatch):
        self._patch_ranks(monkeypatch, "average", "strong")
        a, b = self._snaps()
        note = compat.composite_strength_notes(a, b)
        # composite_strength_notes: `rb == "strong"` branch
        assert "Person B's 7th-house bhavabala is strong" in note

    def test_both_same_non_strong(self, monkeypatch):
        self._patch_ranks(monkeypatch, "weak", "weak")
        a, b = self._snaps()
        note = compat.composite_strength_notes(a, b)
        # composite_strength_notes: `ra == rb` non-strong branch
        assert "Both charts show weak 7th-house" in note

    def test_differ_neither_strong(self, monkeypatch):
        self._patch_ranks(monkeypatch, "weak", "average")
        a, b = self._snaps()
        note = compat.composite_strength_notes(a, b)
        # composite_strength_notes: differing-ranks fall-through return
        assert "complementary partnership strengths" in note

    def test_incomplete_data(self, monkeypatch):
        self._patch_ranks(monkeypatch, None, "strong")
        a, b = self._snaps()
        note = compat.composite_strength_notes(a, b)
        # composite_strength_notes: false arc of `if h7a and h7b` -> incomplete-data return
        assert "incomplete" in note


# ---------------------------------------------------------------------------
# Full compute_compat integration (sanity)
# ---------------------------------------------------------------------------

class TestComputeCompat:
    def test_total_within_bounds_and_kuta_count(self):
        a = _mock_chart(
            {"Moon": {"sign": "Taurus", "nakshatra": "Rohini", "degrees": 5.0}},
            birth_date=datetime.date(1990, 1, 1),
        )
        b = _mock_chart(
            {"Moon": {"sign": "Cancer", "nakshatra": "Pushya", "degrees": 5.0}},
            birth_date=datetime.date(1991, 1, 1),
        )
        res = compat.compute_compat(a, b, datetime.date(2026, 1, 1))
        assert res.max_score == 36.0
        assert 0.0 <= res.total_score <= 36.0
        assert len(res.kutas) == 8
        names = [k.name for k in res.kutas]
        assert names == [
            "varna", "vasya", "tara", "yoni",
            "graha_maitri", "gana", "bhakoot", "nadi",
        ]

    def test_missing_moon_raises(self):
        # A missing Moon means a corrupt snapshot. Rather than silently defaulting
        # to Aries/Ashwini and returning a plausible-but-wrong score, compute_compat
        # must fail loudly.
        a = _mock_chart({"Sun": {"sign": "Leo"}})
        b = _mock_chart({"Sun": {"sign": "Leo"}})
        with pytest.raises(ValueError, match="Moon absent"):
            compat.compute_compat(a, b, datetime.date(2026, 1, 1))
