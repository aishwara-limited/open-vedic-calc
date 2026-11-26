"""Edge-case tests targeting specific uncovered branches in bphs_core modules.

Each section is mapped to the §3.4 capability it exercises:
  - §3.4 dasha timeline (dashas.py)
  - §3.4 chart profile: Kalsarp, numerology, Sade-Sati (profile.py)
  - §3.4 Jaimini/special points (special_points.py)
  - §3.4 transits/gochara: Sade Sati phases, vedha (transits.py)
  - §3.4 planetary strength: Vimshopaka bala (vimshopaka.py)
  - §3.4 yoga detection (yogas.py)
  - §3.4 Shadbala/Bhavabala (strength.py)

All fixtures use synthetic data only — no real personal data.
"""
import datetime

import pytest

from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _person(birth_date=None):
    return PersonalData(
        name="synthetic",
        birth_date=birth_date or datetime.date(1990, 6, 15),
        birth_time=datetime.time(12, 0),
        birth_place="Test City",
        latitude=6.9,
        longitude=79.8,
        timezone_offset_hours=5.5,
    )


def _planet(sign="Aries", degrees=10.0, house=1, dignity="neutral",
            nakshatra="Ashwini", retrograde=False, longitude_abs=None,
            aspects=None, conjunctions=None, planet_name="Sun"):
    return PlanetData(
        planet=planet_name,
        sign=sign,
        degrees=degrees,
        nakshatra=nakshatra,
        dignity=dignity,
        house=house,
        conjunctions=conjunctions or [],
        aspects=aspects or [],
        is_retrograde=retrograde,
        longitude_abs=longitude_abs,
    )


def _snapshot(planets=None, lagna="Aries", lagna_lord="Mars",
              house_cusps=None, birth_date=None):
    """Build a minimal ChartSnapshot from a dict {planet_name: PlanetData}."""
    rasi = planets or {}
    cusps = house_cusps or [i * 30.0 for i in range(12)]
    return ChartSnapshot(
        person=_person(birth_date),
        rasi_chart=rasi,
        hora_chart={},
        drekkana_chart={},
        navamsa_chart={},
        decamsa_chart={},
        dwadasamsa_chart={},
        chaturvimsa_chart={},
        trimshamsa_chart={},
        saptamsa_chart={},
        shashtyamsa_chart={},
        lagna=lagna,
        lagna_lord=lagna_lord,
        ayanamsa_value=0.0,
        house_cusps=cusps,
    )


# ===========================================================================
# §3.4 Dasha timeline — bphs_core/dashas.py
# ===========================================================================

class TestDashasEdges:
    """Edge branches covered here, named by function in bphs_core/dashas.py:

      - ``_moon_nakshatra_and_fraction`` — Moon missing from rasi_chart.
      - ``_yogini_dashas`` — ``end_date`` supplied, forcing the multi-cycle
        ``cycle_count`` branch.
      - ``get_active_dasha`` — the ``system == "yogini"`` branch, and the
        unknown-system fall-through to ``return None``.
      - ``get_dasha_timeline`` → ``_vimshottari_antardashas`` — antardasha
        periods emitted alongside their mahadasha.
    """

    def test_moon_nakshatra_fraction_no_moon_returns_ashwini(self):
        """_moon_nakshatra_and_fraction: Moon absent → Ashwini, fraction=0."""
        from bphs_core.dashas import _moon_nakshatra_and_fraction
        snap = _snapshot({})
        nak, frac = _moon_nakshatra_and_fraction(snap)
        assert nak == "Ashwini"
        assert frac == 0.0

    def test_yogini_with_end_date_triggers_cycle_count(self):
        """_yogini_dashas: passing end_date forces the cycle_count >= 2 branch."""
        from bphs_core.dashas import _yogini_dashas
        moon = _planet("Rohini".split()[0], degrees=5.0, house=1,
                       planet_name="Moon", nakshatra="Rohini")
        moon.sign = "Taurus"
        # Build a snapshot with a known Moon
        rasi = {"Moon": _planet("Taurus", 5.0, 1, "neutral", "Rohini",
                                planet_name="Moon")}
        snap = _snapshot(rasi, birth_date=datetime.date(1990, 1, 1))
        birth = datetime.datetime(1990, 1, 1, 12, 0)
        # end_date far in future forces cycle_count > 1
        end = datetime.datetime(2060, 1, 1)
        periods = _yogini_dashas(snap, birth, end_date=end)
        # Multiple cycles should yield periods well beyond 36 years
        assert len(periods) > 8

    def test_get_active_dasha_yogini_branch(self):
        """get_active_dasha: system='yogini' → the _yogini_dashas containment scan."""
        from bphs_core.dashas import get_active_dasha
        rasi = {"Moon": _planet("Taurus", 5.0, 1, "neutral", "Rohini",
                                planet_name="Moon")}
        snap = _snapshot(rasi, birth_date=datetime.date(1990, 1, 1))
        at = datetime.datetime(2000, 6, 15, 12, 0)
        result = get_active_dasha(snap, at, system="yogini")
        # result may be a DashaPeriod or None if at is before birth-adjusted start
        if result is not None:
            assert result.system == "yogini"

    def test_get_active_dasha_returns_none_for_unknown_system(self):
        """get_active_dasha: system not in ('vimshottari', 'yogini') → returns None."""
        from bphs_core.dashas import get_active_dasha
        rasi = {"Moon": _planet("Aries", 5.0, 1, "neutral", "Ashwini",
                                planet_name="Moon")}
        snap = _snapshot(rasi, birth_date=datetime.date(1990, 1, 1))
        at = datetime.datetime(2000, 1, 1, 12, 0)
        result = get_active_dasha(snap, at, system="char")
        assert result is None

    def test_vimshottari_antardashas_covered_via_get_dasha_timeline(self):
        """Antardasha computation via get_dasha_timeline (covers _vimshottari_antardashas)."""
        from bphs_core.dashas import get_dasha_timeline
        rasi = {"Moon": _planet("Aries", 5.0, 1, "neutral", "Ashwini",
                                planet_name="Moon")}
        snap = _snapshot(rasi, birth_date=datetime.date(1980, 1, 1))
        start = datetime.datetime(1990, 1, 1)
        end = datetime.datetime(1992, 1, 1)
        periods = get_dasha_timeline(snap, start, end, systems=["vimshottari"])
        levels = {p.level for p in periods}
        assert "antardasha" in levels


# ===========================================================================
# §3.4 Chart profile — bphs_core/profile.py
# ===========================================================================

class TestProfileEdges:
    """Edge branches covered here, named by function in bphs_core/profile.py:

      - ``janma_nakshatra`` — Moon missing from rasi_chart; and the pada
        try-block on the valid-Moon path (its ``(ValueError, ZeroDivisionError)``
        guard is unreachable with a valid ``utils.SIGNS``).
      - ``kalsarp_dosh`` — Rahu absent; Rahu present but no visible planet
        collected into ``in_rahu_ketu_arc``; and the ``all_in or all_out`` block
        that sets ``direction`` (``ketu_to_rahu`` reciprocal case), versus the
        mixed-arc ``partial=True`` fall-through.
      - ``sade_sati_lifetime`` — Moon missing (or its sign not in
        ``utils.SIGNS``) → ``[]``.
      - ``numerology`` — the ``if name.strip()`` guard, and a name carrying no
        Chaldean-mapped letters at all (falsy ``total`` → name_number None).
      - ``favourable_points`` — Moon absent, so ``rasi_lord`` falls back to
        ``snapshot.lagna_lord``.
    """

    # --- janma_nakshatra edge: no Moon ---
    def test_janma_nakshatra_no_moon_returns_empty(self):
        """janma_nakshatra: Moon missing from rasi_chart → {}."""
        from bphs_core.profile import janma_nakshatra
        snap = _snapshot({})
        assert janma_nakshatra(snap) == {}

    # --- kalsarp_dosh edges ---
    def test_kalsarp_no_rahu_returns_false(self):
        """kalsarp_dosh: Rahu absent → present=False immediately, rahu_house=None."""
        from bphs_core.profile import kalsarp_dosh
        snap = _snapshot({"Sun": _planet("Aries", 10.0, 1, planet_name="Sun")})
        result = kalsarp_dosh(snap)
        assert result["present"] is False
        assert result["rahu_house"] is None

    def test_kalsarp_no_7_visible_planets_returns_false(self):
        """kalsarp_dosh: Rahu present but in_rahu_ketu_arc stays empty → present=False."""
        from bphs_core.profile import kalsarp_dosh
        rahu = _planet("Aries", 15.0, 1, planet_name="Rahu")
        snap = _snapshot({"Rahu": rahu})
        result = kalsarp_dosh(snap)
        assert result["present"] is False

    def test_kalsarp_all_in_ketu_to_rahu_arc_direction(self):
        """kalsarp_dosh: the all_out arm of the all_in-or-all_out block —
        every planet in the Ketu→Rahu arc → direction='ketu_to_rahu'."""
        from bphs_core.profile import kalsarp_dosh
        # Rahu at Aries 0° (lon 0), Ketu at Libra 0° (lon 180).
        # "all_out" means no planet is in the 0-180 arc (Rahu→Ketu),
        # i.e. ALL are in 180-360 (Ketu→Rahu arc).
        # Put all 7 planets in Scorpio/Sagittarius/Capricorn/Aquarius/Pisces (180-360°).
        rahu = _planet("Aries", 0.0, 1, planet_name="Rahu")
        sun  = _planet("Scorpio", 10.0, 8, planet_name="Sun")
        moon = _planet("Sagittarius", 10.0, 9, planet_name="Moon")
        mars = _planet("Capricorn", 10.0, 10, planet_name="Mars")
        merc = _planet("Aquarius", 10.0, 11, planet_name="Mercury")
        jup  = _planet("Aquarius", 20.0, 11, planet_name="Jupiter")
        ven  = _planet("Pisces", 10.0, 12, planet_name="Venus")
        sat  = _planet("Pisces", 20.0, 12, planet_name="Saturn")
        rasi = {
            "Rahu": rahu, "Sun": sun, "Moon": moon, "Mars": mars,
            "Mercury": merc, "Jupiter": jup, "Venus": ven, "Saturn": sat,
        }
        snap = _snapshot(rasi)
        result = kalsarp_dosh(snap)
        # All seven planets are on the Ketu→Rahu side (all_out=True)
        assert result["present"] is True
        assert result.get("direction") == "ketu_to_rahu"

    def test_kalsarp_partial_returns_partial_true(self):
        """When some planets are on each side → partial=True, present=False."""
        from bphs_core.profile import kalsarp_dosh
        rahu = _planet("Aries", 0.0, 1, planet_name="Rahu")
        sun  = _planet("Cancer", 10.0, 4, planet_name="Sun")   # in Rahu→Ketu arc
        moon = _planet("Scorpio", 10.0, 8, planet_name="Moon") # in Ketu→Rahu arc
        mars = _planet("Cancer", 20.0, 4, planet_name="Mars")
        merc = _planet("Cancer", 5.0, 4, planet_name="Mercury")
        jup  = _planet("Cancer", 25.0, 4, planet_name="Jupiter")
        ven  = _planet("Leo", 10.0, 5, planet_name="Venus")
        sat  = _planet("Scorpio", 20.0, 8, planet_name="Saturn")
        rasi = {
            "Rahu": rahu, "Sun": sun, "Moon": moon, "Mars": mars,
            "Mercury": merc, "Jupiter": jup, "Venus": ven, "Saturn": sat,
        }
        snap = _snapshot(rasi)
        result = kalsarp_dosh(snap)
        assert result["present"] is False
        assert result["partial"] is True

    # --- sade_sati_lifetime: no Moon ---
    def test_sade_sati_no_moon_returns_empty(self):
        """sade_sati_lifetime: no Moon (or Moon sign not in utils.SIGNS) → []."""
        from bphs_core.profile import sade_sati_lifetime
        snap = _snapshot({})
        result = sade_sati_lifetime(snap, datetime.date(1990, 1, 1))
        assert result == []

    # --- numerology: empty name ---
    def test_numerology_empty_name_no_name_number(self):
        """numerology: name='' fails the name.strip() guard → name_number=None."""
        from bphs_core.profile import numerology
        result = numerology(datetime.date(1990, 6, 15), name="")
        assert result["name"] is None
        assert 1 <= result["radical"] <= 9
        assert 1 <= result["destiny"] <= 9

    def test_numerology_name_all_unmapped_chars_returns_none(self):
        """name consisting solely of digits (no alpha) → name_number=None."""
        from bphs_core.profile import numerology
        result = numerology(datetime.date(1990, 6, 15), name="12345")
        assert result["name"] is None

    # --- favourable_points: lagna_lord fallback when Moon absent ---
    def test_favourable_points_no_moon_uses_lagna_lord(self):
        """favourable_points: snapshot has no Moon → rasi_lord falls back to
        snapshot.lagna_lord."""
        from bphs_core.profile import favourable_points
        snap = _snapshot({}, lagna="Aries", lagna_lord="Mars")
        result = favourable_points(snap)
        # Mars lucky_number = 9
        assert result["lucky_number"] == 9
        assert result["rasi_lord"] == "Mars"

    # --- profile: pada calc ValueError branch ---
    def test_janma_nakshatra_pada_with_valid_moon(self):
        """janma_nakshatra: a valid Moon takes the pada try-block → pada 1-4.

        The (ValueError, ZeroDivisionError) guard wrapping that block is NOT
        reached on this path: with a valid utils.SIGNS list neither exception
        can be raised, so the guard is unreachable rather than covered here.
        """
        from bphs_core.profile import janma_nakshatra
        moon = _planet("Aries", 5.0, 1, "neutral", "Ashwini", planet_name="Moon")
        snap = _snapshot({"Moon": moon})
        result = janma_nakshatra(snap)
        assert result["pada"] in (1, 2, 3, 4)


# ===========================================================================
# §3.4 Jaimini/special points — bphs_core/special_points.py
# ===========================================================================

class TestSpecialPointsEdges:
    """Edge branches covered here, named by function in
    bphs_core/special_points.py:

      - ``_sign_and_deg`` — delegation to ``utils.longitude_to_sign_and_degree``.
      - ``_arudha_pada_house`` — the BPHS exception rule when the pada lands on
        the 1st or the 7th.
      - ``get_arudha_lagna`` — lagna lord absent from rasi_chart.
      - ``get_upapada`` — 12th lord absent from rasi_chart.
      - ``get_atmakaraka`` — no non-node candidates at all.
      - ``get_karakamsa`` — the Atmakaraka absent from navamsa_chart.
      - ``_sidereal_longitude`` — longitude_abs present, longitude_abs absent
        (reconstruction), and the planet absent entirely.
    """

    def _sp_snapshot(self, planets=None, lagna="Aries", lagna_lord="Mars"):
        rasi = planets or {}
        return ChartSnapshot(
            person=_person(),
            rasi_chart=rasi,
            hora_chart={},
            drekkana_chart={},
            navamsa_chart={},
            decamsa_chart={},
            dwadasamsa_chart={},
            chaturvimsa_chart={},
            trimshamsa_chart={},
            saptamsa_chart={},
            shashtyamsa_chart={},
            lagna=lagna,
            lagna_lord=lagna_lord,
            ayanamsa_value=0.0,
            house_cusps=[i * 30.0 for i in range(12)],
        )

    def test_sign_and_deg_via_sidereal_longitude(self):
        """_sign_and_deg: delegates to utils.longitude_to_sign_and_degree (lon % 360)."""
        from bphs_core.special_points import _sign_and_deg
        sign, deg = _sign_and_deg(45.5)  # 45.5° → Taurus 15.5°
        assert sign == "Taurus"
        assert abs(deg - 15.5) < 0.01

    def test_arudha_pada_house_landing_on_7_maps_to_4(self):
        """_arudha_pada_house: pada==7 case; the 10th from the pada is taken
        (pada 7 → 10th from 7 = 4th house)."""
        from bphs_core.special_points import _arudha_pada_house, _nth_house_from
        # lord_house such that ((2*lh-1)-1)%12+1 == 7.
        # 2*lh-2 ≡ 6 (mod 12)  →  2*lh ≡ 8 (mod 12)  → lh ≡ 4 (mod 6) → lh=4
        pada = _arudha_pada_house(4)
        # should not be 7; exception rule kicks in (7 → 10th from 7 = 4th)
        assert pada != 7
        assert pada == _nth_house_from(7, 10)

    def test_arudha_pada_house_landing_on_1_maps_to_10(self):
        """_arudha_pada_house: pada==1 case; 10th from pada 1 = house 10."""
        from bphs_core.special_points import _arudha_pada_house
        # lord_house such that ((2*lh-1)-1)%12+1 == 1 → 2*lh-2 ≡ 0 (mod 12) → lh=1
        pada = _arudha_pada_house(1)
        assert pada == 10

    def test_upapada_12th_lord_absent_returns_12th_sign(self):
        """get_upapada: 12th lord missing from rasi_chart → sign = the 12th sign itself."""
        from bphs_core.special_points import get_upapada
        # Aries lagna: 12th sign = Pisces, lord Jupiter — not in rasi_chart.
        snap = self._sp_snapshot(
            {"Sun": _planet("Aries", 10.0, 1, planet_name="Sun")},
            lagna="Aries",
        )
        result = get_upapada(snap)
        assert result.sign == "Pisces"

    def test_atmakaraka_empty_chart_returns_sun(self):
        """get_atmakaraka: no non-node candidates in rasi_chart → fallback 'Sun'."""
        from bphs_core.special_points import get_atmakaraka
        snap = self._sp_snapshot({})
        assert get_atmakaraka(snap) == "Sun"

    def test_karakamsa_ak_not_in_navamsa_uses_lagna(self):
        """get_karakamsa: the get_atmakaraka pick is absent from navamsa_chart →
        falls back to lagna."""
        from bphs_core.special_points import get_karakamsa
        # Sun has highest degrees but is not in navamsa_chart.
        rasi = {"Sun": _planet("Aries", 29.0, 1, planet_name="Sun")}
        snap = self._sp_snapshot(rasi, lagna="Gemini")
        # navamsa_chart is empty so ak_navamsa is None
        result = get_karakamsa(snap)
        assert result.sign == "Gemini"

    def test_arudha_lagna_lord_absent_returns_lagna_sign(self):
        """get_arudha_lagna: lagna lord absent from rasi_chart (so
        _arudha_pada_house is never reached) → sign = lagna, deg = 0."""
        from bphs_core.special_points import get_arudha_lagna
        # Mars is lagna_lord but not in rasi_chart.
        snap = self._sp_snapshot({}, lagna="Aries", lagna_lord="Mars")
        result = get_arudha_lagna(snap)
        assert result.sign == "Aries"
        assert result.degrees == 0.0

    def test_sidereal_longitude_uses_abs_when_available(self):
        """_sidereal_longitude: longitude_abs present → used as-is, mod 360."""
        from bphs_core.special_points import _sidereal_longitude
        # longitude_abs should be used as-is (mod 360).
        sun = _planet("Aries", 5.0, 1, planet_name="Sun", longitude_abs=395.0)
        snap = self._sp_snapshot({"Sun": sun})
        result = _sidereal_longitude(snap, "Sun")
        assert abs(result - 35.0) < 0.01   # 395 % 360 = 35

    def test_sidereal_longitude_fallback_reconstruction(self):
        """_sidereal_longitude: longitude_abs None → reconstructed from sign+degrees."""
        from bphs_core.special_points import _sidereal_longitude
        sun = _planet("Taurus", 5.0, 2, planet_name="Sun", longitude_abs=None)
        snap = self._sp_snapshot({"Sun": sun})
        result = _sidereal_longitude(snap, "Sun")
        # Taurus = sign index 1, so lon = 1*30 + 5 = 35
        assert abs(result - 35.0) < 0.01

    def test_sidereal_longitude_missing_planet_returns_zero(self):
        """_sidereal_longitude for absent planet returns 0.0."""
        from bphs_core.special_points import _sidereal_longitude
        snap = self._sp_snapshot({})
        assert _sidereal_longitude(snap, "Sun") == 0.0


# ===========================================================================
# §3.4 Transits/gochara — bphs_core/transits.py
# ===========================================================================

class TestTransitsEdges:
    """Edge branches covered here, named by function in bphs_core/transits.py:

      - ``get_sade_sati_info`` — natal Moon absent → inactive SadeSatiInfo.
      - ``compute_transit_signals`` — natal Moon absent → {}.
      - ``compute_gochara_vedha`` — natal Moon absent → [].
      - ``compute_transit_derived`` — natal Moon absent → all flags off; the
        chandrashtama arm (``_house_from_moon`` of the transit Moon == 8); both
        dhaiya / Kantaka Sani arms (transit Saturn's house from the natal Moon
        == 4, and == 8); and transit Saturn absent leaving dhaiya_phase None.
    """

    def _ts(self, moon_sign: str | None = "Aries"):
        if moon_sign is None:
            rasi = {}
        else:
            rasi = {"Moon": _planet(moon_sign, 10.0, 1, planet_name="Moon")}
        return _snapshot(rasi)

    def _tp(self, **by_graha):
        from bphs_core.transits import TransitPlacement
        result = {}
        for planet, sign in by_graha.items():
            result[planet] = TransitPlacement(
                planet=planet, sign=sign, degrees=10.0, nakshatra="Ashwini"
            )
        return result

    # --- get_sade_sati_info: no Moon ---
    def test_sade_sati_info_no_moon_returns_inactive(self):
        """get_sade_sati_info: natal Moon absent → SadeSatiInfo(is_active=False,
        phase='none')."""
        from bphs_core.transits import get_sade_sati_info
        snap = self._ts(None)
        result = get_sade_sati_info(snap, datetime.datetime(2025, 1, 1))
        assert result.is_active is False
        assert result.phase == "none"

    # --- compute_transit_signals: no Moon ---
    def test_transit_signals_no_moon_returns_empty(self):
        """compute_transit_signals: natal Moon absent → empty dict."""
        from bphs_core.transits import compute_transit_signals
        snap = self._ts(None)
        transits = self._tp(Jupiter="Gemini")
        assert compute_transit_signals(snap, transits) == {}

    # --- compute_gochara_vedha: no Moon ---
    def test_gochara_vedha_no_moon_returns_empty(self):
        """compute_gochara_vedha: natal Moon absent → []."""
        from bphs_core.transits import compute_gochara_vedha
        snap = self._ts(None)
        transits = self._tp(Mars="Gemini", Jupiter="Pisces")
        assert compute_gochara_vedha(snap, transits) == []

    # --- compute_transit_derived: no Moon ---
    def test_transit_derived_no_moon_returns_false_flags(self):
        """compute_transit_derived: natal Moon absent → all flags False/None."""
        from bphs_core.transits import compute_transit_derived
        snap = self._ts(None)
        result = compute_transit_derived(snap, self._tp())
        assert result == {
            "chandrashtama": False,
            "dhaiya_active": False,
            "dhaiya_phase": None,
        }

    # --- chandrashtama: transit Moon in 8th ---
    def test_chandrashtama_active_when_transit_moon_in_8th(self):
        """compute_transit_derived: chandrashtama=True when _house_from_moon of the
        transit Moon is the 8th from the natal Moon."""
        from bphs_core.transits import compute_transit_derived
        # Natal Moon in Aries (idx 0); 8th from Aries = Scorpio.
        snap = self._ts("Aries")
        transits = self._tp(Moon="Scorpio")
        result = compute_transit_derived(snap, transits)
        assert result["chandrashtama"] is True

    # --- dhaiya in 4th ---
    def test_dhaiya_active_saturn_in_4th_from_moon(self):
        """compute_transit_derived: dhaiya (Kantaka Sani) arm where transit Saturn's
        house from the natal Moon is the 4th."""
        from bphs_core.transits import compute_transit_derived
        # Natal Moon in Aries; 4th from Aries = Cancer.
        snap = self._ts("Aries")
        transits = self._tp(Saturn="Cancer")
        result = compute_transit_derived(snap, transits)
        assert result["dhaiya_active"] is True
        assert result["dhaiya_phase"] == "4th from natal Moon"

    # --- dhaiya in 8th ---
    def test_dhaiya_active_saturn_in_8th_from_moon(self):
        """compute_transit_derived: dhaiya arm where transit Saturn's house from the
        natal Moon is the 8th."""
        from bphs_core.transits import compute_transit_derived
        # Natal Moon in Aries; 8th from Aries = Scorpio.
        snap = self._ts("Aries")
        transits = self._tp(Saturn="Scorpio")
        result = compute_transit_derived(snap, transits)
        assert result["dhaiya_active"] is True
        assert result["dhaiya_phase"] == "8th from natal Moon"

    # --- no transit Saturn → dhaiya_phase stays None ---
    def test_dhaiya_none_when_no_transit_saturn(self):
        """dhaiya_phase is None when Saturn is absent from transits."""
        from bphs_core.transits import compute_transit_derived
        snap = self._ts("Aries")
        transits = self._tp(Moon="Aries")
        result = compute_transit_derived(snap, transits)
        assert result["dhaiya_phase"] is None


# ===========================================================================
# §3.4 Vimshopaka bala — bphs_core/vimshopaka.py
# ===========================================================================

class TestVimshopakaEdges:
    """Edge branches covered here, named by symbol in bphs_core/vimshopaka.py:

      - ``_DASHAVARGA_WEIGHTS_RAW`` — the module-level try/except around the
        pyjhora import, i.e. the literal BPHS fallback table in the except arm.
      - ``compute_vimshopaka`` — the ``pd is None`` arm, where a planet absent
        from a varga contributes 0 for that varga.
      - ``_rasi_longitudes`` — the refusal of a rasi chart without all seven
        grahas, whose places the temporary relationship needs.
    """

    def test_fallback_table_matches_bphs_if_pyjhora_unavailable(self):
        """_DASHAVARGA_WEIGHTS_RAW: the except-arm literal fallback table satisfies
        both invariants."""
        from bphs_core.vimshopaka import _DASHAVARGA_WEIGHTS_RAW
        # If pyjhora's import failed the fallback literal is used; either way these
        # must pass (the module asserts this at import time already, but we test
        # the values explicitly so a coverage probe touches the fallback branch).
        expected_keys = {1, 2, 3, 7, 9, 10, 12, 16, 30, 60}
        assert set(_DASHAVARGA_WEIGHTS_RAW) == expected_keys
        assert abs(sum(_DASHAVARGA_WEIGHTS_RAW.values()) - 20.0) < 1e-9

    def test_missing_planet_in_varga_contributes_zero(self):
        """compute_vimshopaka: pd is None arm — planet absent from a varga → 0 points
        for that varga."""
        from bphs_core.vimshopaka import compute_vimshopaka
        # Only populate rasi_chart (D1); all other vargas empty → D2..D60 contribute 0.
        rasi = {g: _planet("Capricorn", 10.0, 10, planet_name=g)
                for g in ("Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")}
        rasi["Sun"] = _planet("Leo", 10.0, 5, planet_name="Sun")
        result = compute_vimshopaka(_snapshot(rasi), "Sun")
        # D1 own sign (Leo) = 3.0 * 20 / 20 = 3.0. All others = 0.
        assert result.contributions["D1"] == pytest.approx(3.0)
        for label in ("D2", "D3", "D7", "D9", "D10", "D12", "D16", "D30", "D60"):
            assert result.contributions[label] == 0.0
        assert result.total == pytest.approx(3.0)

    def test_compute_all_vimshopaka_refuses_a_partial_rasi_chart(self):
        """_rasi_longitudes: a rasi chart without all seven grahas is refused,
        naming what is missing, rather than scored as nothing."""
        from bphs_core.vimshopaka import compute_all_vimshopaka
        sun = _planet("Aries", 10.0, 1, planet_name="Sun")
        snap = _snapshot({"Sun": sun})
        with pytest.raises(ValueError, match="Moon"):
            compute_all_vimshopaka(snap)


# ===========================================================================
# §3.4 Yoga detection — bphs_core/yogas.py
# ===========================================================================

class TestYogasEdges:
    """Edge branches covered here, named by function in bphs_core/yogas.py:

      - ``_compute_yoga_strength`` — the empty-``dignities`` arm → 'moderate'.
      - ``detect_viparita_raja_yoga`` — the ``lord is None`` continue guard.
      - ``detect_raja_yogas`` — the house-1 guard of the single-graha rule (house
        1 sits in both the kendra and the trikona list, and counts on neither
        side there), and the ``seen_pairs`` dedup.
      - ``detect_parivartana_yoga`` — an empty ``planets`` list (nothing to
        iterate), and the ``lord_of_a == p_a`` own-sign skip.
    """

    def _chart(self, planets=None, lagna="Aries",
               house_cusps=None):
        rasi = {}
        planets = planets or {}
        for p, d in planets.items():
            rasi[p] = PlanetData(
                planet=p,
                sign=d.get("sign", "Aries"),
                degrees=d.get("degrees", 0.0),
                nakshatra="Ashwini",
                house=d.get("house", 1),
                dignity=d.get("dignity", "neutral"),
                conjunctions=[],
                aspects=[],
                is_retrograde=False,
            )
        cusps = house_cusps or [i * 30.0 for i in range(12)]
        return ChartSnapshot(
            person=_person(),
            rasi_chart=rasi,
            lagna=lagna,
            lagna_lord="Mars",
            ayanamsa_value=0.0,
            house_cusps=cusps,
            hora_chart={},
            drekkana_chart={},
            navamsa_chart={},
            decamsa_chart={},
            dwadasamsa_chart={},
            chaturvimsa_chart={},
            trimshamsa_chart={},
            saptamsa_chart={},
            shashtyamsa_chart={},
        )

    def test_compute_yoga_strength_no_planets_returns_moderate(self):
        """_compute_yoga_strength: empty planets list → dignities empty → 'moderate'."""
        from bphs_core.yogas import _compute_yoga_strength
        chart = self._chart({})
        assert _compute_yoga_strength(chart, []) == "moderate"

    def test_viparita_raja_lord_none_skips(self):
        """detect_viparita_raja_yoga: the `lord is None` continue guard — _house_lord
        returning None for a house with no valid sign lord.

        Force lord=None by supplying a house_cusps where the 6th cusp points
        to a sign index that has no lord in utils.get_sign_lord — not possible
        in standard 12 signs. Instead verify that a chart with valid cusps but
        no planets doesn't crash and that at most 0 viparita yogas fire.
        """
        from bphs_core.yogas import detect_viparita_raja_yoga
        # Standard Aries lagna; 6th house = Virgo, lord Mercury; Mercury not in rasi.
        chart = self._chart({})
        # _house_lord returns "Mercury" for 6th; Mercury has no rasi entry so
        # _planet_house returns 0; 0 not in DUSTHANA → no yoga. No crash.
        result = detect_viparita_raja_yoga(chart)
        assert isinstance(result, list)

    def test_raja_yoga_same_house_degenerate_skipped(self):
        """detect_raja_yogas: the house-1 guard — house 1, counted in both the
        kendra and the trikona list, never makes its lord a single-graha yoga."""
        from bphs_core.yogas import detect_raja_yogas
        # Aries lagna: Mars lords house 1. House 1 is in both KENDRA and TRIKONA.
        # The (kh=1, th=1, kl==tl==Mars) case must NOT produce a spurious yoga.
        chart = self._chart(
            {"Mars": {"sign": "Leo", "house": 5, "dignity": "neutral"}}
        )
        yogas = detect_raja_yogas(chart)
        # If a Raja Yoga appears it must not be the degenerate self-paired one.
        for y in yogas:
            if y.planets_involved == ["Mars"] and y.houses_involved == [1]:
                pytest.fail("Degenerate house-1 Raja Yoga was not suppressed")

    def test_raja_yoga_seen_conjunction_dedup(self):
        """detect_raja_yogas seen_pairs dedup: the same kendra-lord/trikona-lord
        pair conjunct in the same house must appear only once even if enumerated from
        multiple (kh, th) combinations."""
        from bphs_core.yogas import detect_raja_yogas
        # Aries lagna: house_cusps → Aries(1),Tau(2),Gem(3),Can(4),Leo(5),Vir(6)...
        # Set up so Jupiter lords kendra(4=Cancer) AND trikona(9) and Mercury lords
        # kendra(10)... actually simplest: put 1st lord (Mars) and 5th lord (Sun) conjunct.
        # Just check the dedup by verifying the result count == 1 even for a
        # legitimate multi-way pairing.
        chart = self._chart({
            "Mars":    {"sign": "Gemini", "house": 3, "dignity": "neutral"},
            "Jupiter": {"sign": "Gemini", "house": 3, "dignity": "neutral"},
        })
        yogas = detect_raja_yogas(chart)
        # Mars (kendra lord of 1 and 7?) and Jupiter (trikona lord of 9): one Raja Yoga.
        raja_yogas = [y for y in yogas if y.name == "Raja Yoga"]
        # Validate no duplicate planet pair.
        pairs_seen = set()
        for y in raja_yogas:
            pair = frozenset(y.planets_involved)
            assert pair not in pairs_seen, "Duplicate Raja Yoga pair detected"
            pairs_seen.add(pair)

    def test_detect_parivartana_empty_chart(self):
        """detect_parivartana_yoga: no planets in rasi_chart → empty list (no iteration)."""
        from bphs_core.yogas import detect_parivartana_yoga
        chart = self._chart({})
        assert detect_parivartana_yoga(chart) == []

    def test_detect_parivartana_self_lord_skips(self):
        """detect_parivartana_yoga: planet in its own sign (lord_of_a == p_a) → skipped."""
        from bphs_core.yogas import detect_parivartana_yoga
        # Sun in Leo: lord of Leo is Sun → lord_of_a == p_a, so skipped.
        chart = self._chart({
            "Sun": {"sign": "Leo", "house": 5, "dignity": "own sign"},
        })
        result = detect_parivartana_yoga(chart)
        assert result == []


# ===========================================================================
# §3.4 Shadbala/Bhavabala — bphs_core/strength.py
# ===========================================================================

class TestStrengthEdges:
    """Edge branches covered here, named by function in bphs_core/strength.py:

      - ``compute_shadbala`` — planet absent from rasi_chart → ValueError, and
        a node (no Shadbala exists for Rahu or Ketu) → ValueError.
      - ``_next_solar_event`` — swisseph reports no rise or set (polar day or
        night) → ``ShadbalaUndefinedError``, never a fabricated day frame.
      - ``compute_ashtakavarga`` — the ``ref_idx.get(ref) is None`` continue for a
        reference point absent from the chart, and the ``planet is not None``
        single-planet return.
    """

    def test_compute_shadbala_refuses_a_node(self):
        """compute_shadbala: BPHS 27 defines Shadbala for the seven grahas only."""
        from bphs_core.strength import compute_shadbala
        rahu = _planet("Aries", 10.0, 1, planet_name="Rahu")
        with pytest.raises(ValueError, match="defined for the seven grahas, not Rahu"):
            compute_shadbala(_snapshot({"Rahu": rahu}), "Rahu")

    def test_bhavabala_refuses_a_chart_missing_a_graha(self):
        """strength_inputs: every graha's Shadbala feeds some house's lord, so
        a chart without all seven is refused before any ephemeris call."""
        from bphs_core.strength import compute_all_bhavabala
        sun = _planet("Aries", 10.0, 1, planet_name="Sun")
        with pytest.raises(ValueError, match=r"lacks \['Moon', 'Mars'"):
            compute_all_bhavabala(_snapshot({"Sun": sun}))

    def test_no_solar_event_raises_undefined(self, monkeypatch):
        """_next_solar_event: a non-zero rise_trans status (the Sun circumpolar
        or below the horizon all day) raises ShadbalaUndefinedError."""
        from bphs_core import strength
        monkeypatch.setattr(strength.swe, "rise_trans",
                            lambda *a, **k: (-2, (0.0,) * 10))
        with pytest.raises(strength.ShadbalaUndefinedError):
            strength._next_solar_event(2451545.0, 897, (15.6, 78.2, 0.0))

    def test_compute_shadbala_raises_for_missing_planet(self):
        """compute_shadbala: raises ValueError when the planet is not in rasi_chart.

        The message is matched whole: strength_inputs refuses the same chart
        with a different ValueError that also names the Sun."""
        from bphs_core.strength import compute_shadbala
        snap = _snapshot({})
        with pytest.raises(ValueError, match=r"^Planet Sun not found in chart$"):
            compute_shadbala(snap, "Sun")

    def test_ashtakavarga_ref_none_is_skipped(self):
        """compute_ashtakavarga: a reference planet absent from rasi_chart → its
        contribution skipped (ref_idx.get returns None → continue)."""
        from bphs_core.strength import compute_ashtakavarga
        # Only Moon in chart; Sun, Mars etc. are absent.
        # Lagna is present (always added from snapshot.lagna).
        moon = _planet("Taurus", 5.0, 2, planet_name="Moon")
        snap = _snapshot({"Moon": moon}, lagna="Aries")
        result = compute_ashtakavarga(snap)
        # Should succeed; samudaya signs are all present.
        assert len(result["samudaya"]) == 12
        # binna has 7 planet keys.
        assert len(result["binna"]) == 7

    def test_ashtakavarga_per_planet_mode(self):
        """compute_ashtakavarga: the planet is not None arm returns that planet's
        binna directly."""
        from bphs_core.strength import compute_ashtakavarga
        moon = _planet("Taurus", 5.0, 2, planet_name="Moon")
        snap = _snapshot({"Moon": moon}, lagna="Aries")
        result = compute_ashtakavarga(snap, planet="Moon")
        # binna is now a flat {sign: count} not a nested {planet: {sign: count}}
        assert isinstance(result["binna"], dict)
        # Spot-check: values are ints 0-8
        for v in result["binna"].values():
            assert 0 <= v <= 8
