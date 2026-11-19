"""BPHS single-chart profile data: Avkahada Chakra, Kalsarp Dosh,
Sade Sati lifetime scan, Numerology, and Favourable auspicious markers.

All calculations are pure Python / deterministic math — no LLM, no swe calls
except for the Sade Sati lifetime scan (which uses the transit longitude helper
from transits.py).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from . import utils
from .chart import ChartSnapshot
from .compat import (
    _VARNA_LEVEL,
    _VARNA_NAMES,
    NAKSHATRA_GANA,
    NAKSHATRA_YONI,
    _degree_in_sign,
    _mangal_dosha_raw,
    _nakshatra_nadi,
    vasya_group,
)

logger = logging.getLogger(__name__)

# Vimshottari nakshatra lords in order (27 nakshatras).
_NAK_LORDS = [
    "Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury",
    "Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury",
    "Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury",
]


# ---------------------------------------------------------------------------
# Janma Nakshatra static metadata (27 nakshatras, BPHS / classical tables)
# ---------------------------------------------------------------------------

# Proper nouns (deity names, animal names, Sanskrit terms) kept transliterated —
# untranslated across locales by design. Interpretation prose is the LLM's job.
JANMA_NAKSHATRA_DATA: dict[str, dict] = {
    "Ashwini":           {"deity": "Ashwini Kumaras", "symbol": "Horse's head",        "ruling_planet": "Ketu",    "tattva": "Fire",  "purushartha": "Dharma",  "body_part": "Knees",           "nature": "Light / Swift (Laghu/Kshipra)"},
    "Bharani":           {"deity": "Yama",            "symbol": "Yoni (womb)",          "ruling_planet": "Venus",   "tattva": "Earth", "purushartha": "Artha",   "body_part": "Head",            "nature": "Fierce / Severe (Ugra)"},
    "Krittika":          {"deity": "Agni",            "symbol": "Razor / flame",        "ruling_planet": "Sun",     "tattva": "Fire",  "purushartha": "Kama",    "body_part": "Eyes",            "nature": "Mixed (Mishra)"},
    "Rohini":            {"deity": "Brahma / Prajapati", "symbol": "Chariot / temple",  "ruling_planet": "Moon",    "tattva": "Earth", "purushartha": "Moksha",  "body_part": "Forehead / legs", "nature": "Fixed (Dhruva)"},
    "Mrigashira":        {"deity": "Soma (Moon)",     "symbol": "Deer's head",          "ruling_planet": "Mars",    "tattva": "Air",   "purushartha": "Moksha",  "body_part": "Eyes / eyebrows", "nature": "Soft / Mild (Mridu)"},
    "Ardra":             {"deity": "Rudra",           "symbol": "Teardrop / diamond",   "ruling_planet": "Rahu",    "tattva": "Air",   "purushartha": "Kama",    "body_part": "Hair / arms",     "nature": "Sharp / Intense (Tikshna)"},
    "Punarvasu":         {"deity": "Aditi",           "symbol": "Bow / quiver",         "ruling_planet": "Jupiter", "tattva": "Water", "purushartha": "Artha",   "body_part": "Nose / fingers",  "nature": "Movable (Chara)"},
    "Pushya":            {"deity": "Brihaspati",      "symbol": "Flower / circle",      "ruling_planet": "Saturn",  "tattva": "Water", "purushartha": "Dharma",  "body_part": "Face / mouth",    "nature": "Light / Swift (Laghu/Kshipra)"},
    "Ashlesha":          {"deity": "Sarpa (serpent)", "symbol": "Coiled serpent",       "ruling_planet": "Mercury", "tattva": "Water", "purushartha": "Dharma",  "body_part": "Ears / joints",   "nature": "Sharp / Intense (Tikshna)"},
    "Magha":             {"deity": "Pitrs (ancestors)", "symbol": "Throne / palanquin", "ruling_planet": "Ketu",    "tattva": "Fire",  "purushartha": "Artha",   "body_part": "Nose / lips",     "nature": "Fierce / Severe (Ugra)"},
    "Purva Phalguni":    {"deity": "Bhaga",           "symbol": "Front legs of cot",    "ruling_planet": "Venus",   "tattva": "Fire",  "purushartha": "Kama",    "body_part": "Right hand",      "nature": "Fierce / Severe (Ugra)"},
    "Uttara Phalguni":   {"deity": "Aryaman",         "symbol": "Back legs of cot",     "ruling_planet": "Sun",     "tattva": "Earth", "purushartha": "Moksha",  "body_part": "Left hand",       "nature": "Fixed (Dhruva)"},
    "Hasta":             {"deity": "Savitur (Sun)",   "symbol": "Open hand",            "ruling_planet": "Moon",    "tattva": "Earth", "purushartha": "Moksha",  "body_part": "Hands / fingers", "nature": "Light / Swift (Laghu/Kshipra)"},
    "Chitra":            {"deity": "Vishvakarman",    "symbol": "Shining jewel / pearl","ruling_planet": "Mars",    "tattva": "Fire",  "purushartha": "Kama",    "body_part": "Forehead / neck", "nature": "Soft / Mild (Mridu)"},
    "Swati":             {"deity": "Vayu",            "symbol": "Coral / sword",        "ruling_planet": "Rahu",    "tattva": "Air",   "purushartha": "Artha",   "body_part": "Chest / skin",    "nature": "Movable (Chara)"},
    "Vishakha":          {"deity": "Indra-Agni",      "symbol": "Triumphal arch",       "ruling_planet": "Jupiter", "tattva": "Fire",  "purushartha": "Dharma",  "body_part": "Arms / breast",   "nature": "Mixed (Mishra)"},
    "Anuradha":          {"deity": "Mitra",           "symbol": "Lotus / staff",        "ruling_planet": "Saturn",  "tattva": "Water", "purushartha": "Dharma",  "body_part": "Stomach",         "nature": "Soft / Mild (Mridu)"},
    "Jyeshtha":          {"deity": "Indra",           "symbol": "Circular amulet / umbrella", "ruling_planet": "Mercury", "tattva": "Water", "purushartha": "Artha", "body_part": "Tongue / right side", "nature": "Sharp / Intense (Tikshna)"},
    "Mula":              {"deity": "Nirriti / Alakshmi", "symbol": "Root tied together", "ruling_planet": "Ketu",   "tattva": "Fire",  "purushartha": "Kama",    "body_part": "Feet / left side","nature": "Sharp / Intense (Tikshna)"},
    "Purva Ashadha":     {"deity": "Apas (water)",   "symbol": "Elephant tusk / fan",  "ruling_planet": "Venus",   "tattva": "Air",   "purushartha": "Moksha",  "body_part": "Thighs / back",   "nature": "Fierce / Severe (Ugra)"},
    "Uttara Ashadha":    {"deity": "Vishwadevas",     "symbol": "Elephant tusk / planks","ruling_planet": "Sun",    "tattva": "Earth", "purushartha": "Moksha",  "body_part": "Thighs / waist",  "nature": "Fixed (Dhruva)"},
    "Shravana":          {"deity": "Vishnu",          "symbol": "Ear / three footprints","ruling_planet": "Moon",   "tattva": "Air",   "purushartha": "Artha",   "body_part": "Ears / genitals", "nature": "Movable (Chara)"},
    "Dhanishta":         {"deity": "Ashta Vasus",     "symbol": "Drum / flute",         "ruling_planet": "Mars",    "tattva": "Air",   "purushartha": "Dharma",  "body_part": "Back / anus",     "nature": "Movable (Chara)"},
    "Shatabhisha":       {"deity": "Varuna",          "symbol": "Empty circle / 100 stars","ruling_planet": "Rahu", "tattva": "Air",   "purushartha": "Artha",   "body_part": "Right thigh / jaw","nature": "Movable (Chara)"},
    "Purva Bhadrapada":  {"deity": "Aja Ekapada",     "symbol": "Swords / two front legs of funeral cot","ruling_planet": "Jupiter", "tattva": "Air", "purushartha": "Artha", "body_part": "Ribs / sides", "nature": "Fierce / Severe (Ugra)"},
    "Uttara Bhadrapada": {"deity": "Ahir Budhanya",   "symbol": "Twins / back legs of funeral cot","ruling_planet": "Saturn", "tattva": "Water", "purushartha": "Kama", "body_part": "Shins / sides", "nature": "Fixed (Dhruva)"},
    "Revati":            {"deity": "Pushan",          "symbol": "Fish / drum",          "ruling_planet": "Mercury", "tattva": "Water", "purushartha": "Moksha",  "body_part": "Feet / abdomen",  "nature": "Soft / Mild (Mridu)"},
}


def janma_nakshatra(snapshot: ChartSnapshot) -> dict:
    """Return Moon nakshatra with metadata + pada (1–4).

    Pada is computed from the Moon's fractional position within the nakshatra
    (each nakshatra = 13°20' = 4 padas of 3°20' each).
    """
    moon = snapshot.rasi_chart.get("Moon")
    if not moon:
        return {}
    nak = moon.nakshatra
    meta = dict(JANMA_NAKSHATRA_DATA.get(nak, {}))
    meta["nakshatra"] = nak

    # Compute pada (1–4) from Moon's absolute longitude
    try:
        moon_lon = utils.SIGNS.index(moon.sign) * 30 + moon.degrees
        nak_idx = int(moon_lon / (360 / 27))
        nak_start = nak_idx * (360 / 27)
        offset = moon_lon - nak_start
        pada = int(offset / (360 / 27 / 4)) + 1  # 1–4
        meta["pada"] = min(pada, 4)
    except (ValueError, ZeroDivisionError):
        meta["pada"] = None

    return meta


# ---------------------------------------------------------------------------
# Single-chart Mangal Dosha
# ---------------------------------------------------------------------------

def mangal_dosha(snapshot: ChartSnapshot) -> dict:
    """Single-chart Mangal Dosha: checks from lagna and from Moon.

    Reuses the pair-compatibility raw checker from compat.py.
    """
    has_d, sev_d, cancel_d = _mangal_dosha_raw(snapshot)

    # Also check from Moon's chart (Moon treated as lagna)
    moon = snapshot.rasi_chart.get("Moon")
    mars = snapshot.rasi_chart.get("Mars")
    from_moon = False
    if moon and mars:
        # Mars houses from Moon: 1/2/4/7/8/12
        moon_idx = utils.SIGNS.index(moon.sign)
        mars_idx = utils.SIGNS.index(mars.sign)
        mars_house_from_moon = (mars_idx - moon_idx) % 12 + 1
        from_moon = mars_house_from_moon in {1, 2, 4, 7, 8, 12}

    return {
        "present": has_d,
        "severity": sev_d,
        "cancellation": cancel_d[0] if cancel_d else None,
        "from_moon": from_moon,
        "mars_house": mars.house if mars else None,
    }


# ---------------------------------------------------------------------------
# Avkahada Chakra — single-chart Moon-sign / Moon-nakshatra profile
# ---------------------------------------------------------------------------

def _varna(moon_sign: str) -> str:
    level = _VARNA_LEVEL.get(moon_sign, 0)
    return _VARNA_NAMES.get(level, "Unknown")


def _vasya(moon_sign: str, degree_in_sign: float) -> str:
    # Sagittarius and Capricorn change vasya group at 15 degrees, so the group
    # needs the Moon's degree as well as its sign: see
    # bphs_core/compat.py::vasya_group.
    try:
        return vasya_group(moon_sign, degree_in_sign)
    except (KeyError, ValueError):
        return "Unknown"


def _yoni(moon_nak: str) -> str:
    pair = NAKSHATRA_YONI.get(moon_nak)
    if not pair:
        return "Unknown"
    animal, gender = pair
    return f"{animal} ({gender})"


def _gana(moon_nak: str) -> str:
    return NAKSHATRA_GANA.get(moon_nak, "Unknown")


def _nadi(moon_nak: str) -> str:
    try:
        return _nakshatra_nadi(moon_nak)
    except (ValueError, IndexError):
        return "Unknown"


def avkahada_chakra(snapshot: ChartSnapshot) -> dict:
    """Return Avkahada Chakra parameters for a single chart.

    All five parameters are derived from the Moon's sign and nakshatra.
    """
    moon = snapshot.rasi_chart.get("Moon")
    if not moon:
        return {}
    nak = moon.nakshatra
    sign = moon.sign
    nak_idx = utils.NAKSHATRAS.index(nak) if nak in utils.NAKSHATRAS else -1
    return {
        "moon_sign":  sign,
        "moon_nakshatra": nak,
        "varna":      _varna(sign),
        "vasya":      _vasya(sign, _degree_in_sign(moon)),
        "yoni":       _yoni(nak),
        "gana":       _gana(nak),
        "nadi":       _nadi(nak),
        "nakshatra_lord": _NAK_LORDS[nak_idx] if 0 <= nak_idx < len(_NAK_LORDS) else "",
    }


# ---------------------------------------------------------------------------
# Kalsarp Dosh
# ---------------------------------------------------------------------------

_SEVEN_PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")

# Named Kalsarp types by Rahu house (whole-sign from lagna)
_KALSARP_NAMES = {
    1: "Anant Kalsarp",    2: "Kulik Kalsarp",   3: "Vasuki Kalsarp",
    4: "Shankhapal Kalsarp", 5: "Padma Kalsarp",  6: "Mahapadma Kalsarp",
    7: "Takshak Kalsarp",  8: "Karkotak Kalsarp", 9: "Shankhachur Kalsarp",
    10: "Ghatak Kalsarp", 11: "Vishakta Kalsarp", 12: "Sheshnag Kalsarp",
}


def kalsarp_dosh(snapshot: ChartSnapshot) -> dict:
    """Check for Kalsarp Dosh: all 7 visible planets hemmed between Rahu and Ketu.

    Kalsarp Dosh is present when every planet (Sun–Saturn) occupies the 180°
    arc from Rahu to Ketu (measured clockwise). The reciprocal case (all in the
    Ketu→Rahu arc) is sometimes called Kalsarp but is considered less severe
    (Kalasarpa vs Kalsarp — we label it partial). Any planet exactly on Rahu
    or Ketu dissolves the yoga.
    """
    rahu = snapshot.rasi_chart.get("Rahu")
    if not rahu:
        return {"present": False, "name": None, "partial": False, "rahu_house": None}

    rahu_lon = utils.SIGNS.index(rahu.sign) * 30 + rahu.degrees

    in_rahu_ketu_arc: list[bool] = []
    for name in _SEVEN_PLANETS:
        p = snapshot.rasi_chart.get(name)
        if not p:
            continue
        p_lon = utils.SIGNS.index(p.sign) * 30 + p.degrees
        # Planet is in arc if (p_lon - rahu_lon) mod 360 < 180
        in_arc = (p_lon - rahu_lon) % 360 < 180
        in_rahu_ketu_arc.append(in_arc)

    if not in_rahu_ketu_arc:
        return {"present": False, "name": None, "partial": False, "rahu_house": None}

    all_in = all(in_rahu_ketu_arc)
    all_out = not any(in_rahu_ketu_arc)   # all in Ketu→Rahu arc
    rahu_house = rahu.house

    if all_in or all_out:
        name = _KALSARP_NAMES.get(rahu_house, "Kalsarp")
        return {"present": True, "name": name, "partial": False, "rahu_house": rahu_house,
                "direction": "rahu_to_ketu" if all_in else "ketu_to_rahu"}
    return {"present": False, "name": None, "partial": True, "rahu_house": rahu_house}


# ---------------------------------------------------------------------------
# Sade Sati lifetime scan
# ---------------------------------------------------------------------------

_SADE_SATI_SCAN_STEP_DAYS: int = 91
"""Quarterly scan step used by sade_sati_lifetime.

The start/end dates returned by sade_sati_lifetime are rounded to the nearest
quarterly boundary, so they carry an inherent ±91-day (±1 quarter) imprecision.
This constant is exposed so callers and the profile response can communicate the
uncertainty to consumers — e.g. "start date accurate to within ±91 days".
Reducing the step improves precision at the cost of ~4× the computation per
80-year lifetime scan.
"""


_SADE_SATI_HORIZON_YEARS: int = 80
"""How far past the birth date sade_sati_lifetime sweeps, in years."""

_DAYS_PER_YEAR: float = 365.25
"""Length of one of those years in days.

The same year every dasha period in this engine is projected with (the
``timedelta(days=yrs * 365.25)`` arithmetic of
``bphs_core/dashas.py::vimshottari_mahadashas``), so "eighty years on" means one
thing in the dasha timeline and in this sweep. The horizon is counted in days
from the birth date and is never a calendar anniversary: the anniversary of a
29 February birth does not exist in a year that is not a leap year, and building
it raised for every such birth whose eightieth year is 1900, 2100, 2200 or 2300.
Contract: tests/test_leap_day_birth_profile.py.
"""


def sade_sati_lifetime(snapshot: ChartSnapshot, birth_date: date) -> list[dict]:
    """Return all Sade Sati periods from birth to birth+80 years.

    Scans every ~91 days (quarterly) for Saturn's sign relative to natal Moon.
    Contiguous quarters where Saturn occupies the sign before, same as, or after
    natal Moon are merged into a single period with a rising/peak/setting label.

    **Precision note**: period boundaries are accurate to within ±``_SADE_SATI_SCAN_STEP_DAYS``
    days (currently ±91 days / ±1 quarter). Callers that need finer accuracy should
    use a dedicated binary-search ingress finder (e.g. ``get_sade_sati_info`` in
    transits.py) on the specific boundary of interest.
    """
    from .transits import _jd_from_date, _transit_longitude

    moon = snapshot.rasi_chart.get("Moon")
    if not moon or moon.sign not in utils.SIGNS:
        return []

    moon_idx = utils.SIGNS.index(moon.sign)

    # Quarter-year steps over 80 years, the horizon counted in days (see
    # _DAYS_PER_YEAR): a day count exists for every birth date.
    periods: list[dict] = []
    step = timedelta(days=_SADE_SATI_SCAN_STEP_DAYS)
    scan_date = datetime(birth_date.year, birth_date.month, birth_date.day)
    end_date = scan_date + timedelta(days=_SADE_SATI_HORIZON_YEARS * _DAYS_PER_YEAR)

    active: dict | None = None  # current open Sade Sati window
    prev_phase: str | None = None

    while scan_date <= end_date:
        try:
            jd = _jd_from_date(scan_date)
            sat_lon = _transit_longitude(jd, "Saturn")
            sat_idx = int(sat_lon // 30) % 12
        except Exception:
            # A systematic ephemeris/compute failure here would otherwise be
            # indistinguishable from a legitimately empty scan — log it so the
            # difference is visible.
            logger.warning(
                "sade_sati_scan_error scan_date=%s", scan_date.isoformat(), exc_info=True,
            )
            scan_date += step
            continue

        diff = (sat_idx - moon_idx) % 12
        if diff == 11:
            phase = "rising"
        elif diff == 0:
            phase = "peak"
        elif diff == 1:
            phase = "setting"
        else:
            phase = None

        if phase:
            if active is None:
                active = {"phase": phase, "start": scan_date.strftime("%Y-%m-%d"),
                          "end": scan_date.strftime("%Y-%m-%d")}
            else:
                active["end"] = scan_date.strftime("%Y-%m-%d")
                if phase != prev_phase and prev_phase is not None:
                    # phase shifted inside the same continuous window — keep going
                    active["phase"] = "multi"
        else:
            if active is not None:
                periods.append(active)
                active = None
        prev_phase = phase
        scan_date += step

    if active is not None:
        periods.append(active)

    return periods


# ---------------------------------------------------------------------------
# Numerology
# ---------------------------------------------------------------------------

def _reduce(n: int) -> int:
    while n > 9:
        n = sum(int(d) for d in str(n))
    return n


# Chaldean letter-to-digit mapping (classical numerology)
_CHALDEAN: dict[str, int] = {
    "a": 1, "i": 1, "j": 1, "q": 1, "y": 1,
    "b": 2, "k": 2, "r": 2,
    "c": 3, "g": 3, "l": 3, "s": 3,
    "d": 4, "m": 4, "t": 4,
    "e": 5, "h": 5, "n": 5, "x": 5,
    "u": 6, "v": 6, "w": 6,
    "o": 7, "z": 7,
    "f": 8, "p": 8,
}


def numerology(birth_date: date, name: str = "") -> dict:
    """Radical (Mulank), Destiny (Bhagyank), and Chaldean Name number.

    Radical = digit sum of day, reduced to 1–9.
    Destiny = digit sum of full date (DDMMYYYY), reduced to 1–9.
    Name    = Chaldean digit sum of consonants+vowels in the name, reduced 1–9.
    """
    radical = _reduce(sum(int(d) for d in str(birth_date.day)))
    destiny = _reduce(sum(int(d) for d in str(birth_date.day)
                         + str(birth_date.month)
                         + str(birth_date.year)))
    name_number: int | None = None
    if name.strip():
        letters = [c.lower() for c in name if c.isalpha()]
        total = sum(_CHALDEAN.get(c, 0) for c in letters)
        name_number = _reduce(total) if total else None
    return {"radical": radical, "destiny": destiny, "name": name_number}


# ---------------------------------------------------------------------------
# Favourable Points (Shubha Anka etc.) based on lagna lord
# ---------------------------------------------------------------------------

_LAGNA_LORD_PROFILE: dict[str, dict] = {
    "Sun":     {"lucky_number": 1,  "lucky_metal": "Gold",       "lucky_stone": "Ruby",             "lucky_color": "Red"},
    "Moon":    {"lucky_number": 2,  "lucky_metal": "Silver",     "lucky_stone": "Pearl",            "lucky_color": "White"},
    "Mars":    {"lucky_number": 9,  "lucky_metal": "Copper",     "lucky_stone": "Red Coral",        "lucky_color": "Red"},
    "Mercury": {"lucky_number": 5,  "lucky_metal": "Bronze",     "lucky_stone": "Emerald",          "lucky_color": "Green"},
    "Jupiter": {"lucky_number": 3,  "lucky_metal": "Gold",       "lucky_stone": "Yellow Sapphire",  "lucky_color": "Yellow"},
    "Venus":   {"lucky_number": 6,  "lucky_metal": "Silver",     "lucky_stone": "Diamond",          "lucky_color": "White"},
    "Saturn":  {"lucky_number": 8,  "lucky_metal": "Iron",       "lucky_stone": "Blue Sapphire",    "lucky_color": "Blue"},
    "Rahu":    {"lucky_number": 4,  "lucky_metal": "Lead",       "lucky_stone": "Hessonite",        "lucky_color": "Blue"},
    "Ketu":    {"lucky_number": 7,  "lucky_metal": "Iron",       "lucky_stone": "Cat's Eye",        "lucky_color": "Multicolor"},
}


def favourable_points(snapshot: ChartSnapshot, radical: int = 1) -> dict:
    """Return lucky number / metal / stone / color + auspicious years.

    Keyed on Moon's sign lord (Janma rashi). Auspicious years = ages whose
    year-of-age digit-sum reduces to the lucky number (first 10 such ages).
    """
    moon = snapshot.rasi_chart.get("Moon")
    rasi_lord = utils.get_sign_lord(moon.sign) if moon else snapshot.lagna_lord
    profile = dict(_LAGNA_LORD_PROFILE.get(rasi_lord, {}))
    profile["rasi_lord"] = rasi_lord

    # Good years: ages 1–100 where age-digit-sum == lucky_number
    lucky = profile.get("lucky_number", radical)
    good_ages = [a for a in range(1, 100) if _reduce(a) == lucky]
    profile["good_years"] = good_ages[:10]   # first 10 auspicious ages

    return profile


# ---------------------------------------------------------------------------
# Composite profile — single entry point
# ---------------------------------------------------------------------------

def compute_profile(snapshot: ChartSnapshot, birth_date: date, name: str = "") -> dict:
    num = numerology(birth_date, name)
    fav = favourable_points(snapshot, radical=num.get("radical", 1))
    return {
        "avkahada":           avkahada_chakra(snapshot),
        "kalsarp":            kalsarp_dosh(snapshot),
        "sade_sati_lifetime": sade_sati_lifetime(snapshot, birth_date),
        "numerology":         num,
        "favourable":         fav,
        "janma_nakshatra":    janma_nakshatra(snapshot),
        "mangal_dosha":       mangal_dosha(snapshot),
        # The Sade Sati lifetime scan uses quarterly (~91-day) steps, so
        # period start/end dates are accurate to within ±this many days.
        # Callers that need finer accuracy should use the transits binary-search
        # ingress finder for the specific boundary of interest.
        "precision_days":     _SADE_SATI_SCAN_STEP_DAYS,
    }
