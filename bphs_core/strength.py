"""Shadbala, Bhavabala and Ashtakavarga.

Shadbala and Bhavabala follow Brihat Parashara Hora Shastra (BPHS) chapter 27
in R. Santhanam's translation, wherever BPHS gives a rule or a number, except
BPHS 27.30-31 (a rupa added or taken for the grahas occupying a bhava, and 15
virupas by the rising type of its sign), which is not applied: Bhavabala is
the three components of BPHS 27.26-29 (see bhavabala_table). Where
BPHS is silent, the method is the Surya Siddhanta's (Burgess translation): the
ahargana that fixes the year and month lords, the mean longitudes and
sighroccas the cheshta kendra needs, and the rule that decides a planetary
war. Every rule below cites its verse. This module computes everything
itself; it never calls the dependency's own strength module.

Units: every sub-bala is computed in virupas (shashtiamsas); the served
fields are rupas (virupas / 60), rounded to three places.

The six served components, and where each sub-bala lands:

* ``sthana_bala``     uchcha + saptavargaja + ojayugma + kendradi + drekkana
                      (BPHS 27.1-6)
* ``dig_bala``        BPHS 27.7
* ``kaala_bala``      nathonnata + paksha + tribhaga + the lords of the
                      year, month, day and hora + ayana + yuddha
                      (BPHS 27.8-13, 27.15-17, 27.20)
* ``cheshta_bala``    BPHS 27.18 and 27.24-25 (the cheshta-kendra method)
* ``naisargika_bala`` BPHS 27.14
* ``drik_bala``       BPHS 27.19, each aspect valued by BPHS 26.6-12

Every sub-bala except yuddha and drik is bounded by construction at its
classical range (0 to 60 virupas; saptavargaja 0 to 315): every arc is
reduced past six signs before it is divided by three. Drik bala and yuddha
bala carry a sign by definition (malefic aspects deduct; the vanquished graha
in a war loses), and BPHS states no ceiling for either.
"""

import logging
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping

import swisseph as swe

from . import utils
from .chart import ChartSnapshot

logger = logging.getLogger(__name__)

SHADBALA_PLANETS: tuple[str, ...] = (
    "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn",
)

# Required Shadbala in rupas, BPHS 27.32-33: 390, 360, 300, 420, 390, 330 and
# 300 virupas for the Sun through Saturn, divided by 60.
SHADBALA_MINIMUMS: dict[str, float] = {
    "Sun": 6.5, "Moon": 6.0, "Mars": 5.0,
    "Mercury": 7.0, "Jupiter": 6.5, "Venus": 5.5, "Saturn": 5.0,
}

# Naisargika bala, BPHS 27.14: one rupa divided by seven, multiplied by 1 to 7
# for Saturn, Mars, Mercury, Jupiter, Venus, the Moon and the Sun.
_NAISARGIKA_SEVENTHS: dict[str, int] = {
    "Saturn": 1, "Mars": 2, "Mercury": 3, "Jupiter": 4,
    "Venus": 5, "Moon": 6, "Sun": 7,
}

# Deep debilitation points (sidereal degrees). BPHS 3.49-50: deep exaltation
# Sun 10 Aries, Moon 3 Taurus, Mars 28 Capricorn, Mercury 15 Virgo, Jupiter 5
# Cancer, Venus 27 Pisces, Saturn 20 Libra; the debilitation point is the same
# degree of the seventh sign.
_DEBILITATION_POINT: dict[str, float] = {
    "Sun": 190.0, "Moon": 213.0, "Mars": 118.0, "Mercury": 345.0,
    "Jupiter": 275.0, "Venus": 177.0, "Saturn": 20.0,
}

# Saptavargaja bala, BPHS 27.2-4 (Santhanam): virupas per varga for the
# graha's state there. The seven vargas are the rasi, hora, drekkana,
# saptamsa, navamsa, dwadasamsa and trimsamsa.
_SAPTAVARGAJA_POINTS: dict[str, float] = {
    "moolatrikona": 45.0, "own": 30.0, "great friend": 20.0, "friend": 15.0,
    "neutral": 10.0, "enemy": 4.0, "great enemy": 2.0,
}
SAPTAVARGA: tuple[str, ...] = ("D1", "D2", "D3", "D7", "D9", "D12", "D30")
_VARGA_FIELD: dict[str, str] = {
    "D2": "hora_chart", "D3": "drekkana_chart", "D7": "saptamsa_chart",
    "D9": "navamsa_chart", "D12": "dwadasamsa_chart", "D30": "trimshamsa_chart",
}

# Temporary friendship, BPHS 3.56: a graha in the 2nd, 3rd, 4th, 10th, 11th or
# 12th sign from another is its temporary friend; anywhere else, its enemy.
_TEMPORARY_FRIEND_PLACES = frozenset({2, 3, 4, 10, 11, 12})

# Drekkana bala, BPHS 27.6: a quarter rupa to a male graha in the first
# decanate of a sign, a female in the second and a neuter in the third. Sex
# of the grahas, BPHS 3.19: the Sun, Mars and Jupiter male; the Moon and
# Venus female; Mercury and Saturn neuter. Values: the decanate index (0-2).
_DREKKANA_OF: dict[str, int] = {
    "Sun": 0, "Mars": 0, "Jupiter": 0,
    "Moon": 1, "Venus": 1,
    "Mercury": 2, "Saturn": 2,
}
# Ojayugma bala, BPHS 27.4 (second half): the Moon and Venus gain in even
# signs, the others in odd signs.
_EVEN_SIGN_GRAHAS = frozenset({"Moon", "Venus"})

# Natural benefic and malefic grahas, BPHS 3.11: the Sun, Saturn, Mars, the
# waning Moon, Rahu and Ketu are malefic; the rest benefic; Mercury becomes
# malefic when he joins a malefic.
_FIXED_MALEFICS = frozenset({"Sun", "Mars", "Saturn"})
_SHADOW_GRAHAS = frozenset({"Rahu", "Ketu"})

# Weekday order, which is also the order of the lords counted from Sunday.
_WEEKDAY_LORDS: tuple[str, ...] = (
    "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn",
)

# The five star grahas, the only ones that meet in planetary war (Surya
# Siddhanta 7.18).
_STAR_GRAHAS: tuple[str, ...] = ("Mars", "Mercury", "Jupiter", "Venus", "Saturn")

# Surya Siddhanta 1.29-34 and 1.37 (Burgess): revolutions in a Mahayuga of
# 4,320,000 years, and the civil days in it. Mercury's and Venus's entries are
# their sighroccas (conjunctions); their mean longitude is the mean Sun's.
_SS_CIVIL_DAYS = 1_577_917_828
_SS_REVOLUTIONS: dict[str, int] = {
    "Sun": 4_320_000,
    "Mars": 2_296_832,
    "Jupiter": 364_220,
    "Saturn": 146_568,
    "Mercury sighrocca": 17_937_060,
    "Venus sighrocca": 7_022_376,
}
# Surya Siddhanta 1.57: the mean grahas stand together at the first point of
# Aries at midnight on the meridian of Ujjain that begins the Kali Yuga,
# Julian 18 February 3102 BCE. JD 588465.5 is 00:00 UT that day; Ujjain lies
# 75 deg 46 min east, so its midnight falls 75.7667/360 of a day earlier in UT.
_UJJAIN_LONGITUDE = 75.0 + 46.0 / 60.0
_KALI_EPOCH_JD_UT = 588465.5 - _UJJAIN_LONGITUDE / 360.0
# Ahargana (days since creation) of the first civil day of the Kali Yuga,
# 18 February 3102 BCE (JDN 588466), counted as Santhanam's translator's note
# to BPHS 27.13 counts it: 1 January 1860 is day 714,404,108,573, and a
# remainder of 1 on division by 7 is Sunday. Creation to the Kali Yuga is
# 1,955,880,000 years (Surya Siddhanta 1.21-24) = 452.75 Mahayugas of
# 1,577,917,828 days = 714,402,296,627 days.
_KALI_DAY_ONE_JDN = 588466
_AHARGANA_AT_KALI_DAY_ONE = 714_402_296_628


class ShadbalaUndefinedError(ValueError):
    """The classical Shadbala cannot be computed for this birth.

    Raised when the Sun does not both rise and set at the birth place around
    the birth (polar day or night): tribhaga, hora and vara bala are defined
    from sunrise and sunset (BPHS 27.12-13), so no classical value exists.
    """


@dataclass
class ShadbalaResult:
    planet: str
    sthana_bala: float
    dig_bala: float
    kaala_bala: float
    cheshta_bala: float
    naisargika_bala: float
    drik_bala: float
    total_bala: float
    minimum_bala: float
    is_below_minimum: bool


@dataclass
class BhavabalaResult:
    house_number: int
    bala_total: float
    bhava_adhipathi_bala: float
    bhava_drik: float
    rank: str


@dataclass(frozen=True)
class StrengthInputs:
    """Everything the classical computation reads, as plain numbers.

    ``longitudes`` are sidereal (Lahiri), for the seven grahas and both
    nodes. ``latitudes`` are geocentric ecliptic latitudes of the five star
    grahas, read only to decide a planetary war. ``varga_signs`` maps each
    saptavarga label except D1 to graha -> sign. ``ascendant`` and
    ``midheaven`` are sidereal. Julian Days are UT. ``local_apparent_hours``
    is the local apparent solar time of birth. ``hindu_day_jdn`` is the
    Julian Day Number of the local civil date of the sunrise that opens the
    day of birth.
    """
    longitudes: Mapping[str, float]
    latitudes: Mapping[str, float]
    varga_signs: Mapping[str, Mapping[str, str]]
    ayanamsa: float
    ascendant: float
    midheaven: float
    birth_jd: float
    sunrise_jd: float
    sunset_jd: float
    next_sunrise_jd: float
    local_apparent_hours: float
    hindu_day_jdn: int


# ---------------------------------------------------------------------------
# Arithmetic helpers
# ---------------------------------------------------------------------------

def _arc(a: float, b: float) -> float:
    """The arc a - b in degrees, reduced past six signs: 'if the result
    exceeds six signs, deduct it from twelve' (BPHS 27.1, 27.7, 27.10)."""
    d = (a - b) % 360.0
    return 360.0 - d if d > 180.0 else d


def _sign_index(longitude: float) -> int:
    return int((longitude % 360.0) // 30.0)


def _sign(longitude: float) -> str:
    return utils.SIGNS[_sign_index(longitude)]


def _moon_is_waxing(longitudes: Mapping[str, float]) -> bool:
    """Waxing (shukla) Moon: elongation from the Sun in the open interval
    (0, 180). BPHS 3.11 makes the waning Moon a malefic."""
    elongation = (longitudes["Moon"] - longitudes["Sun"]) % 360.0
    return 0.0 < elongation < 180.0


def is_benefic(graha: str, longitudes: Mapping[str, float]) -> bool:
    """Natural benefic per BPHS 3.11, as paksha and drik bala read it.

    Jupiter and Venus are benefic; the Sun, Mars, Saturn, Rahu and Ketu
    malefic. The Moon is benefic while waxing. Mercury is benefic unless he
    joins, by sharing the rasi sign, the Sun, Mars, Saturn, the waning Moon,
    Rahu or Ketu.
    """
    if graha in _FIXED_MALEFICS or graha in _SHADOW_GRAHAS:
        return False
    if graha == "Moon":
        return _moon_is_waxing(longitudes)
    if graha == "Mercury":
        mercury_sign = _sign_index(longitudes["Mercury"])
        for other, lon in longitudes.items():
            if other == "Mercury" or _sign_index(lon) != mercury_sign:
                continue
            if other in _FIXED_MALEFICS or other in _SHADOW_GRAHAS:
                return False
            if other == "Moon" and not _moon_is_waxing(longitudes):
                return False
    return True


# ---------------------------------------------------------------------------
# Sphuta drishti, BPHS 26.6-12
# ---------------------------------------------------------------------------

def sphuta_drishti(aspecting: str, angle: float) -> float:
    """Aspect value in virupas that *aspecting* casts across *angle* degrees.

    *angle* is the aspected point's longitude less the aspecting graha's.
    Write it as s whole signs and r degrees.

    General rule, BPHS 26.6-9: s = 0 gives nothing; s = 1 half the degrees;
    s = 2 the degrees plus 15; s = 3 four signs less the angle, halved, plus
    30; s = 4 five signs less the angle; s = 5 the degrees doubled; s = 6 to
    9 ten signs less the angle, halved; s = 10 and 11 nothing.

    Saturn, BPHS 26.10: s = 1 and s = 9 the elapsed and the remaining degrees
    doubled; s = 2 sixty less half the degrees; s = 8 the degrees plus 30.
    Mars, BPHS 26.11: s = 3 and s = 7 sixty less the degrees; s = 2 one and a
    half times the degrees plus 15; s = 6 always one rupa (60).
    Jupiter, BPHS 26.12: s = 3 and s = 7 half the degrees plus 45; s = 4 and
    s = 8 sixty less twice the degrees.

    Every value lies in [0, 60]. Saturn's peaks are his 3rd and 10th aspects
    (60 and 270 degrees), Mars's his 4th and 8th (90, and 180 to 210),
    Jupiter's his 5th and 9th (120 and 240).
    """
    a = angle % 360.0
    s = int(a // 30.0)
    r = a - 30.0 * s
    if aspecting == "Saturn":
        if s == 1:
            return 2.0 * r
        if s == 2:
            return 60.0 - r / 2.0
        if s == 8:
            return 30.0 + r
        if s == 9:
            return 2.0 * (30.0 - r)
    elif aspecting == "Mars":
        if s == 2:
            return 15.0 + 1.5 * r
        if s in (3, 7):
            return 60.0 - r
        if s == 6:
            return 60.0
    elif aspecting == "Jupiter":
        if s in (3, 7):
            return 45.0 + r / 2.0
        if s in (4, 8):
            return 60.0 - 2.0 * r
    if s == 1:
        return r / 2.0
    if s == 2:
        return r + 15.0
    if s == 3:
        return (120.0 - a) / 2.0 + 30.0
    if s == 4:
        return 150.0 - a
    if s == 5:
        return 2.0 * r
    if 6 <= s <= 9:
        return (300.0 - a) / 2.0
    return 0.0


def _aspect_strength(point: float, longitudes: Mapping[str, float]) -> float:
    """Drik bala of a graha (BPHS 27.19) or a bhava point (BPHS 27.29), in
    virupas: add a quarter of each benefic's drishti, deduct a quarter of
    each malefic's, and add on top the entire drishti of Mercury and of
    Jupiter. A graha's drishti on its own longitude is nil (an angle of 0,
    BPHS 26.6), so it needs no exclusion."""
    total = 0.0
    for aspecting in SHADBALA_PLANETS:
        value = sphuta_drishti(aspecting, point - longitudes[aspecting])
        quarter = value / 4.0
        total += quarter if is_benefic(aspecting, longitudes) else -quarter
        if aspecting in ("Mercury", "Jupiter"):
            total += value
    return total


# ---------------------------------------------------------------------------
# Sthana bala, BPHS 27.1-6
# ---------------------------------------------------------------------------

def _uchcha_bala(planet: str, longitude: float) -> float:
    """BPHS 27.1: the arc from the deep debilitation point, reduced past six
    signs, in degrees divided by three."""
    return _arc(longitude, _DEBILITATION_POINT[planet]) / 3.0


def compound_relationship(planet: str, other: str,
                          longitudes: Mapping[str, float]) -> str:
    """The five-fold relationship, BPHS 3.55-58: the natural relationship
    combined with the temporary one read from the rasi chart."""
    if other in utils._FRIENDLY[planet]:
        natural = 1
    elif other in utils._ENEMY[planet]:
        natural = -1
    else:
        natural = 0
    place = (_sign_index(longitudes[other]) - _sign_index(longitudes[planet])) % 12 + 1
    temporary = 1 if place in _TEMPORARY_FRIEND_PLACES else -1
    return {
        2: "great friend", 1: "friend", 0: "neutral",
        -1: "enemy", -2: "great enemy",
    }[natural + temporary]


def varga_state(planet: str, sign: str, rasi_longitude: float | None,
                longitudes: Mapping[str, float]) -> str:
    """The graha's state in one varga, for saptavargaja bala (BPHS 27.2-4).

    Moolatrikona is judged by the degree arcs of BPHS 3.51-54 in the rasi
    chart (pass the rasi longitude) and by sign in every other varga (pass
    None): BPHS 27.2-4 applies one scale to all seven vargas. The arcs are
    utils.MOOLATRIKONA_ARC, the table the served rasi dignity reads.
    Exaltation and debilitation take no part here; uchcha bala carries them.
    """
    mt_sign, mt_from, mt_to = utils.MOOLATRIKONA_ARC[planet]
    if sign == mt_sign and (
        rasi_longitude is None or mt_from <= rasi_longitude % 30.0 < mt_to
    ):
        return "moolatrikona"
    if sign in utils._OWN_SIGNS[planet]:
        return "own"
    return compound_relationship(planet, utils.SIGN_LORDS[sign], longitudes)


def _saptavargaja_bala(planet: str, inp: StrengthInputs) -> float:
    lon = inp.longitudes[planet]
    total = _SAPTAVARGAJA_POINTS[varga_state(planet, _sign(lon), lon, inp.longitudes)]
    for varga in SAPTAVARGA[1:]:
        sign = inp.varga_signs[varga][planet]
        total += _SAPTAVARGAJA_POINTS[varga_state(planet, sign, None, inp.longitudes)]
    return total


def _ojayugma_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.4 (second half): a quarter rupa (15) in the rasi and again in
    the navamsa; the Moon and Venus in an even sign, the others in an odd."""
    total = 0.0
    for sign_idx in (_sign_index(inp.longitudes[planet]),
                     utils.SIGNS.index(inp.varga_signs["D9"][planet])):
        odd = sign_idx % 2 == 0  # Aries, index 0, is the first (odd) sign
        if odd != (planet in _EVEN_SIGN_GRAHAS):
            total += 15.0
    return total


def _kendradi_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.5: 60 in a kendra, 30 in a panaphara, 15 in an apoklima,
    counted in whole signs from the lagna (the engine's primary frame)."""
    house = (_sign_index(inp.longitudes[planet]) - _sign_index(inp.ascendant)) % 12 + 1
    if house in (1, 4, 7, 10):
        return 60.0
    if house in (2, 5, 8, 11):
        return 30.0
    return 15.0


def _drekkana_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.6: a quarter rupa (15) for a male graha in the first decanate,
    a female in the second, a neuter in the third."""
    decanate = int((inp.longitudes[planet] % 30.0) // 10.0)
    return 15.0 if decanate == _DREKKANA_OF[planet] else 0.0


# ---------------------------------------------------------------------------
# Dig bala, BPHS 27.7
# ---------------------------------------------------------------------------

def _dig_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.7: deduct the 4th bhava (the nadir) from the Sun and Mars, the
    7th (the descendant) from Jupiter and Mercury, the 10th (the meridian)
    from the Moon and Venus and the lagna from Saturn; reduce past six signs
    and divide by three."""
    nadir = inp.midheaven + 180.0
    descendant = inp.ascendant + 180.0
    point = {
        "Sun": nadir, "Mars": nadir,
        "Jupiter": descendant, "Mercury": descendant,
        "Moon": inp.midheaven, "Venus": inp.midheaven,
        "Saturn": inp.ascendant,
    }[planet]
    return _arc(inp.longitudes[planet], point) / 3.0


# ---------------------------------------------------------------------------
# Kaala bala, BPHS 27.8-17 and 27.20
# ---------------------------------------------------------------------------

def is_day_birth(inp: StrengthInputs) -> bool:
    """Born between the sunrise that opens the day and the next sunset."""
    return inp.birth_jd < inp.sunset_jd


def _nathonnata_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.8-9: unnata is the interval between midnight and the apparent
    time of birth, in ghatis (0 to 30); nata is 30 less unnata. The Moon,
    Mars and Saturn get twice the nata; the Sun, Jupiter and Venus 60 less
    that; Mercury always 60."""
    if planet == "Mercury":
        return 60.0
    h = inp.local_apparent_hours % 24.0
    unnata = min(h, 24.0 - h) * 2.5  # hours from midnight -> ghatis
    night = 2.0 * (30.0 - unnata)
    return night if planet in ("Moon", "Mars", "Saturn") else 60.0 - night


def _paksha_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.10-11: the Moon's distance from the Sun, reduced past six
    signs, in degrees divided by three, for a benefic; 60 less that for a
    malefic. The Moon's is not doubled (Santhanam's BPHS)."""
    value = _arc(inp.longitudes["Moon"], inp.longitudes["Sun"]) / 3.0
    return value if is_benefic(planet, inp.longitudes) else 60.0 - value


def _tribhaga_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.12: in the first, second and last third of the day Mercury,
    the Sun and Saturn get one rupa; in the thirds of the night the Moon,
    Venus and Mars; Jupiter always."""
    if planet == "Jupiter":
        return 60.0
    if is_day_birth(inp):
        start, end, lords = inp.sunrise_jd, inp.sunset_jd, ("Mercury", "Sun", "Saturn")
    else:
        start, end, lords = inp.sunset_jd, inp.next_sunrise_jd, ("Moon", "Venus", "Mars")
    third = min(2, int(3.0 * (inp.birth_jd - start) / (end - start)))
    return 60.0 if lords[third] == planet else 0.0


def ahargana(inp: StrengthInputs) -> int:
    """Days since creation for the Hindu day of birth (Surya Siddhanta
    1.21-24, counted as in Santhanam's note to BPHS 27.13).

    The count is anchored to the note's figure for 1 January 1860, and the
    day of birth takes its own number: a day whose count is a multiple of 360
    (or of 30) already takes the next year's (or month's) lord in year_lord
    and month_lord. Read as the days elapsed before the day of birth, every
    such boundary would fall one day later."""
    return _AHARGANA_AT_KALI_DAY_ONE + (inp.hindu_day_jdn - _KALI_DAY_ONE_JDN)


def _counted_from_sunday(remainder: int) -> str:
    """Surya Siddhanta 1.51-52: the remainder counted from the Sun, so 1 is
    the Sun's, 2 the Moon's ... 6 Venus's and 0 Saturn's."""
    return _WEEKDAY_LORDS[(remainder - 1) % 7]


def year_lord(inp: StrengthInputs) -> str:
    """Surya Siddhanta 1.52: the ahargana divided by 360; the quotient times
    3, plus 1, divided by 7; the remainder counted from the Sun."""
    return _counted_from_sunday((ahargana(inp) // 360 * 3 + 1) % 7)


def month_lord(inp: StrengthInputs) -> str:
    """Surya Siddhanta 1.52: the ahargana divided by 30; the quotient times
    2, plus 1, divided by 7; the remainder counted from the Sun."""
    return _counted_from_sunday((ahargana(inp) // 30 * 2 + 1) % 7)


def weekday_lord(inp: StrengthInputs) -> str:
    """Surya Siddhanta 1.51: the ahargana divided by 7; the remainder counted
    from the Sun is the lord of the day."""
    return _counted_from_sunday(ahargana(inp) % 7)


def hora_lord(inp: StrengthInputs) -> str:
    """BPHS 27.13 with its translator's note: sunrise to sunrise holds 24
    equal horas; the first is the weekday lord's and each next belongs to the
    sixth lord from the previous one in weekday order."""
    span = (inp.next_sunrise_jd - inp.sunrise_jd) / 24.0
    k = min(23, int((inp.birth_jd - inp.sunrise_jd) / span))
    start = _WEEKDAY_LORDS.index(weekday_lord(inp))
    return _WEEKDAY_LORDS[(start + 5 * k) % 7]


def _lord_balas(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.13: 15, 30, 45 and 60 virupas to the lords of the year, the
    month, the day and the hora."""
    return (
        (15.0 if year_lord(inp) == planet else 0.0)
        + (30.0 if month_lord(inp) == planet else 0.0)
        + (45.0 if weekday_lord(inp) == planet else 0.0)
        + (60.0 if hora_lord(inp) == planet else 0.0)
    )


def kranti_khanda(bhuja: float) -> float:
    """BPHS 27.15-16: the khandas 45, 33 and 12 for the first, second and
    third sign of the bhuja, each taken in proportion (0 to 90)."""
    if bhuja <= 30.0:
        return 45.0 * bhuja / 30.0
    if bhuja <= 60.0:
        return 45.0 + 33.0 * (bhuja - 30.0) / 30.0
    return 78.0 + 12.0 * (bhuja - 60.0) / 30.0


def _ayana_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.15-17: from the sayana longitude take the bhuja (the distance
    from the nearer equinox) and its kranti by the khandas. The Moon and
    Saturn add it to three signs (90) in Tula to Meena and deduct it in
    Mesha to Kanya; the Sun, Mars, Jupiter and Venus the reverse; Mercury
    always adds. The result divided by three (0 to 60). Not doubled for the
    Sun: the doubling is the translator's note, not the verse."""
    sayana = (inp.longitudes[planet] + inp.ayanamsa) % 360.0
    northern = sayana < 180.0
    half = sayana % 180.0
    kranti = kranti_khanda(min(half, 180.0 - half))
    if planet == "Mercury":
        adds = True
    elif planet in ("Moon", "Saturn"):
        adds = not northern
    else:
        adds = northern
    return (90.0 + kranti if adds else 90.0 - kranti) / 3.0


def yuddha_pairs(inp: StrengthInputs) -> list[tuple[str, str]]:
    """Planetary wars, Surya Siddhanta 7.18-21: two star grahas less than one
    degree apart are at war, and the one to the north (the greater ecliptic
    latitude) is the victor. Returns (victor, vanquished) pairs."""
    pairs = []
    for i, a in enumerate(_STAR_GRAHAS):
        for b in _STAR_GRAHAS[i + 1:]:
            if _arc(inp.longitudes[a], inp.longitudes[b]) >= 1.0:
                continue
            lat_a, lat_b = inp.latitudes[a], inp.latitudes[b]
            if lat_a != lat_b:
                pairs.append((a, b) if lat_a > lat_b else (b, a))
    return pairs


# ---------------------------------------------------------------------------
# Cheshta bala, BPHS 27.18 and 27.24-25
# ---------------------------------------------------------------------------

def surya_siddhanta_mean_longitude(body: str, jd_ut: float) -> float:
    """Mean longitude (or sighrocca) of *body* by the Surya Siddhanta: its
    revolutions in a Mahayuga times the days elapsed since the Kali epoch,
    over the civil days in a Mahayuga (SS 1.29-37, 1.57). No bija."""
    elapsed = Fraction(jd_ut) - Fraction(_KALI_EPOCH_JD_UT)
    revolutions = _SS_REVOLUTIONS[body] * elapsed / _SS_CIVIL_DAYS
    return float(revolutions % 1) * 360.0


def cheshta_kendra(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.24-25: the sighrocca less half the sum of the mean and the true
    longitude. For Mars, Jupiter and Saturn the sighrocca is the mean Sun;
    for Mercury and Venus it is their own sighrocca and their mean longitude
    is the mean Sun's. The half-sum is taken along the shorter arc."""
    mean_sun = surya_siddhanta_mean_longitude("Sun", inp.birth_jd)
    if planet in ("Mercury", "Venus"):
        sighrocca = surya_siddhanta_mean_longitude(f"{planet} sighrocca", inp.birth_jd)
        mean = mean_sun
    else:
        sighrocca = mean_sun
        mean = surya_siddhanta_mean_longitude(planet, inp.birth_jd)
    true = inp.longitudes[planet]
    half_sum = mean + (((true - mean + 180.0) % 360.0) - 180.0) / 2.0
    return (sighrocca - half_sum) % 360.0


def _cheshta_bala(planet: str, inp: StrengthInputs) -> float:
    """BPHS 27.18: the Sun's cheshta bala is his ayana bala and the Moon's her
    paksha bala. BPHS 27.24-25 for the others: the cheshta kendra, reduced
    past six signs, in degrees divided by three."""
    if planet == "Sun":
        return _ayana_bala("Sun", inp)
    if planet == "Moon":
        return _paksha_bala("Moon", inp)
    kendra = cheshta_kendra(planet, inp)
    return (360.0 - kendra if kendra > 180.0 else kendra) / 3.0


# ---------------------------------------------------------------------------
# The Shadbala table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShadbalaVirupas:
    """Every sub-bala of one graha, in virupas."""
    uchcha: float
    saptavargaja: float
    ojayugma: float
    kendradi: float
    drekkana: float
    dig: float
    nathonnata: float
    paksha: float
    tribhaga: float
    lords: float
    ayana: float
    yuddha: float
    cheshta: float
    naisargika: float
    drik: float

    @property
    def sthana(self) -> float:
        return self.uchcha + self.saptavargaja + self.ojayugma + self.kendradi + self.drekkana

    @property
    def kaala(self) -> float:
        return (self.nathonnata + self.paksha + self.tribhaga + self.lords
                + self.ayana + self.yuddha)

    @property
    def total(self) -> float:
        return self.sthana + self.dig + self.kaala + self.cheshta + self.naisargika + self.drik


def shadbala_virupas(inp: StrengthInputs) -> dict[str, ShadbalaVirupas]:
    """The classical Shadbala of the seven grahas, every sub-bala in virupas."""
    parts: dict[str, dict[str, float]] = {}
    for planet in SHADBALA_PLANETS:
        lon = inp.longitudes[planet]
        parts[planet] = {
            "uchcha": _uchcha_bala(planet, lon),
            "saptavargaja": _saptavargaja_bala(planet, inp),
            "ojayugma": _ojayugma_bala(planet, inp),
            "kendradi": _kendradi_bala(planet, inp),
            "drekkana": _drekkana_bala(planet, inp),
            "dig": _dig_bala(planet, inp),
            "nathonnata": _nathonnata_bala(planet, inp),
            "paksha": _paksha_bala(planet, inp),
            "tribhaga": _tribhaga_bala(planet, inp),
            "lords": _lord_balas(planet, inp),
            "ayana": _ayana_bala(planet, inp),
            "yuddha": 0.0,
            "cheshta": _cheshta_bala(planet, inp),
            "naisargika": 60.0 * _NAISARGIKA_SEVENTHS[planet] / 7.0,
            "drik": _aspect_strength(lon, inp.longitudes),
        }
    # BPHS 27.20: the difference between the two grahas' Shadbala is added to
    # the victor's and deducted from the vanquished's. Every war is judged on
    # the totals before any war is applied.
    before = {p: sum(v.values()) for p, v in parts.items()}
    for victor, vanquished in yuddha_pairs(inp):
        difference = abs(before[victor] - before[vanquished])
        parts[victor]["yuddha"] += difference
        parts[vanquished]["yuddha"] -= difference
    return {p: ShadbalaVirupas(**v) for p, v in parts.items()}


def _result(planet: str, v: ShadbalaVirupas) -> ShadbalaResult:
    total = round(v.total / 60.0, 3)
    minimum = SHADBALA_MINIMUMS[planet]
    return ShadbalaResult(
        planet=planet,
        sthana_bala=round(v.sthana / 60.0, 3),
        dig_bala=round(v.dig / 60.0, 3),
        kaala_bala=round(v.kaala / 60.0, 3),
        cheshta_bala=round(v.cheshta / 60.0, 3),
        naisargika_bala=round(v.naisargika / 60.0, 3),
        drik_bala=round(v.drik / 60.0, 3),
        total_bala=total,
        minimum_bala=minimum,
        is_below_minimum=total < minimum,
    )


def shadbala_table(inp: StrengthInputs) -> dict[str, ShadbalaResult]:
    """The served Shadbala of the seven grahas, in rupas."""
    return {p: _result(p, v) for p, v in shadbala_virupas(inp).items()}


# ---------------------------------------------------------------------------
# Bhavabala, BPHS 27.26-29
# ---------------------------------------------------------------------------

def bhava_madhya(house: int, inp: StrengthInputs) -> float:
    """The bhava's point: the lagna's degree carried into the house's sign.
    The lagna is the first bhava's point, and bhava n always lies in
    whole-sign house n (the engine's primary house frame)."""
    return (inp.ascendant + 30.0 * (house - 1)) % 360.0


_NARA_SIGNS = frozenset({"Gemini", "Virgo", "Libra", "Aquarius"})
_CHATUSHPADA_SIGNS = frozenset({"Aries", "Taurus", "Leo"})
_KEETA_SIGNS = frozenset({"Cancer", "Scorpio"})


def bhava_dig_reference(madhya: float, inp: StrengthInputs) -> float:
    """BPHS 27.26-28: the point deducted from a bhava, by the bhava's sign.

    The 7th bhava (the descendant) for Kanya, Mithuna, Tula, Kumbha and the
    first half of Dhanus; the 4th (the nadir) for Mesha, Vrishabha, Simha,
    the first half of Makara and the second half of Dhanus; the lagna for
    Karkata and Vrischika; the 10th (the meridian) for the second half of
    Makara and for Meena.
    """
    sign = _sign(madhya)
    first_half = madhya % 30.0 < 15.0
    if sign in _NARA_SIGNS or (sign == "Sagittarius" and first_half):
        return inp.ascendant + 180.0
    if (sign in _CHATUSHPADA_SIGNS or sign == "Sagittarius"
            or (sign == "Capricorn" and first_half)):
        return inp.midheaven + 180.0
    if sign in _KEETA_SIGNS:
        return inp.ascendant
    return inp.midheaven


def bhava_virupas(house: int, inp: StrengthInputs) -> tuple[float, float]:
    """(bhava digbala, bhava drishti bala) of one house, in virupas.

    Digbala, BPHS 27.28: the arc from the reference point, reduced past six
    signs, divided by three. Drishti, BPHS 27.29: as drik bala, on the
    bhava's point.
    """
    madhya = bhava_madhya(house, inp)
    dig = _arc(madhya, bhava_dig_reference(madhya, inp)) / 3.0
    return dig, _aspect_strength(madhya, inp.longitudes)


def bhavabala_table(inp: StrengthInputs,
                    shadbala: Mapping[str, ShadbalaVirupas]) -> list[BhavabalaResult]:
    """Bhavabala of the twelve houses, in rupas: the bhavadhipati bala (the
    full Shadbala of the house's lord, BPHS 27.26) plus the bhava digbala
    and the bhava drishti bala. Ranked strong / average / weak by quartile."""
    results = []
    for house in range(1, 13):
        lord = utils.SIGN_LORDS[_sign(bhava_madhya(house, inp))]
        adhipati = shadbala[lord].total / 60.0
        dig, drishti = bhava_virupas(house, inp)
        results.append(BhavabalaResult(
            house_number=house,
            bala_total=round(adhipati + (dig + drishti) / 60.0, 3),
            bhava_adhipathi_bala=round(adhipati, 3),
            bhava_drik=round(drishti / 60.0, 3),
            rank="",
        ))
    totals = [r.bala_total for r in results]
    # Quartile boundaries derived from length so the 4/4/4 split scales if
    # the house count ever differs from 12 (n=12 -> q1=index 3, q3=index 8).
    n = len(totals)
    ordered = sorted(totals)
    q1 = ordered[n // 4]            # bottom quartile boundary (n=12 -> index 3)
    q3 = ordered[n - n // 4 - 1]    # top quartile boundary  (n=12 -> index 8)
    for r in results:
        if r.bala_total >= q3:
            r.rank = "strong"
        elif r.bala_total <= q1:
            r.rank = "weak"
        else:
            r.rank = "average"
    return results


# ---------------------------------------------------------------------------
# From a chart to the inputs
# ---------------------------------------------------------------------------

# A search for a sunrise or sunset is refined from this many days before the
# event it found (see _next_solar_event).
_NEAR_SEARCH_DAYS = 0.25


def _rise_trans(jd_ut: float, rsmi: int, geopos: tuple[float, float, float]) -> float:
    res, tret = swe.rise_trans(jd_ut, swe.SUN, rsmi, geopos, 0.0, 0.0,
                               utils.POSITION_FLAGS)
    if res != 0:
        logger.warning("shadbala_undefined reason=no_solar_event rsmi=%s", rsmi)
        raise ShadbalaUndefinedError(
            "the Sun does not rise and set at this place around this date, so "
            "tribhaga, hora and vara bala (BPHS 27.12-13) are undefined"
        )
    return tret[0]


def _next_solar_event(jd_ut: float, rsmi: int, geopos: tuple[float, float, float]) -> float:
    """The first sunrise or sunset after *jd_ut* on the declared rise/set
    convention (utils.RISE_FLAGS / SET_FLAGS: the centre of the disc on the
    horizon, refraction ignored).

    Searched twice when the event lies far from the start. swe.rise_trans
    started about a day before an event returns it up to about four minutes
    off at high latitudes (measured: the sunrise of 1947-12-22 at 59.4 S
    226 s late, of 2019-06-20 at 51.5 N 14 s late), and within 0.1 s when
    started a quarter of a day or less before it. So an event found more than
    a quarter of a day after the start is searched for again from a quarter
    of a day before it.

    A search can read past the shipped data files: from the last admissible
    birth instant, the sunrise after the birth lies past them. swisseph then
    keeps its fallback for every later lookup, even at Julian Days the files
    cover, so the ephemeris state is re-applied when the search ends, however
    it ends (utils.restore_ephemeris_state).
    """
    try:
        event = _rise_trans(jd_ut, rsmi, geopos)
        if event - jd_ut > _NEAR_SEARCH_DAYS:
            event = _rise_trans(event - _NEAR_SEARCH_DAYS, rsmi, geopos)
        return event
    finally:
        utils.restore_ephemeris_state()


@utils.serialized_ephemeris
def strength_inputs(snapshot: ChartSnapshot) -> StrengthInputs:
    """Read every input of the classical computation for *snapshot*."""
    missing = [p for p in SHADBALA_PLANETS if p not in snapshot.rasi_chart]
    if missing:
        raise ValueError(f"Shadbala needs all seven grahas; the chart lacks {missing}")
    person = snapshot.person
    jd_ut = snapshot.jd
    geopos = (person.longitude, person.latitude, 0.0)
    ayanamsa = snapshot.ayanamsa_value

    # The ascendant and the meridian in the frame the grahas are served in,
    # exactly as Chart._compute takes the lagna (utils.sidereal_houses).
    # Placidus is undefined past the polar circles; ascmc does not depend on
    # the house system, so the equal-house call stands in there.
    try:
        _, ascmc = utils.sidereal_houses(jd_ut, person.latitude, person.longitude, b"P")
    except Exception:
        _, ascmc = utils.sidereal_houses(jd_ut, person.latitude, person.longitude, b"E")
    ascendant = ascmc[0] % 360.0
    midheaven = ascmc[1] % 360.0

    # The sunrise that opens the Hindu day of birth is the last one at or
    # before the birth instant; the day runs to the next sunrise.
    sunrise = _next_solar_event(jd_ut - 2.0, utils.RISE_FLAGS, geopos)
    following = _next_solar_event(sunrise + 1e-4, utils.RISE_FLAGS, geopos)
    while following <= jd_ut:
        sunrise = following
        following = _next_solar_event(sunrise + 1e-4, utils.RISE_FLAGS, geopos)
    sunset = _next_solar_event(sunrise + 1e-4, utils.SET_FLAGS, geopos)
    if sunrise > jd_ut or sunset >= following:
        logger.warning("shadbala_undefined reason=no_day_frame")
        raise ShadbalaUndefinedError(
            "no sunrise-to-sunset day frame encloses the birth, so tribhaga, "
            "hora and vara bala (BPHS 27.12-13) are undefined"
        )

    tz = person.timezone_offset_hours
    hindu_day_jdn = math.floor(sunrise + tz / 24.0 + 0.5)
    ut_hours = ((jd_ut + 0.5) % 1.0) * 24.0
    apparent = (ut_hours + person.longitude / 15.0 + swe.time_equ(jd_ut) * 24.0) % 24.0

    return StrengthInputs(
        longitudes={name: pd.longitude_abs for name, pd in snapshot.rasi_chart.items()},
        latitudes={star: utils.graha_ecliptic_latitude(jd_ut, star) for star in _STAR_GRAHAS},
        varga_signs={
            label: {name: pd.sign for name, pd in getattr(snapshot, field).items()}
            for label, field in _VARGA_FIELD.items()
        },
        ayanamsa=ayanamsa,
        ascendant=ascendant,
        midheaven=midheaven,
        birth_jd=jd_ut,
        sunrise_jd=sunrise,
        sunset_jd=sunset,
        next_sunrise_jd=following,
        local_apparent_hours=apparent,
        hindu_day_jdn=hindu_day_jdn,
    )


def compute_shadbala(snapshot: ChartSnapshot, planet: str) -> ShadbalaResult:
    """The served Shadbala of one of the seven grahas."""
    if planet not in snapshot.rasi_chart:
        raise ValueError(f"Planet {planet} not found in chart")
    if planet not in SHADBALA_MINIMUMS:
        raise ValueError(f"Shadbala is defined for the seven grahas, not {planet}")
    return shadbala_table(strength_inputs(snapshot))[planet]


def compute_all_bhavabala(snapshot: ChartSnapshot) -> list[BhavabalaResult]:
    """The served Bhavabala of the twelve houses."""
    inp = strength_inputs(snapshot)
    return bhavabala_table(inp, shadbala_virupas(inp))


def compute_strength(
    snapshot: ChartSnapshot,
) -> tuple[dict[str, ShadbalaResult], list[BhavabalaResult]]:
    """The served Shadbala of the seven grahas and Bhavabala of the twelve
    houses, from one reading of the inputs (the sunrise and sunset searches
    and the war latitudes are read once, not once per graha)."""
    inp = strength_inputs(snapshot)
    virupas = shadbala_virupas(inp)
    shadbala = {p: _result(p, v) for p, v in virupas.items()}
    return shadbala, bhavabala_table(inp, virupas)


# Bhinnashtakavarga benefic places per BPHS chapter 66 (Parashara), read
# verse by verse; the Moon's rows are vv. 46-48 and Venus's vv. 56-58. Four
# rows differ from the variant table that many printed tables and programs
# carry (attributed to Varahamihira's Brihat Jataka ch. 9), which this module
# served until it was checked against the verses: the Moon from the Moon (BPHS
# adds the 9th), from Mars
# (BPHS drops the 9th), from Jupiter (BPHS has the 2nd, not the 12th) and Venus
# from Mars (BPHS has the 4th, not the 5th). The per-planet totals are the same
# in both, so only a row-by-row check can tell them apart.
# For each planet's own ashtakavarga, every reference point (the 7 planets plus
# the Lagna) contributes a bindu to specific houses counted *from that reference
# point*. A planet's BAV is the sum of bindus from all 8 reference points (0-8
# per sign). Per-planet BAV totals: Sun 48, Moon 49, Mars 39, Mercury 54,
# Jupiter 56, Venus 52, Saturn 39; SAV (sum of the 7) = 337.
_ASHTAKAVARGA_BENEFICS: dict[str, dict[str, list[int]]] = {
    "Sun": {
        "Sun":     [1, 2, 4, 7, 8, 9, 10, 11],
        "Moon":    [3, 6, 10, 11],
        "Mars":    [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [5, 6, 9, 11],
        "Venus":   [6, 7, 12],
        "Saturn":  [1, 2, 4, 7, 8, 9, 10, 11],
        "Lagna":   [3, 4, 6, 10, 11, 12],
    },
    "Moon": {
        "Sun":     [3, 6, 7, 8, 10, 11],
        "Moon":    [1, 3, 6, 7, 9, 10, 11],
        "Mars":    [2, 3, 5, 6, 10, 11],
        "Mercury": [1, 3, 4, 5, 7, 8, 10, 11],
        "Jupiter": [1, 2, 4, 7, 8, 10, 11],
        "Venus":   [3, 4, 5, 7, 9, 10, 11],
        "Saturn":  [3, 5, 6, 11],
        "Lagna":   [3, 6, 10, 11],
    },
    "Mars": {
        "Sun":     [3, 5, 6, 10, 11],
        "Moon":    [3, 6, 11],
        "Mars":    [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [3, 5, 6, 11],
        "Jupiter": [6, 10, 11, 12],
        "Venus":   [6, 8, 11, 12],
        "Saturn":  [1, 4, 7, 8, 9, 10, 11],
        "Lagna":   [1, 3, 6, 10, 11],
    },
    "Mercury": {
        "Sun":     [5, 6, 9, 11, 12],
        "Moon":    [2, 4, 6, 8, 10, 11],
        "Mars":    [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [1, 3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [6, 8, 11, 12],
        "Venus":   [1, 2, 3, 4, 5, 8, 9, 11],
        "Saturn":  [1, 2, 4, 7, 8, 9, 10, 11],
        "Lagna":   [1, 2, 4, 6, 8, 10, 11],
    },
    "Jupiter": {
        "Sun":     [1, 2, 3, 4, 7, 8, 9, 10, 11],
        "Moon":    [2, 5, 7, 9, 11],
        "Mars":    [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [1, 2, 4, 5, 6, 9, 10, 11],
        "Jupiter": [1, 2, 3, 4, 7, 8, 10, 11],
        "Venus":   [2, 5, 6, 9, 10, 11],
        "Saturn":  [3, 5, 6, 12],
        "Lagna":   [1, 2, 4, 5, 6, 7, 9, 10, 11],
    },
    "Venus": {
        "Sun":     [8, 11, 12],
        "Moon":    [1, 2, 3, 4, 5, 8, 9, 11, 12],
        "Mars":    [3, 4, 6, 9, 11, 12],
        "Mercury": [3, 5, 6, 9, 11],
        "Jupiter": [5, 8, 9, 10, 11],
        "Venus":   [1, 2, 3, 4, 5, 8, 9, 10, 11],
        "Saturn":  [3, 4, 5, 8, 9, 10, 11],
        "Lagna":   [1, 2, 3, 4, 5, 8, 9, 11],
    },
    "Saturn": {
        "Sun":     [1, 2, 4, 7, 8, 10, 11],
        "Moon":    [3, 6, 11],
        "Mars":    [3, 5, 6, 10, 11, 12],
        "Mercury": [6, 8, 9, 10, 11, 12],
        "Jupiter": [5, 6, 11, 12],
        "Venus":   [6, 11, 12],
        "Saturn":  [3, 5, 6, 11],
        "Lagna":   [1, 3, 4, 6, 10, 11],
    },
}

_ASHTAKAVARGA_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]


def compute_ashtakavarga(snapshot: ChartSnapshot,
                         planet: str | None = None) -> dict:
    """Bhinnashtakavarga (per-planet) and Sarvashtakavarga bindus per sign.

    For each of the 7 planets, bindus are accumulated from all 8 reference points
    (the 7 planets + the Lagna) per the BPHS chapter 66 benefic-place tables.
    The Lagna is a reference point *inside* each planet's varga, never a separate
    binna column, so the SAV (samudaya) is the sum of the 7 planetary BAVs.

    Returns {"binna": {planet: {sign: bindus}}, "samudaya": {sign: bindus}}, or
    when ``planet`` is given, {"binna": {sign: bindus}, "samudaya": {sign: bindus}}.
    """
    signs = utils.SIGNS

    ref_idx: dict[str, int] = {
        name: utils.SIGNS.index(pd.sign)
        for name, pd in snapshot.rasi_chart.items()
    }
    ref_idx["Lagna"] = utils.SIGNS.index(snapshot.lagna)

    binna: dict[str, dict[str, int]] = {}
    samudaya = [0] * 12

    for p in _ASHTAKAVARGA_PLANETS:
        scores = [0] * 12
        for ref, houses in _ASHTAKAVARGA_BENEFICS[p].items():
            base = ref_idx.get(ref)
            if base is None:
                continue
            for house in houses:
                scores[(base + house - 1) % 12] += 1
        binna[p] = {signs[i]: scores[i] for i in range(12)}
        for i in range(12):
            samudaya[i] += scores[i]

    sav = {signs[i]: samudaya[i] for i in range(12)}

    if planet is not None:
        return {"binna": binna.get(planet, {}), "samudaya": sav}
    return {"binna": binna, "samudaya": sav}
