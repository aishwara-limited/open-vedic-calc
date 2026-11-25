"""Classical Shadbala and Bhavabala, rule by rule (bphs_core/strength.py).

Standard: Brihat Parashara Hora Shastra (BPHS), R. Santhanam's translation,
wherever BPHS gives a rule; the Surya Siddhanta (Burgess translation) where
BPHS is silent. Every expected value below was worked out from those rules,
independently of the module under test:

* the small-domain rules are pinned EXHAUSTIVELY by hand tables (every sign,
  every house, every decanate, every sign-band of the aspect rules);
* three charts are worked fully by hand, component by component, for all
  seven grahas and all twelve houses. Their inputs are fixed numbers, not a
  live ephemeris, so the arithmetic is reproducible on paper; they are
  synthetic and need not be a real sky. Chart A is worked through in the
  comments of ``TestChartAWorkedSun``; the tables in ``_WORKED`` came from
  the same rules by the same steps;
* two published worked examples are reproduced where the rule matches:
  saravali.github.io's Parasara ayana bala example (1 May 1990, 0:00 UT,
  BPHS 27.15-17 khanda method, sayana longitudes) and its uchcha bala
  example (the Sun at 12 Gemini), and the ahargana of 1 January 1860 given
  in Santhanam's translator's note to BPHS 27.13 (714,404,108,573, a Sunday).
"""
import math

import pytest

from bphs_core import strength as st
from bphs_core.strength import StrengthInputs

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
         "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
GRAHAS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

# ---------------------------------------------------------------------------
# Sphuta drishti, BPHS 26.6-12: every sign-band, at its start (r = 0) and its
# middle (r = 15), for the general rule and for Saturn, Mars and Jupiter.
# ---------------------------------------------------------------------------

#                 s:  0      1      2      3      4      5      6      7      8      9      10     11
_GENERAL = [(0, 0), (0, 7.5), (15, 30), (45, 37.5), (30, 15), (0, 30),
            (60, 52.5), (45, 37.5), (30, 22.5), (15, 7.5), (0, 0), (0, 0)]
_SPECIAL = {
    # BPHS 26.10: s1 2r; s2 60 - r/2; s8 30 + r; s9 2(30 - r)
    "Saturn": {1: (0, 30), 2: (60, 52.5), 8: (30, 45), 9: (60, 30)},
    # BPHS 26.11: s2 15 + 1.5r; s3 and s7 60 - r; s6 60
    "Mars": {2: (15, 37.5), 3: (60, 45), 6: (60, 60), 7: (60, 45)},
    # BPHS 26.12: s3 and s7 45 + r/2; s4 and s8 60 - 2r
    "Jupiter": {3: (45, 52.5), 4: (60, 30), 7: (45, 52.5), 8: (60, 30)},
}


@pytest.mark.parametrize("aspecting", GRAHAS)
@pytest.mark.parametrize("band", range(12))
def test_sphuta_drishti_every_band(aspecting, band):
    start, middle = _SPECIAL.get(aspecting, {}).get(band, _GENERAL[band])
    assert st.sphuta_drishti(aspecting, 30.0 * band) == pytest.approx(start)
    assert st.sphuta_drishti(aspecting, 30.0 * band + 15.0) == pytest.approx(middle)


@pytest.mark.parametrize("aspecting", GRAHAS)
def test_sphuta_drishti_peaks_and_range(aspecting):
    """Every value lies in [0, 60]; the full aspects are where BPHS 26.3-4
    puts them: the 7th for all, Saturn's 3rd and 10th, Mars's 4th and 8th,
    Jupiter's 5th and 9th."""
    values = [st.sphuta_drishti(aspecting, k / 4.0) for k in range(1440)]
    assert min(values) >= 0.0 and max(values) <= 60.0
    full = {"Saturn": [60.0, 180.0, 270.0], "Mars": [90.0, 180.0, 210.0],
            "Jupiter": [120.0, 180.0, 240.0]}.get(aspecting, [180.0])
    for angle in full:
        assert st.sphuta_drishti(aspecting, angle) == 60.0


# ---------------------------------------------------------------------------
# Saptavargaja states, BPHS 27.2-4 with BPHS 3.51-58: every graha in every
# sign of a divisional chart, against the rasi placements of chart A (Sun
# Aries, Moon Cancer, Mars Libra, Mercury Taurus, Jupiter Virgo, Venus
# Pisces, Saturn Libra). Each entry is natural + temporary relationship to
# the sign's lord, worked by hand (MT = moolatrikona sign, own = own sign).
# ---------------------------------------------------------------------------

_CHART_A_LONGITUDES = {"Sun": 25.5, "Moon": 100.0, "Mars": 200.4, "Mercury": 40.0,
                       "Jupiter": 155.0, "Venus": 340.0, "Saturn": 200.0,
                       "Rahu": 70.0, "Ketu": 250.0}
_ABBR = {"MT": "moolatrikona", "own": "own", "AF": "great friend", "F": "friend",
         "N": "neutral", "E": "enemy", "AE": "great enemy"}
#             Ari   Tau   Gem   Can   Leo   Vir   Lib   Sco   Sag   Cap   Aqu   Pis
_VARGA_STATES = {
    "Sun":     "N    N    F    AF   MT   F    N    N    N    AE   AE   N",
    "Moon":    "F    MT   AF   own  AF   AF   E    F    F    F    F    F",
    "Mars":    "MT   E    AE   AF   N    AE   E    own  AF   E    E    AF",
    "Mercury": "E    AF   own  N    AF   MT   AF   E    E    E    E    E",
    "Jupiter": "AF   AE   AE   AF   N    AE   AE   AF   MT   F    F    own",
    "Venus":   "E    own  AF   AE   N    AF   MT   E    E    N    N    E",
    "Saturn":  "AE   N    N    N    AE   N    N    AE   F    own  MT   F",
}


@pytest.mark.parametrize("planet", GRAHAS)
@pytest.mark.parametrize("sign_idx", range(12))
def test_varga_state_every_sign(planet, sign_idx):
    want = _ABBR[_VARGA_STATES[planet].split()[sign_idx]]
    got = st.varga_state(planet, SIGNS[sign_idx], None, _CHART_A_LONGITUDES)
    assert got == want


# Rasi chart: moolatrikona by the degree arcs of BPHS 3.51-54; outside the arc
# the graha is in its own sign (or, for the Moon in her first 3 degrees of
# Taurus, which is not her own sign, in the sign lord's relationship).
@pytest.mark.parametrize("planet,sign,inside,outside,outside_state", [
    ("Sun", "Leo", 19.99, 20.0, "own"),
    ("Moon", "Taurus", 3.0, 2.99, "enemy"),       # Venus: neutral + temporary enemy
    ("Mars", "Aries", 11.99, 12.0, "own"),
    ("Mercury", "Virgo", 15.0, 14.99, "own"),
    ("Mercury", "Virgo", 19.99, 20.0, "own"),
    ("Jupiter", "Sagittarius", 9.99, 10.0, "own"),
    ("Venus", "Libra", 14.99, 15.0, "own"),
    ("Saturn", "Aquarius", 19.99, 20.0, "own"),
])
def test_rasi_moolatrikona_arcs(planet, sign, inside, outside, outside_state):
    base = 30.0 * SIGNS.index(sign)
    assert st.varga_state(planet, sign, base + inside, _CHART_A_LONGITUDES) == "moolatrikona"
    assert st.varga_state(planet, sign, base + outside, _CHART_A_LONGITUDES) == outside_state


# ---------------------------------------------------------------------------
# Ayana bala, BPHS 27.15-17: the khandas, and the north/south rule in every
# sayana sign (taken at 15 degrees in, ayanamsa 0).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bhuja,kranti", [
    (0, 0), (15, 22.5), (30, 45), (45, 61.5), (60, 78), (75, 84), (90, 90),
])
def test_kranti_khanda(bhuja, kranti):
    assert st.kranti_khanda(bhuja) == pytest.approx(kranti)


# Kranti at 15 degrees into each sayana sign: bhuja 15, 45 or 75.
_KRANTI_AT_15 = [22.5, 61.5, 84, 84, 61.5, 22.5, 22.5, 61.5, 84, 84, 61.5, 22.5]


def _inputs(longitudes, **overrides):
    base = dict(
        longitudes=longitudes,
        latitudes={g: 0.0 for g in ("Mars", "Mercury", "Jupiter", "Venus", "Saturn")},
        varga_signs={}, ayanamsa=0.0, ascendant=0.0, midheaven=270.0,
        birth_jd=2451545.0, sunrise_jd=2451544.8, sunset_jd=2451545.3,
        next_sunrise_jd=2451545.8, local_apparent_hours=12.0, hindu_day_jdn=2451545,
    )
    base.update(overrides)
    return StrengthInputs(**base)


@pytest.mark.parametrize("sign_idx", range(12))
@pytest.mark.parametrize("planet", GRAHAS)
def test_ayana_north_south_rule_every_sign(planet, sign_idx):
    kranti = _KRANTI_AT_15[sign_idx]
    northern = sign_idx < 6
    if planet == "Mercury":
        adds = True
    elif planet in ("Moon", "Saturn"):
        adds = not northern
    else:
        adds = northern
    want = (90 + kranti) / 3 if adds else (90 - kranti) / 3
    inp = _inputs({planet: 30.0 * sign_idx + 15.0})
    assert st._ayana_bala(planet, inp) == pytest.approx(want)


# Published worked example: saravali.github.io, Ayana Bala, 1 May 1990 0:00
# UT, the Parasara (BPHS 27.15-17) column, from sayana longitudes; values
# published to one decimal (the Moon's 3.989 is printed truncated as 3.9).
@pytest.mark.parametrize("planet,sayana,published", [
    ("Sun", 30 + 10 + 22 / 60, 48.8),
    ("Moon", 90 + 29 + 55 / 60, 3.9),
    ("Mars", 330 + 7 + 32 / 60, 18.8),
    ("Mercury", 30 + 15 + 5 / 60, 50.5),
    ("Jupiter", 90 + 6 + 57 / 60, 59.1),
    ("Venus", 330 + 26 + 28 / 60, 28.2),
    ("Saturn", 270 + 25 + 20 / 60, 56.6),
])
def test_ayana_matches_published_example(planet, sayana, published):
    got = st._ayana_bala(planet, _inputs({planet: sayana}))
    assert abs(got - published) < 0.1


# ---------------------------------------------------------------------------
# Uchcha, ojayugma, kendradi, drekkana and dig bala rules, exhaustively.
# ---------------------------------------------------------------------------

def test_uchcha_published_example():
    """saravali.github.io: the Sun at 12 Gemini is 118 degrees from his deep
    debilitation (10 Libra): 39.3 virupas."""
    assert st._uchcha_bala("Sun", 72.0) == pytest.approx(118 / 3)


@pytest.mark.parametrize("planet,exalted,debilitated", [
    ("Sun", 10.0, 190.0), ("Moon", 33.0, 213.0), ("Mars", 298.0, 118.0),
    ("Mercury", 165.0, 345.0), ("Jupiter", 95.0, 275.0), ("Venus", 357.0, 177.0),
    ("Saturn", 200.0, 20.0),
])
def test_uchcha_extremes(planet, exalted, debilitated):
    """BPHS 3.49-50 deep points: 60 at deep exaltation, 0 at deep debilitation."""
    assert st._uchcha_bala(planet, exalted) == pytest.approx(60.0)
    assert st._uchcha_bala(planet, debilitated) == pytest.approx(0.0)


@pytest.mark.parametrize("sign_idx", range(12))
@pytest.mark.parametrize("planet", GRAHAS)
def test_ojayugma_every_sign(planet, sign_idx):
    """BPHS 27.4: 15 in the rasi and 15 in the navamsa, odd signs (Aries,
    Gemini, ...) for all but the Moon and Venus, who want even signs."""
    odd = sign_idx % 2 == 0
    gains = (not odd) if planet in ("Moon", "Venus") else odd
    inp = _inputs({planet: 30.0 * sign_idx + 1.0}, varga_signs={"D9": {planet: SIGNS[sign_idx]}})
    assert st._ojayugma_bala(planet, inp) == (30.0 if gains else 0.0)


@pytest.mark.parametrize("house,want", [
    (1, 60), (2, 30), (3, 15), (4, 60), (5, 30), (6, 15),
    (7, 60), (8, 30), (9, 15), (10, 60), (11, 30), (12, 15),
])
def test_kendradi_every_house(house, want):
    """BPHS 27.5, whole-sign houses from a lagna in Leo."""
    inp = _inputs({"Mars": (120.0 + 30.0 * (house - 1) + 5.0) % 360.0}, ascendant=125.0)
    assert st._kendradi_bala("Mars", inp) == want


@pytest.mark.parametrize("planet,gaining", [
    ("Sun", 0), ("Mars", 0), ("Jupiter", 0), ("Moon", 1), ("Venus", 1),
    ("Mercury", 2), ("Saturn", 2),
])
@pytest.mark.parametrize("decanate", range(3))
def test_drekkana_every_decanate(planet, gaining, decanate):
    """BPHS 27.6 with BPHS 3.19: male first, female second, neuter third."""
    inp = _inputs({planet: 60.0 + 10.0 * decanate + 5.0})
    assert st._drekkana_bala(planet, inp) == (15.0 if decanate == gaining else 0.0)


@pytest.mark.parametrize("planet,strongest", [
    ("Sun", "mc"), ("Mars", "mc"), ("Jupiter", "asc"), ("Mercury", "asc"),
    ("Moon", "ic"), ("Venus", "ic"), ("Saturn", "desc"),
])
def test_dig_bala_full_at_the_classical_direction(planet, strongest):
    """BPHS 27.7: full (60) at the point opposite the one deducted, nil on it."""
    asc, mc = 100.0, 10.0
    point = {"asc": asc, "desc": asc + 180, "mc": mc, "ic": mc + 180}[strongest]
    full = st._dig_bala(planet, _inputs({planet: point % 360}, ascendant=asc, midheaven=mc))
    nil = st._dig_bala(planet, _inputs({planet: (point + 180) % 360}, ascendant=asc, midheaven=mc))
    assert full == pytest.approx(60.0) and nil == pytest.approx(0.0)


# Bhava digbala reference points, BPHS 27.26-28, for every sign and both
# halves (ascendant 7 deg, so the descendant is 187 and the lagna itself 7;
# meridian 280, so the nadir is 100).
#                     Ari    Tau    Gem    Can    Leo    Vir    Lib    Sco    Sag    Cap    Aqu    Pis
_BHAVA_REF_FIRST = ["ic", "ic", "desc", "asc", "ic", "desc", "desc", "asc", "desc", "ic", "desc", "mc"]
_BHAVA_REF_SECOND = ["ic", "ic", "desc", "asc", "ic", "desc", "desc", "asc", "ic", "mc", "desc", "mc"]


@pytest.mark.parametrize("sign_idx", range(12))
@pytest.mark.parametrize("second_half", [False, True])
def test_bhava_dig_reference_every_sign(sign_idx, second_half):
    inp = _inputs({}, ascendant=7.0, midheaven=280.0)
    points = {"asc": 7.0, "desc": 187.0, "mc": 280.0, "ic": 100.0}
    table = _BHAVA_REF_SECOND if second_half else _BHAVA_REF_FIRST
    madhya = 30.0 * sign_idx + (20.0 if second_half else 5.0)
    assert st.bhava_dig_reference(madhya, inp) % 360 == pytest.approx(points[table[sign_idx]])


@pytest.mark.parametrize("degree,dhanus,makara", [
    (14.99, "desc", "ic"),
    (15.0, "ic", "mc"),
])
def test_bhava_dig_reference_half_sign_cut(degree, dhanus, makara):
    """BPHS 27.26-28 cut Dhanus and Makara at their middle, 15 degrees: the
    first half of Dhanus takes the 7th, its second half the 4th; the first
    half of Makara the 4th, its second half the 10th. 15.0 itself opens the
    second half."""
    inp = _inputs({}, ascendant=7.0, midheaven=280.0)
    points = {"asc": 7.0, "desc": 187.0, "mc": 280.0, "ic": 100.0}
    assert st.bhava_dig_reference(240.0 + degree, inp) % 360 == pytest.approx(points[dhanus])
    assert st.bhava_dig_reference(270.0 + degree, inp) % 360 == pytest.approx(points[makara])


# ---------------------------------------------------------------------------
# Kaala bala: nathonnata, tribhaga, the four lords, paksha.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hours,night_value", [
    (0.0, 60.0), (6.0, 30.0), (12.0, 0.0), (18.0, 30.0), (21.0, 45.0), (3.0, 45.0),
])
def test_nathonnata(hours, night_value):
    """BPHS 27.8-9: double the nata for the Moon, Mars and Saturn; 60 less
    that for the Sun, Jupiter and Venus; Mercury 60 at any hour."""
    inp = _inputs({}, local_apparent_hours=hours)
    for planet in ("Moon", "Mars", "Saturn"):
        assert st._nathonnata_bala(planet, inp) == pytest.approx(night_value)
    for planet in ("Sun", "Jupiter", "Venus"):
        assert st._nathonnata_bala(planet, inp) == pytest.approx(60.0 - night_value)
    assert st._nathonnata_bala("Mercury", inp) == 60.0


@pytest.mark.parametrize("fraction,day,lord", [
    (0.10, True, "Mercury"), (0.50, True, "Sun"), (0.90, True, "Saturn"),
    (0.10, False, "Moon"), (0.50, False, "Venus"), (0.90, False, "Mars"),
])
def test_tribhaga_every_third(fraction, day, lord):
    """BPHS 27.12: thirds of the day and of the night; Jupiter always."""
    sr, ss, nsr = 100.0, 100.5, 101.0
    birth = sr + fraction * (ss - sr) if day else ss + fraction * (nsr - ss)
    inp = _inputs({}, sunrise_jd=sr, sunset_jd=ss, next_sunrise_jd=nsr, birth_jd=birth)
    for planet in GRAHAS:
        want = 60.0 if planet in (lord, "Jupiter") else 0.0
        assert st._tribhaga_bala(planet, inp) == want


def test_ahargana_matches_published_1860():
    """Santhanam's note to BPHS 27.13: 1 January 1860 (JDN 2400411) is
    ahargana 714,404,108,573, whose remainder by 7 is 1: Sunday."""
    inp = _inputs({}, hindu_day_jdn=2400411)
    assert st.ahargana(inp) == 714_404_108_573
    assert st.weekday_lord(inp) == "Sun"


@pytest.mark.parametrize("offset", range(7))
def test_weekday_lord_follows_the_calendar(offset):
    """Seven consecutive days from Sunday 1 January 1860 run Sun to Saturn,
    the civil weekday of each Julian Day Number."""
    jdn = 2400411 + offset
    assert st.weekday_lord(_inputs({}, hindu_day_jdn=jdn)) == GRAHAS[(jdn + 1) % 7]


def test_year_and_month_lords_by_hand():
    """Surya Siddhanta 1.52 for 1 January 1860 (ahargana 714,404,108,573):
    year: quotient by 360 = 1,984,455,857; times 3 plus 1 = 5,953,367,572;
    remainder by 7 = 5 -> Thursday's lord, Jupiter. Month: quotient by 30 =
    23,813,470,285; times 2 plus 1 = 47,626,940,571 = 7 x 6,803,848,653;
    remainder 0 -> Saturday's lord, Saturn."""
    inp = _inputs({}, hindu_day_jdn=2400411)
    assert 714_404_108_573 // 360 == 1_984_455_857
    assert (1_984_455_857 * 3 + 1) % 7 == 5
    assert 714_404_108_573 // 30 == 23_813_470_285
    assert (23_813_470_285 * 2 + 1) % 7 == 0
    assert st.year_lord(inp) == "Jupiter"
    assert st.month_lord(inp) == "Saturn"


def test_hora_sequence_from_a_sunday_sunrise():
    """BPHS 27.13: 24 equal horas from sunrise; Sunday's run Sun, Venus,
    Mercury, Moon, Saturn, Jupiter, Mars and round again."""
    cycle = ["Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars"]
    for k in range(24):
        inp = _inputs({}, hindu_day_jdn=2400411, sunrise_jd=10.0, next_sunrise_jd=11.0,
                      sunset_jd=10.5, birth_jd=10.0 + (k + 0.5) / 24.0)
        assert st.hora_lord(inp) == cycle[k % 7], k


@pytest.mark.parametrize("moon,benefic", [
    (90.0, True), (179.9, True), (180.0, False), (270.0, False), (0.0, False), (0.1, True),
])
def test_moon_benefic_only_while_waxing(moon, benefic):
    """BPHS 3.11: the waning Moon is malefic; waxing is elongation in (0, 180)."""
    assert st.is_benefic("Moon", {"Sun": 0.0, "Moon": moon}) is benefic


@pytest.mark.parametrize("companion,benefic", [
    (None, True), ("Sun", False), ("Mars", False), ("Saturn", False), ("Rahu", False),
    ("Ketu", False), ("Jupiter", True), ("Venus", True),
])
def test_mercury_turns_malefic_beside_a_malefic(companion, benefic):
    """BPHS 3.11: Mercury is malefic when he joins (shares the sign of) a malefic."""
    # Everyone else from Gemini onwards, out of Mercury's Aries.
    longitudes = {g: 60.0 + 30 * i for i, g in enumerate(
        ["Sun", "Moon", "Mars", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"])}
    longitudes["Moon"] = longitudes["Sun"] + 90.0   # waxing
    longitudes["Mercury"] = 5.0
    if companion:
        longitudes[companion] = 20.0
    assert st.is_benefic("Mercury", longitudes) is benefic


def test_mercury_beside_the_waning_moon_is_malefic():
    longitudes = {"Sun": 100.0, "Moon": 10.0, "Mercury": 20.0}
    assert st.is_benefic("Mercury", longitudes) is False
    longitudes["Moon"] = 190.0  # waxing now, and no longer in Mercury's sign
    assert st.is_benefic("Mercury", longitudes) is True


@pytest.mark.parametrize("moon", [0.0, 45.0, 90.0, 180.0, 225.0, 330.0])
def test_paksha_benefic_and_malefic(moon):
    """BPHS 27.10-11: the reduced Sun-Moon arc / 3 for a benefic (Jupiter),
    60 less that for a malefic (Saturn)."""
    arc = min(moon % 360, 360 - moon % 360)
    inp = _inputs({"Sun": 0.0, "Moon": moon})
    assert st._paksha_bala("Jupiter", inp) == pytest.approx(arc / 3)
    assert st._paksha_bala("Saturn", inp) == pytest.approx(60 - arc / 3)


# ---------------------------------------------------------------------------
# Surya Siddhanta mean motions and the cheshta kendra.
# ---------------------------------------------------------------------------

def test_mean_grahas_conjoin_at_the_kali_epoch():
    """Surya Siddhanta 1.57: every mean graha and sighrocca at 0 Aries at the
    Kali epoch, and back there after one Mahayuga's civil days."""
    epoch = st._KALI_EPOCH_JD_UT
    for body in st._SS_REVOLUTIONS:
        for jd in (epoch, epoch + st._SS_CIVIL_DAYS):
            got = st.surya_siddhanta_mean_longitude(body, jd)
            assert min(got, 360.0 - got) < 1e-6, body


def test_mean_sun_against_a_modern_mean_sun():
    """With the ephemeris directly: the Surya Siddhanta mean Sun stays within
    a degree and a half of the modern mean Sun (Meeus 25.2, made sidereal by
    the engine's own Lahiri ayanamsa) across the served span. Measured at
    five-year steps 1800-2400: -1.25 to +0.17 degrees (the Surya Siddhanta
    year is about 0.0024 day longer than the sidereal year)."""
    import swisseph as swe
    from jhora.panchanga import drik
    for year in range(1800, 2401, 50):
        jd = swe.julday(year, 6, 1, 0.0)
        t = (jd - 2451545.0) / 36525.0
        modern = (280.46646 + 36000.76983 * t + 0.0003032 * t * t
                  - drik.get_ayanamsa_value(jd)) % 360.0
        got = st.surya_siddhanta_mean_longitude("Sun", jd)
        assert abs(((got - modern + 180.0) % 360.0) - 180.0) < 1.5, year


@pytest.mark.parametrize("kendra,want", [(0.0, 0.0), (90.0, 30.0), (180.0, 60.0),
                                         (190.0, 170.0 / 3), (350.0, 10.0 / 3)])
def test_cheshta_kendra_reduced_past_six_signs(monkeypatch, kendra, want):
    """BPHS 27.24-25 with the reduction of 27.1: a kendra past six signs is
    deducted from twelve before the division by three, so never above 60."""
    monkeypatch.setattr(st, "cheshta_kendra", lambda planet, inp: kendra)
    assert st._cheshta_bala("Mars", _inputs({})) == pytest.approx(want)


def test_cheshta_kendra_half_sum_on_the_shorter_arc(monkeypatch):
    """A mean longitude of 10 and a true one of 350 lie either side of 0
    Aries; their half-sum is 0, not 180. With the mean Sun (the sighrocca of
    Mars) at 100 the kendra is 100 - 0 = 100, not 100 - 180 = 280."""
    means = {"Sun": 100.0, "Mars": 10.0}
    monkeypatch.setattr(st, "surya_siddhanta_mean_longitude", lambda body, jd: means[body])
    assert st.cheshta_kendra("Mars", _inputs({"Mars": 350.0})) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Three charts worked by hand, every sub-bala of every graha (virupas).
# Column order: uchcha, saptavargaja, ojayugma, kendradi, drekkana, dig,
# nathonnata, paksha, tribhaga, lords, ayana, yuddha, cheshta, naisargika,
# drik.
# ---------------------------------------------------------------------------

_COLUMNS = ("uchcha", "saptavargaja", "ojayugma", "kendradi", "drekkana", "dig",
            "nathonnata", "paksha", "tribhaga", "lords", "ayana", "yuddha",
            "cheshta", "naisargika", "drik")

# Divisional signs by BPHS 6 (hora 6.5-6, drekkana 6.7-8, saptamsa 6.10,
# navamsa 6.12, dwadasamsa 6.15, trimsamsa 6.27), worked by hand.
_CHARTS = {
    # Day birth (second third, Sun's hora), waxing Moon, Mars and Saturn at
    # war 0.4 degree apart (Saturn north, the victor).
    "A": dict(
        longitudes=_CHART_A_LONGITUDES,
        latitudes={"Mars": 1.2, "Mercury": -2.0, "Jupiter": 0.5, "Venus": -1.0, "Saturn": 2.1},
        varga_signs={
            "D2": {"Sun": "Cancer", "Moon": "Cancer", "Mars": "Cancer", "Mercury": "Cancer",
                   "Jupiter": "Cancer", "Venus": "Cancer", "Saturn": "Cancer"},
            "D3": {"Sun": "Sagittarius", "Moon": "Scorpio", "Mars": "Gemini", "Mercury": "Virgo",
                   "Jupiter": "Virgo", "Venus": "Cancer", "Saturn": "Gemini"},
            "D7": {"Sun": "Virgo", "Moon": "Pisces", "Mars": "Aquarius", "Mercury": "Capricorn",
                   "Jupiter": "Aries", "Venus": "Scorpio", "Saturn": "Aquarius"},
            "D9": {"Sun": "Scorpio", "Moon": "Libra", "Mars": "Aries", "Mercury": "Aries",
                   "Jupiter": "Aquarius", "Venus": "Libra", "Saturn": "Aries"},
            "D12": {"Sun": "Aquarius", "Moon": "Scorpio", "Mars": "Gemini", "Mercury": "Virgo",
                    "Jupiter": "Scorpio", "Venus": "Cancer", "Saturn": "Gemini"},
            "D30": {"Sun": "Libra", "Moon": "Virgo", "Mars": "Gemini", "Mercury": "Virgo",
                    "Jupiter": "Virgo", "Venus": "Virgo", "Saturn": "Gemini"},
        },
        ayanamsa=23.85, ascendant=95.0, midheaven=2.0,
        birth_jd=2460000.31, sunrise_jd=2460000.05, sunset_jd=2460000.55,
        next_sunrise_jd=2460001.05, local_apparent_hours=10.75, hindu_day_jdn=2460000,
    ),
    # Night birth (first third), waning Moon, Mercury beside the Sun.
    "B": dict(
        longitudes={"Sun": 280.0, "Moon": 230.0, "Mars": 85.0, "Mercury": 295.0,
                    "Jupiter": 128.0, "Venus": 322.0, "Saturn": 268.0,
                    "Rahu": 15.0, "Ketu": 195.0},
        latitudes={"Mars": 0.3, "Mercury": 1.0, "Jupiter": -0.4, "Venus": 2.0, "Saturn": 0.9},
        varga_signs={
            "D2": {"Sun": "Cancer", "Moon": "Leo", "Mars": "Cancer", "Mercury": "Leo",
                   "Jupiter": "Leo", "Venus": "Cancer", "Saturn": "Cancer"},
            "D3": {"Sun": "Taurus", "Moon": "Cancer", "Mars": "Aquarius", "Mercury": "Virgo",
                   "Jupiter": "Leo", "Venus": "Libra", "Saturn": "Leo"},
            "D7": {"Sun": "Virgo", "Moon": "Virgo", "Mars": "Scorpio", "Mercury": "Sagittarius",
                   "Jupiter": "Virgo", "Venus": "Cancer", "Saturn": "Gemini"},
            "D9": {"Sun": "Aries", "Moon": "Capricorn", "Mars": "Taurus", "Mercury": "Leo",
                   "Jupiter": "Gemini", "Venus": "Aries", "Saturn": "Sagittarius"},
            "D12": {"Sun": "Taurus", "Moon": "Cancer", "Mars": "Aries", "Mercury": "Scorpio",
                    "Jupiter": "Scorpio", "Venus": "Libra", "Saturn": "Scorpio"},
            "D30": {"Sun": "Virgo", "Moon": "Capricorn", "Mars": "Libra", "Mercury": "Scorpio",
                    "Jupiter": "Aquarius", "Venus": "Gemini", "Saturn": "Libra"},
        },
        ayanamsa=24.1, ascendant=200.0, midheaven=110.0,
        birth_jd=2455000.85, sunrise_jd=2455000.30, sunset_jd=2455000.78,
        next_sunrise_jd=2455001.29, local_apparent_hours=22.4, hindu_day_jdn=2455000,
    ),
    # Day birth (second third), waxing Moon at her deep debilitation, Jupiter
    # at his deep exaltation, Venus and Saturn at their deep debilitation,
    # Mercury in his moolatrikona arc with no malefic beside him.
    "C": dict(
        longitudes={"Sun": 145.0, "Moon": 213.0, "Mars": 300.0, "Mercury": 167.0,
                    "Jupiter": 95.0, "Venus": 177.0, "Saturn": 20.0,
                    "Rahu": 250.0, "Ketu": 70.0},
        latitudes={"Mars": -1.5, "Mercury": 0.8, "Jupiter": 0.2, "Venus": -3.0, "Saturn": 1.1},
        varga_signs={
            "D2": {"Sun": "Cancer", "Moon": "Cancer", "Mars": "Leo", "Mercury": "Leo",
                   "Jupiter": "Cancer", "Venus": "Leo", "Saturn": "Cancer"},
            "D3": {"Sun": "Aries", "Moon": "Scorpio", "Mars": "Aquarius", "Mercury": "Capricorn",
                   "Jupiter": "Cancer", "Venus": "Taurus", "Saturn": "Sagittarius"},
            "D7": {"Sun": "Capricorn", "Moon": "Taurus", "Mars": "Aquarius", "Mercury": "Gemini",
                   "Jupiter": "Aquarius", "Venus": "Virgo", "Saturn": "Leo"},
            "D9": {"Sun": "Scorpio", "Moon": "Cancer", "Mars": "Libra", "Mercury": "Gemini",
                   "Jupiter": "Leo", "Venus": "Virgo", "Saturn": "Libra"},
            "D12": {"Sun": "Gemini", "Moon": "Sagittarius", "Mars": "Aquarius", "Mercury": "Pisces",
                    "Jupiter": "Virgo", "Venus": "Cancer", "Saturn": "Sagittarius"},
            "D30": {"Sun": "Libra", "Moon": "Taurus", "Mars": "Aries", "Mercury": "Pisces",
                    "Jupiter": "Virgo", "Venus": "Scorpio", "Saturn": "Gemini"},
        },
        ayanamsa=23.5, ascendant=330.0, midheaven=240.0,
        birth_jd=2440000.6, sunrise_jd=2440000.4, sunset_jd=2440000.9,
        next_sunrise_jd=2440001.4, local_apparent_hours=13.9, hindu_day_jdn=2440000,
    ),
}

_WORKED = {
    "A": {
        "Sun": (54.8333, 77.0000, 15.0000, 60.0000, 0.0000, 52.1667, 53.7500, 35.1667, 60.0000, 60.0000, 52.0950, 0.0000, 52.0950, 60.0000, 43.5000),
        "Moon": (37.6667, 129.0000, 15.0000, 60.0000, 15.0000, 32.6667, 6.2500, 24.8333, 0.0000, 0.0000, 5.4117, 0.0000, 24.8333, 51.4286, 1.3250),
        "Mars": (27.4667, 79.0000, 30.0000, 60.0000, 0.0000, 6.1333, 6.2500, 35.1667, 0.0000, 15.0000, 9.7750, -73.2124, 56.4583, 17.1429, 43.0750),
        "Mercury": (18.3333, 173.0000, 15.0000, 30.0000, 0.0000, 41.6667, 60.0000, 24.8333, 0.0000, 0.0000, 56.5133, 0.0000, 26.1358, 25.7143, 38.7500),
        "Jupiter": (40.0000, 81.0000, 15.0000, 15.0000, 15.0000, 40.0000, 53.7500, 24.8333, 60.0000, 30.0000, 30.5750, 0.0000, 42.1577, 34.2857, 51.1250),
        "Venus": (54.3333, 79.0000, 15.0000, 15.0000, 15.0000, 7.3333, 53.7500, 24.8333, 0.0000, 45.0000, 31.9250, 0.0000, 22.7148, 42.8571, 74.2750),
        "Saturn": (60.0000, 97.0000, 30.0000, 60.0000, 15.0000, 35.0000, 6.2500, 35.1667, 0.0000, 0.0000, 50.0783, 73.2124, 19.4888, 8.5714, 42.1250),
    },
    "B": {
        "Sun": (30.0000, 68.0000, 15.0000, 60.0000, 0.0000, 3.3333, 8.0000, 43.3333, 0.0000, 0.0000, 5.5033, 0.0000, 5.5033, 60.0000, -12.5000),
        "Moon": (5.6667, 134.0000, 30.0000, 30.0000, 0.0000, 40.0000, 52.0000, 43.3333, 60.0000, 0.0000, 57.8800, 0.0000, 43.3333, 51.4286, 68.3750),
        "Mars": (11.0000, 99.0000, 15.0000, 15.0000, 0.0000, 51.6667, 52.0000, 43.3333, 0.0000, 15.0000, 57.4533, 0.0000, 9.8336, 17.1429, -24.8750),
        "Mercury": (16.6667, 92.0000, 15.0000, 60.0000, 15.0000, 28.3333, 60.0000, 43.3333, 0.0000, 45.0000, 48.9967, 0.0000, 7.1824, 25.7143, 22.5000),
        "Jupiter": (49.0000, 58.0000, 30.0000, 30.0000, 15.0000, 36.0000, 8.0000, 16.6667, 60.0000, 0.0000, 43.9500, 0.0000, 50.9119, 34.2857, 19.7500),
        "Venus": (48.3333, 154.0000, 0.0000, 30.0000, 0.0000, 49.3333, 8.0000, 16.6667, 0.0000, 60.0000, 23.0500, 0.0000, 22.9940, 42.8571, 33.5000),
        "Saturn": (37.3333, 70.0000, 30.0000, 15.0000, 15.0000, 22.6667, 52.0000, 43.3333, 0.0000, 30.0000, 57.0533, 0.0000, 46.4751, 8.5714, 9.0000),
    },
    "C": {
        "Sun": (15.0000, 97.0000, 15.0000, 15.0000, 0.0000, 28.3333, 50.5000, 37.3333, 60.0000, 30.0000, 35.7500, 0.0000, 35.7500, 60.0000, -7.7500),
        "Moon": (0.0000, 184.0000, 30.0000, 15.0000, 0.0000, 9.0000, 9.5000, 22.6667, 0.0000, 0.0000, 54.7167, 0.0000, 22.6667, 51.4286, 62.0000),
        "Mars": (59.3333, 119.0000, 30.0000, 15.0000, 15.0000, 40.0000, 9.5000, 37.3333, 0.0000, 0.0000, 12.6167, 0.0000, 15.9752, 17.1429, 85.3750),
        "Mercury": (59.3333, 159.0000, 15.0000, 60.0000, 0.0000, 5.6667, 60.0000, 22.6667, 0.0000, 60.0000, 35.2500, 0.0000, 16.2674, 25.7143, 22.2500),
        "Jupiter": (60.0000, 85.0000, 15.0000, 30.0000, 15.0000, 18.3333, 50.5000, 22.6667, 60.0000, 45.0000, 56.2000, 0.0000, 25.7630, 34.2857, 1.8750),
        "Venus": (0.0000, 84.0000, 30.0000, 60.0000, 0.0000, 21.0000, 50.5000, 22.6667, 0.0000, 15.0000, 19.7500, 0.0000, 25.6451, 42.8571, 34.2500),
        "Saturn": (0.0000, 64.0000, 30.0000, 30.0000, 15.0000, 16.6667, 9.5000, 37.3333, 0.0000, 0.0000, 10.0500, 0.0000, 10.3625, 8.5714, 65.0000),
    },
}

# Bhavas 1-12: (bhava digbala, bhava drishti bala) in virupas, and the
# Bhavabala total in rupas (the lord's Shadbala + (dig + drishti) / 60).
_WORKED_BHAVAS = {
    "A": [
        (0.0000, 0.7000, 6.7353), (19.0000, 31.7625, 12.1062), (40.0000, 51.1250, 10.0179),
        (30.0000, 23.3750, 8.9066), (40.0000, 83.6875, 7.2657), (10.0000, 101.8625, 10.7432),
        (31.0000, 100.0875, 11.0497), (10.0000, 10.4625, 9.2059), (9.0000, 78.6500, 10.3396),
        (59.0000, 45.8250, 6.9513), (49.0000, 50.6250, 9.6774), (50.0000, 6.8375, 9.4464),
    ],
    "B": [
        (60.0000, 39.3750, 9.8018), (10.0000, 68.3750, 7.3322), (10.0000, 32.7500, 8.2386),
        (60.0000, 11.2500, 8.4614), (20.0000, 35.2500, 8.1947), (40.0000, 42.7500, 8.9052),
        (30.0000, 59.3750, 7.5155), (40.0000, 24.3750, 9.2185), (20.0000, -15.7500, 8.0663),
        (30.0000, 4.5000, 10.8419), (50.0000, 24.2500, 6.0071), (50.0000, 11.0000, 9.0121),
    ],
    "C": [
        (30.0000, 99.3750, 10.8166), (20.0000, 80.3750, 9.2775), (10.0000, 53.7500, 7.8236),
        (30.0000, 32.5000, 10.0608), (40.0000, 8.1250, 8.4851), (20.0000, -20.8750, 7.8507),
        (0.0000, -4.0000, 8.9525), (10.0000, 36.8750, 7.5424), (40.0000, 57.8750, 9.2359),
        (30.0000, 31.3750, 9.6833), (50.0000, 108.6250, 7.5851), (50.0000, 85.3750, 7.1976),
    ],
}


@pytest.mark.parametrize("chart", sorted(_CHARTS))
@pytest.mark.parametrize("planet", GRAHAS)
def test_worked_chart_every_sub_bala(chart, planet):
    got = st.shadbala_virupas(StrengthInputs(**_CHARTS[chart]))[planet]
    for column, want in zip(_COLUMNS, _WORKED[chart][planet]):
        assert getattr(got, column) == pytest.approx(want, abs=6e-5), column


@pytest.mark.parametrize("chart", sorted(_CHARTS))
def test_worked_chart_every_bhava(chart):
    inp = StrengthInputs(**_CHARTS[chart])
    shadbala = st.shadbala_virupas(inp)
    table = st.bhavabala_table(inp, shadbala)
    for house, (dig, drishti, total) in enumerate(_WORKED_BHAVAS[chart], start=1):
        got_dig, got_drishti = st.bhava_virupas(house, inp)
        assert got_dig == pytest.approx(dig, abs=6e-5), house
        assert got_drishti == pytest.approx(drishti, abs=6e-5), house
        row = table[house - 1]
        assert row.house_number == house
        assert row.bala_total == pytest.approx(total, abs=1.5e-3), house
        assert row.bhava_drik == pytest.approx(drishti / 60, abs=1e-3), house
        assert row.bala_total == pytest.approx(
            row.bhava_adhipathi_bala + (dig + drishti) / 60, abs=1.5e-3)


@pytest.mark.parametrize("chart", sorted(_CHARTS))
def test_worked_chart_served_rupas(chart):
    """The served fields are the virupa sums of the worked columns / 60."""
    table = st.shadbala_table(StrengthInputs(**_CHARTS[chart]))
    for planet in GRAHAS:
        w = dict(zip(_COLUMNS, _WORKED[chart][planet]))
        sthana = w["uchcha"] + w["saptavargaja"] + w["ojayugma"] + w["kendradi"] + w["drekkana"]
        kaala = (w["nathonnata"] + w["paksha"] + w["tribhaga"] + w["lords"]
                 + w["ayana"] + w["yuddha"])
        total = sum(w.values())
        row = table[planet]
        assert row.sthana_bala == pytest.approx(sthana / 60, abs=1e-3)
        assert row.kaala_bala == pytest.approx(kaala / 60, abs=1e-3)
        assert row.dig_bala == pytest.approx(w["dig"] / 60, abs=1e-3)
        assert row.cheshta_bala == pytest.approx(w["cheshta"] / 60, abs=1e-3)
        assert row.naisargika_bala == pytest.approx(w["naisargika"] / 60, abs=1e-3)
        assert row.drik_bala == pytest.approx(w["drik"] / 60, abs=1e-3)
        assert row.total_bala == pytest.approx(total / 60, abs=1e-3)
        assert row.minimum_bala == st.SHADBALA_MINIMUMS[planet]
        assert row.is_below_minimum is (row.total_bala < row.minimum_bala)


class TestChartAWorkedSun:
    """Chart A's Sun, step by step (sidereal Aries 25 deg 30 min)."""

    inp = StrengthInputs(**_CHARTS["A"])

    def test_uchcha(self):
        # 25.5 - 190 = -164.5 -> 195.5 > 180 -> 164.5; / 3 = 54.8333
        assert st._uchcha_bala("Sun", 25.5) == pytest.approx(164.5 / 3)

    def test_saptavargaja(self):
        # D1 Aries (Mars: friend + temporary enemy, Mars 7th) neutral 10;
        # D2 Cancer (Moon: friend + Moon 4th) great friend 20; D3 Sagittarius
        # (Jupiter: friend + Jupiter 6th) neutral 10; D7 Virgo (Mercury:
        # neutral + Mercury 2nd) friend 15; D9 Scorpio (Mars) neutral 10; D12
        # Aquarius (Saturn: enemy + Saturn 7th) great enemy 2; D30 Libra
        # (Venus: enemy + Venus 12th) neutral 10. Sum 77.
        assert st._saptavargaja_bala("Sun", self.inp) == 77.0

    def test_dig(self):
        # nadir = meridian 2 + 180 = 182; 25.5 - 182 -> 203.5 -> 156.5; / 3
        assert st._dig_bala("Sun", self.inp) == pytest.approx(156.5 / 3)

    def test_kaala(self):
        # nathonnata: 10.75 h from midnight = 26.875 ghatis; night value
        # 2 x (30 - 26.875) = 6.25; the Sun takes 60 - 6.25 = 53.75.
        assert st._nathonnata_bala("Sun", self.inp) == pytest.approx(53.75)
        # paksha: Moon 100 - Sun 25.5 = 74.5; / 3 = 24.8333; the Sun is a
        # malefic: 60 - 24.8333 = 35.1667.
        assert st._paksha_bala("Sun", self.inp) == pytest.approx(60 - 74.5 / 3)
        # tribhaga: (0.31 - 0.05) / 0.5 = 0.52 of the day -> second third.
        assert st._tribhaga_bala("Sun", self.inp) == 60.0
        # ahargana = 714,402,296,628 + (2,460,000 - 588,466) = 714,404,168,162;
        # by 7 remainder 6 -> Friday (Venus); by 360 quotient 1,984,456,022,
        # x3+1 = 5,953,368,067, by 7 remainder 3 -> Mars; by 30 quotient
        # 23,813,472,272, x2+1 = 47,626,944,545, by 7 remainder 5 -> Jupiter;
        # hora: 0.26 day x 24 = 6.24 -> the 7th hora, Venus + 6 x 5 places ->
        # the Sun. So the Sun takes the hora's 60.
        assert st.ahargana(self.inp) == 714_404_168_162
        assert (st.weekday_lord(self.inp), st.year_lord(self.inp),
                st.month_lord(self.inp), st.hora_lord(self.inp)) == (
                    "Venus", "Mars", "Jupiter", "Sun")
        assert st._lord_balas("Sun", self.inp) == 60.0
        # ayana: sayana 25.5 + 23.85 = 49.35 (north); khanda 45 + 33 x 19.35
        # / 30 = 66.285; the Sun adds in the north: (90 + 66.285) / 3.
        assert st._ayana_bala("Sun", self.inp) == pytest.approx(156.285 / 3)

    def test_cheshta_is_ayana(self):
        assert st._cheshta_bala("Sun", self.inp) == st._ayana_bala("Sun", self.inp)

    def test_drik(self):
        # Moon (waxing, benefic) at 285.5 deg behind: s9 r15.5 -> 15 - 7.75 =
        # 7.25, + 7.25/4. Mars (malefic) at 185.1: Mars s6 = 60, - 15. Mercury
        # at 345.5: nothing. Jupiter at 230.5: Jupiter s7 = 45 + 10.25 =
        # 55.25, + 55.25/4 + 55.25. Venus at 45.5: s1 = 7.75, + 7.75/4.
        # Saturn (malefic) at 185.5: s6 = 60 - 2.75 = 57.25, - 57.25/4.
        want = 7.25 / 4 - 15 + 55.25 / 4 + 55.25 + 7.75 / 4 - 57.25 / 4
        assert st._aspect_strength(25.5, self.inp.longitudes) == pytest.approx(want)

    def test_war(self):
        # Mars 200.4 and Saturn 200.0 are 0.4 apart; Saturn's latitude 2.1 is
        # north of Mars's 1.2, so Saturn wins the difference of their totals.
        assert st.yuddha_pairs(self.inp) == [("Saturn", "Mars")]


def test_required_minimums_are_bphs():
    """BPHS 27.32-33: 390, 360, 300, 420, 390, 330, 300 virupas."""
    virupas = [390, 360, 300, 420, 390, 330, 300]
    assert st.SHADBALA_MINIMUMS == {g: v / 60 for g, v in zip(GRAHAS, virupas)}


def test_naisargika_is_sevenths():
    """BPHS 27.14: 1/7 of a rupa times 1..7 from Saturn up to the Sun."""
    inp = StrengthInputs(**_CHARTS["A"])
    got = st.shadbala_virupas(inp)
    for k, planet in enumerate(["Saturn", "Mars", "Mercury", "Jupiter", "Venus", "Moon", "Sun"], 1):
        assert got[planet].naisargika == pytest.approx(60 * k / 7)
    assert math.isclose(sum(got[p].naisargika for p in GRAHAS), 240.0)


# ---------------------------------------------------------------------------
# Reading the inputs from a real chart.
# ---------------------------------------------------------------------------

def _real_snapshot(date, time, lat, lon, tz):
    import datetime as dt

    from bphs_core.chart import Chart, PersonalData
    return Chart(PersonalData("synthetic", dt.datetime.fromisoformat(date),
                              dt.time.fromisoformat(time), "Synthetic", lat, lon, tz)).snapshot()


def test_apparent_time_is_the_suns_hour_angle():
    """With the ephemeris directly: local apparent time is 12 h plus the Sun's
    hour angle (local sidereal time less the Sun's right ascension). Early
    November, when the equation of time is near its +16 minute peak, so
    serving mean time instead would miss by a quarter of an hour."""
    import swisseph as swe
    snap = _real_snapshot("2021-11-03", "15:40:00", 13.0, 77.6, 5.5)
    inp = st.strength_inputs(snap)
    ra = swe.calc_ut(snap.jd, swe.SUN, swe.FLG_EQUATORIAL)[0][0]
    hour_angle = (swe.sidtime(snap.jd) * 15.0 + 77.6 - ra) % 360.0
    want = (12.0 + hour_angle / 15.0) % 24.0
    assert abs(inp.local_apparent_hours - want) < 0.01   # under 36 seconds
    mean_time = ((snap.jd + 0.5) % 1.0) * 24.0 + 77.6 / 15.0
    assert abs(inp.local_apparent_hours - mean_time) > 0.2


def test_day_frame_comes_from_the_birth_place():
    """Sunrise at or before the birth, the next sunrise after it, and the
    sunset between them; a 15:40 birth in Bengaluru is a day birth."""
    snap = _real_snapshot("2021-11-03", "15:40:00", 13.0, 77.6, 5.5)
    inp = st.strength_inputs(snap)
    assert inp.sunrise_jd <= inp.birth_jd < inp.sunset_jd < inp.next_sunrise_jd
    assert 0.9 < inp.next_sunrise_jd - inp.sunrise_jd < 1.1
    assert st.is_day_birth(inp)


@pytest.mark.parametrize("events", [
    # the only sunset found falls after the next sunrise (a polar night edge)
    {"rise": [-1.25, -0.25, 0.75], "set": [0.9]},
    # no sunrise at or before the birth within two days
    {"rise": [0.25, 1.25], "set": [0.6]},
])
def test_no_enclosing_day_frame_is_undefined(monkeypatch, events):
    """BPHS 27.12-13 need a sunrise-sunset-sunrise frame around the birth;
    without one the classical value does not exist and nothing is served."""
    snap = _real_snapshot("2021-11-03", "15:40:00", 13.0, 77.6, 5.5)
    birth = snap.jd

    def fake(jd, rsmi, geopos):
        key = "rise" if rsmi == st.utils.RISE_FLAGS else "set"
        return next(birth + e for e in events[key] if birth + e > jd)

    monkeypatch.setattr(st, "_next_solar_event", fake)
    with pytest.raises(st.ShadbalaUndefinedError):
        st.strength_inputs(snap)


@pytest.mark.parametrize("birth", [
    ("2021-11-03", "15:40:00", 13.0, 77.6, 5.5),
    ("1984-09-21", "03:15:00", 51.5, -0.1, 1.0),
    ("1991-03-11", "18:05:00", -33.9, 151.2, 11.0),
])
def test_ascendant_and_meridian_in_the_served_frame(birth):
    """Dig bala and the bhava points read the ascendant and the meridian in
    the frame the grahas and the lagna are served in (utils.sidereal_houses,
    as Chart._compute takes the lagna), never tropical points less the
    ayanamsa, which would leave the nutation in longitude in them."""
    from bphs_core import utils
    snap = _real_snapshot(*birth)
    inp = st.strength_inputs(snap)
    _, ascmc = utils.sidereal_houses(snap.jd, birth[2], birth[3], b"P")
    assert inp.ascendant == ascmc[0] and inp.midheaven == ascmc[1]
    assert SIGNS[int(inp.ascendant // 30)] == snap.lagna


# ---------------------------------------------------------------------------
# Real births through strength_inputs: what the chart hands the computation.
# Each expectation is worked from the rule and the date, not read back from
# the module. Positions are the Swiss ephemeris's, to tolerances the Moshier
# runtime also meets.
# ---------------------------------------------------------------------------

def _bphs_varga_sign(varga, longitude):
    """The sign of a sidereal *longitude* in one varga, by BPHS chapter 6."""
    s = int(longitude // 30.0) % 12
    d = longitude % 30.0
    odd = s % 2 == 0  # Aries, index 0, is the first (odd) sign
    if varga == "D2":   # 6.5-6: odd signs Leo then Cancer, even signs reversed
        return "Leo" if (d < 15.0) == odd else "Cancer"
    if varga == "D3":   # 6.7-8: the sign, its 5th, its 9th
        return SIGNS[(s + 4 * int(d // 10.0)) % 12]
    if varga == "D7":   # 6.10: odd signs from the sign, even from its 7th
        return SIGNS[(s + (0 if odd else 6) + int(d * 7 // 30.0)) % 12]
    if varga == "D9":   # 6.12: movable from the sign, fixed from its 9th, dual from its 5th
        return SIGNS[(s + (0, 8, 4)[s % 3] + int(d * 9 // 30.0)) % 12]
    if varga == "D12":  # 6.15: from the sign
        return SIGNS[(s + int(d // 2.5)) % 12]
    if varga == "D30":  # 6.27: odd Mars 5, Saturn 5, Jupiter 8, Mercury 7, Venus 5; even reversed
        bands = ([(5, "Aries"), (10, "Aquarius"), (18, "Sagittarius"), (25, "Gemini"),
                  (30, "Libra")] if odd else
                 [(5, "Taurus"), (12, "Virgo"), (20, "Pisces"), (25, "Capricorn"),
                  (30, "Scorpio")])
        return next(sign for end, sign in bands if d < end)
    raise AssertionError(varga)


@pytest.mark.parametrize("birth", [
    ("1962-02-04", "23:40:00", 28.6, 77.2, 5.5),
    ("1991-03-11", "18:05:00", -33.9, 151.2, 11.0),
    ("2019-06-20", "15:30:00", 51.5, -0.1, 1.0),
])
def test_saptavarga_signs_are_bphs_chapter_6_of_the_longitude(birth):
    """Saptavargaja bala (BPHS 27.2-4) reads each graha's sign in the hora,
    drekkana, saptamsa, navamsa, dwadasamsa and trimsamsa. Every one is
    worked here from the graha's sidereal longitude by BPHS chapter 6, so a
    varga read from the wrong divisional chart fails."""
    inp = st.strength_inputs(_real_snapshot(*birth))
    assert set(inp.varga_signs) == set(st.SAPTAVARGA[1:])
    for varga in st.SAPTAVARGA[1:]:
        for graha in GRAHAS:
            want = _bphs_varga_sign(varga, inp.longitudes[graha])
            assert inp.varga_signs[varga][graha] == want, (varga, graha)


@pytest.mark.parametrize("birth,jdn,lord", [
    # 04:00 IST on Monday 3 January 2000, before the 07:18 IST sunrise: the
    # Hindu day is still Sunday 2 January, JDN 2451546.
    (("2000-01-03", "04:00:00", 28.6, 77.2, 5.5), 2451546, "Sun"),
    # 10:00 JST on Monday 3 January 2000. The sunrise that opened the day fell
    # at 21:56 UT on Sunday 2 January; its local date (UTC+9) is Monday,
    # JDN 2451547.
    (("2000-01-03", "10:00:00", 35.7, 139.7, 9.0), 2451547, "Moon"),
])
def test_hindu_day_is_the_local_date_of_the_opening_sunrise(birth, jdn, lord):
    """The day lord is the lord of the day opened by the sunrise at or before
    the birth (BPHS 27.13), on the local calendar of the birth place."""
    inp = st.strength_inputs(_real_snapshot(*birth))
    assert inp.hindu_day_jdn == jdn
    assert st.weekday_lord(inp) == lord


@pytest.mark.parametrize("birth,arcs,latitudes,wars", [
    # The great conjunction in Capricorn. Mercury and Venus are 0.26 deg
    # apart; Mercury at +3.50 is north of Venus at -1.30 and wins. Three
    # further pairs lie within five degrees but past one: no war.
    (("1962-02-04", "23:40:00", 28.6, 77.2, 5.5),
     {("Mercury", "Venus"): 0.256, ("Mars", "Saturn"): 1.603,
      ("Mercury", "Jupiter"): 1.345, ("Jupiter", "Venus"): 1.090},
     {"Mars": -0.995, "Mercury": 3.502, "Jupiter": -0.689, "Venus": -1.296,
      "Saturn": -0.367},
     [("Mercury", "Venus")]),
    # Jupiter and Saturn 0.003 deg apart; Saturn at -0.379 is north of
    # Jupiter at -0.480.
    (("2020-12-21", "23:00:00", 28.6, 77.2, 5.5),
     {("Jupiter", "Saturn"): 0.003},
     {"Jupiter": -0.480, "Saturn": -0.379},
     [("Saturn", "Jupiter")]),
    # Mars and Saturn 0.035 deg apart; Saturn at -0.954 is north of Mars at
    # -1.259.
    (("2022-04-05", "06:00:00", 28.6, 77.2, 5.5),
     {("Mars", "Saturn"): 0.035},
     {"Mars": -1.259, "Saturn": -0.954},
     [("Saturn", "Mars")]),
    # Three weeks before their conjunction Jupiter and Saturn are 2.12 deg
    # apart: no war.
    (("2020-12-02", "12:00:00", 28.6, 77.2, 5.5),
     {("Jupiter", "Saturn"): 2.124},
     {"Jupiter": -0.465, "Saturn": -0.362},
     []),
])
def test_real_planetary_wars(birth, arcs, latitudes, wars):
    """Surya Siddhanta 7.18-21 on real skies: two star grahas less than one
    degree apart in longitude are at war, and the one with the more northern
    geocentric ecliptic latitude is the victor. BPHS 27.20 then moves the
    difference of their Shadbala from the vanquished to the victor."""
    inp = st.strength_inputs(_real_snapshot(*birth))
    for (a, b), arc in arcs.items():
        assert st._arc(inp.longitudes[a], inp.longitudes[b]) == pytest.approx(arc, abs=0.01)
    for graha, latitude in latitudes.items():
        assert inp.latitudes[graha] == pytest.approx(latitude, abs=0.01), graha
    assert st.yuddha_pairs(inp) == wars
    table = st.shadbala_virupas(inp)
    for victor, vanquished in wars:
        assert table[victor].yuddha > 0.0 > table[vanquished].yuddha
        assert table[victor].yuddha == pytest.approx(-table[vanquished].yuddha)


def test_hora_counts_24_equal_parts_on_a_long_day():
    """BPHS 27.13 and its note: 24 equal horas from sunrise to the next
    sunrise. London, Thursday 20 June 2019, 15:30 BST (14:30 UT): sunrise
    03:50 UT and the next one 03:50 UT, so each hora is an hour and the birth,
    10 h 40 min after sunrise, falls in the 11th (k = 10). Thursday's horas
    run Jupiter, Mars, Sun, Venus, Mercury, Moon, Saturn and round again, so
    the 11th is Venus's. Twelve horas of daylight (sunset 20:14 UT, 82
    minutes each) would put it in the 8th, Jupiter's."""
    inp = st.strength_inputs(_real_snapshot("2019-06-20", "15:30:00", 51.5, -0.1, 1.0))
    assert st.weekday_lord(inp) == "Jupiter"
    assert st.hora_lord(inp) == "Venus"


def test_ayana_reads_the_sayana_longitude_of_a_real_birth():
    """BPHS 27.15-17 measure ayana bala on the sayana longitude. Delhi,
    5 April 2022, 06:00 IST: the sayana Sun is at 15.22 deg (Aries, north of
    the equator). Bhuja 15.22, kranti 45 x 15.22 / 30 = 22.83, and the Sun
    adds it: (90 + 22.83) / 3 = 37.61 virupas, which is also his cheshta bala
    (BPHS 27.18). Read on the sidereal longitude instead, 351.05 deg, he
    would be south of it, at 25.5."""
    inp = st.strength_inputs(_real_snapshot("2022-04-05", "06:00:00", 28.6, 77.2, 5.5))
    assert (inp.longitudes["Sun"] + inp.ayanamsa) % 360.0 == pytest.approx(15.22, abs=0.02)
    assert st._ayana_bala("Sun", inp) == pytest.approx(37.61, abs=0.02)
    assert st._cheshta_bala("Sun", inp) == pytest.approx(37.61, abs=0.02)


@pytest.mark.parametrize("birth", [
    ("1947-12-22", "12:00:00", -59.4, 0.0, 0.0),   # midsummer at 59.4 S
    ("2019-06-20", "15:30:00", 51.5, -0.1, 1.0),   # midsummer at 51.5 N
    ("2019-03-20", "15:30:00", 51.5, -0.1, 0.0),   # equinox: sunrise 2 min earlier each day
    ("1962-02-04", "23:40:00", 28.6, 77.2, 5.5),   # a night birth
])
def test_day_frame_puts_the_suns_centre_on_the_horizon(birth):
    """The Hindu sunrise and sunset (utils.RISE_FLAGS / SET_FLAGS) are the
    instants the centre of the Sun's disc stands on the horizon, refraction
    ignored. Checked by the Sun's own altitude at each of the three events,
    so neither the search nor the day count can hide a wrong time:
    swe.rise_trans started a day before the event returned the sunrise at
    59.4 S 226 s late (0.30 deg of altitude) and at 51.5 N 14 s late
    (0.03 deg), and a next sunrise taken as one day after this one would be
    2 min late at the equinox (0.36 deg)."""
    import swisseph as swe
    inp = st.strength_inputs(_real_snapshot(*birth))
    geopos = (birth[3], birth[2], 0.0)
    for name in ("sunrise_jd", "sunset_jd", "next_sunrise_jd"):
        jd = getattr(inp, name)
        lon, _, distance = swe.calc_ut(jd, swe.SUN, swe.FLG_SWIEPH)[0][:3]
        altitude = swe.azalt(jd, swe.ECL2HOR, geopos, 0.0, 0.0, (lon, 0.0, distance))[1]
        assert abs(altitude) < 0.001, (name, altitude)
    assert inp.sunrise_jd <= inp.birth_jd < inp.next_sunrise_jd
