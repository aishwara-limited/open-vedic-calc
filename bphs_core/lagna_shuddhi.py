"""
Lagna Shuddhi: minute-resolution electional muhurat.

Scans candidate windows to find the precise instant where the rising lagna
and its lord are well-disposed for the intended activity, clear of hard
inauspicious periods (Rahu Kala, Yamaganda, Gulika).

Does NOT compute or guess planetary positions — all astrology math uses
pyswisseph/pyjhora calls at the exact Julian Day of each candidate minute.

Family scan (scan_family_lagna_shuddhi): computes a single deterministic
joint instant that satisfies all members simultaneously — hard-gating each
member's Rahu/Yama/Gulika exclusions and Tara/Chandra Bala, then ranking by
the minimum individual score so no weak member can be averaged away.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

import swisseph as swe
from jhora.panchanga import drik

from . import utils
from .muhurat import (
    _TARA_BALA_LEVELS,
    VARJYAM_HOURS_KEY,
    compute_muhurat_for_day,
    panchanga_at_instant,
)

logger = logging.getLogger(__name__)

# Chaldean descending-speed order (used for hora lord sequence)
_CHALDEAN = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]
_WEEKDAY_LORDS = {
    "Monday": "Moon", "Tuesday": "Mars", "Wednesday": "Mercury",
    "Thursday": "Jupiter", "Friday": "Venus", "Saturday": "Saturn", "Sunday": "Sun",
}
# The classical natural malefics, by NAME. Grahas are resolved to swisseph
# bodies only inside utils.graha_sidereal_longitude — the sanctioned
# name -> body boundary. Never rebuild an integer id table from
# enumerate(utils.PLANETS): those indices are pyjhora's planet numbering,
# which swisseph does not follow (index 2 is Mars in one space and Mercury
# in the other — see the boundary rationale in bphs_core/utils.py).
_MALEFIC_GRAHAS = ("Sun", "Mars", "Saturn", "Rahu", "Ketu")
_FAVORABLE_CHOGADIYA = {
    "Chara (Auspicious)", "Labh (Auspicious)",
    "Amrit (Highly Auspicious)", "Shubh (Auspicious)",
}
_FAVORABLE_HORA = {"Sun", "Moon", "Mercury", "Jupiter", "Venus"}

ActivityCategory = Literal[
    "generic",
    # exclusive
    "marriage",
    # special
    "griha_pravesh", "business", "shop_opening", "property",
    "namkaran", "mundan", "annaprashan", "upanayana", "surgery",
    # normal
    "travel", "vehicle", "new_job", "education",
]

# --- Panchanga suitability---------------------------------------------
# Rikta tithis (4th, 9th, 14th of either paksha) are classically inauspicious
# for new undertakings; get_tithi_name prefixes the paksha, so match by base name.
_RIKTA_TITHIS = ("Chaturthi", "Navami", "Chaturdashi")
# Amavasya (new moon) is classically prohibited for new undertakings. It is NOT
# a Rikta tithi, so it needs its own membership check on the tithi name.
_AMAVASYA = "Amavasya"
# Classically avoided yogas (Vishkumbha … Vaidhriti).
_INAUSPICIOUS_YOGAS = frozenset({
    "Vishkumbha", "Atiganda", "Shula", "Ganda", "Vyaghata",
    "Vajra", "Vyatipata", "Parigha", "Vaidhriti",
})

# Event Navamsha (D9 of the rising sign at the candidate instant) — the
# minute-level electional signal. Its classical use is a *strength* check, NOT a
# per-activity sign whitelist: Vargottama (navamsa lagna sign == rasi lagna
# sign) is the strongest auspicious signal; the lagna's sign NATURE should suit
# the activity (movable for journeys, fixed for permanence/dwelling, dual for
# learning/exchange); a benefic-ruled navamsa lagna is mildly favourable.
# Sources: B.V. Raman, "Muhurtha" (Vargottama / Pushkaramsa); the classical
# chara/sthira/dvisvabhava muhurta rule (movable→yatra/travel, fixed→griha
# pravesh/marriage) — e.g. drikpanchang / standard muhurta texts.
_MOVABLE_SIGNS = frozenset({"Aries", "Cancer", "Libra", "Capricorn"})
_FIXED_SIGNS = frozenset({"Taurus", "Leo", "Scorpio", "Aquarius"})
_DUAL_SIGNS = frozenset({"Gemini", "Virgo", "Sagittarius", "Pisces"})
# Vara (weekday) classes. The benefic day-lords (Moon/Mercury/Jupiter/Venus)
# carry auspicious undertakings; Mangala (Tue) and Shani (Sat) are classically
# avoided for samskaras and beginnings. Commerce/learning lean to Budha/Guru/
# Shukra. (B.V. Raman, "Muhurtha"; standard panchanga vaara-shuddhi.)
_BENEFIC_VARAS = frozenset({"Monday", "Wednesday", "Thursday", "Friday"})
_COMMERCE_VARAS = frozenset({"Wednesday", "Thursday", "Friday"})
_MALEFIC_VARAS = frozenset({"Tuesday", "Saturday"})
# Vara bonus/penalty magnitudes (a tuning choice; the classical texts give a
# qualitative day-lord preference, not numbers).
_VARA_BONUS = 0.06
_VARA_PENALTY = 0.05
# Day/instant conditions that classically VETO an electional instant for the
# activities that name them (subset stored per-activity in ActivityRule).
_SAMSKARA_EXCLUDES = frozenset({"eclipse", "adhik_maasa"})


@dataclass(frozen=True)
class ActivityRule:
    """Per-activity electional preferences — pure DATA, no branching logic.

    Every field below is consumed by ``_score_instant`` / ``_event_navamsha_factor``
    so a new activity is added by appending ONE row to ``_ACTIVITY_RULES`` (Open/
    Closed), never by adding an ``if activity == ...`` branch.

    sign_nature        preferred nature of the lagna / event-navamsa sign
                       (movable→motion, fixed→permanence, dual→learning/exchange).
    prefer_varas       weekdays that earn a bonus (classical day-lords).
    avoid_varas        weekdays that earn a penalty.
    dignity_weight     multiplier on the lagna-lord dignity bonus (>1 amplifies).
    kendra_lord_bonus  extra credit when the lagna lord occupies a kendra.
    chogadiya_bonus    credit for a favourable chogadiya at the instant.
    hard_excludes      conditions that VETO the instant (score 0.0): a subset of
                       {"durm_varj", "eclipse", "adhik_maasa", "vishti"}.

    The values are BPHS-/muhurta-grounded defaults (B.V. Raman, "Muhurtha";
    standard drikpanchang vaara/tithi/yoga shuddhi) and are intended to be
    reviewed for domain accuracy; the *structure* is what keeps scoring uniform.
    """
    sign_nature: frozenset = frozenset()
    prefer_varas: frozenset = frozenset()
    avoid_varas: frozenset = frozenset()
    dignity_weight: float = 1.0
    kendra_lord_bonus: float = 0.0
    chogadiya_bonus: float = 0.08
    hard_excludes: frozenset = frozenset()


# The full taxonomy as data. 14 activities + a neutral ``generic`` fallback.
# Classes (metering lives in the application, not here): exclusive=marriage;
# special=griha_pravesh/business/shop_opening/property/namkaran/mundan/
# annaprashan/upanayana/surgery; normal=travel/vehicle/new_job/education.
_ACTIVITY_RULES: dict[str, ActivityRule] = {
    # Fallback: no fixed preferences — judged on Vargottama + a benefic navamsa
    # lagna alone. Preserves the original "generic" behaviour exactly.
    "generic": ActivityRule(),

    # --- exclusive -------------------------------------------------------
    # Marriage: permanence (fixed) lagna; benefic days, avoid Mangala/Shani;
    # HARD veto on eclipse, Adhika Maasa and Bhadra (Vishti karana). Vyatipata/
    # Vaidhriti are already in the always-avoided yoga set. Amplified lagna-lord
    # dignity weight (the lord's strength matters most for the union).
    "marriage": ActivityRule(
        sign_nature=_FIXED_SIGNS,
        prefer_varas=_BENEFIC_VARAS,
        avoid_varas=_MALEFIC_VARAS,
        dignity_weight=1.2,
        hard_excludes=frozenset({"eclipse", "adhik_maasa", "vishti"}),
    ),

    # --- special ---------------------------------------------------------
    # House entry: dwelling permanence (fixed); benefic days; no auspicious
    # entry during an eclipse or Adhika Maasa.
    "griha_pravesh": ActivityRule(
        sign_nature=_FIXED_SIGNS, prefer_varas=_BENEFIC_VARAS,
        avoid_varas=_MALEFIC_VARAS, hard_excludes=_SAMSKARA_EXCLUDES,
    ),
    # Commerce establishment: durability (fixed); Budha/Guru/Shukra days; a
    # strong lagna lord in a kendra is especially wanted.
    "business": ActivityRule(
        sign_nature=_FIXED_SIGNS, prefer_varas=_COMMERCE_VARAS,
        avoid_varas=_MALEFIC_VARAS, kendra_lord_bonus=0.05,
        hard_excludes=_SAMSKARA_EXCLUDES,
    ),
    # Shop opening: same commercial profile as business establishment.
    "shop_opening": ActivityRule(
        sign_nature=_FIXED_SIGNS, prefer_varas=_COMMERCE_VARAS,
        avoid_varas=_MALEFIC_VARAS, kendra_lord_bonus=0.05,
        hard_excludes=_SAMSKARA_EXCLUDES,
    ),
    # Property purchase: permanence (fixed); benefic days; avoid eclipse/Adhika.
    "property": ActivityRule(
        sign_nature=_FIXED_SIGNS, prefer_varas=_BENEFIC_VARAS,
        avoid_varas=_MALEFIC_VARAS, hard_excludes=_SAMSKARA_EXCLUDES,
    ),
    # Child samskaras (naming / tonsure / first-feeding / sacred-thread). Soft
    # benefic days; eclipse and Adhika Maasa are classically barred. Naming,
    # first-feeding and upanayana carry a learning (dual) flavour; tonsure has
    # no sign-nature preference.
    "namkaran": ActivityRule(
        sign_nature=_DUAL_SIGNS, prefer_varas=_BENEFIC_VARAS,
        avoid_varas=_MALEFIC_VARAS, hard_excludes=_SAMSKARA_EXCLUDES,
    ),
    "mundan": ActivityRule(
        prefer_varas=_BENEFIC_VARAS, avoid_varas=_MALEFIC_VARAS,
        hard_excludes=_SAMSKARA_EXCLUDES,
    ),
    "annaprashan": ActivityRule(
        sign_nature=_DUAL_SIGNS, prefer_varas=_BENEFIC_VARAS,
        avoid_varas=_MALEFIC_VARAS, hard_excludes=_SAMSKARA_EXCLUDES,
    ),
    "upanayana": ActivityRule(
        sign_nature=_DUAL_SIGNS, prefer_varas=_COMMERCE_VARAS,
        avoid_varas=_MALEFIC_VARAS, hard_excludes=_SAMSKARA_EXCLUDES,
    ),
    # Surgery: the one activity that keeps the Durmuhurtam/Varjyam veto; also
    # avoid eclipse. No sign-nature preference (parity with prior behaviour).
    "surgery": ActivityRule(
        hard_excludes=frozenset({"durm_varj", "eclipse"}),
    ),

    # --- normal ----------------------------------------------------------
    # Travel/yatra: motion (movable); a favourable chogadiya weighs more for
    # journeys; avoid eclipse.
    "travel": ActivityRule(
        sign_nature=_MOVABLE_SIGNS, prefer_varas=_BENEFIC_VARAS,
        chogadiya_bonus=0.15, hard_excludes=frozenset({"eclipse"}),
    ),
    # Vehicle purchase: a conveyance → motion (movable); chogadiya weighted
    # like travel.
    "vehicle": ActivityRule(
        sign_nature=_MOVABLE_SIGNS, prefer_varas=_BENEFIC_VARAS,
        chogadiya_bonus=0.15, hard_excludes=frozenset({"eclipse"}),
    ),
    # New job/role: stability (fixed) with a strong lagna lord in a kendra;
    # benefic days.
    "new_job": ActivityRule(
        sign_nature=_FIXED_SIGNS, prefer_varas=_BENEFIC_VARAS,
        avoid_varas=_MALEFIC_VARAS, kendra_lord_bonus=0.05,
        hard_excludes=frozenset({"eclipse"}),
    ),
    # Education/vidyarambha: learning & exchange (dual); Budha/Guru/Shukra days.
    "education": ActivityRule(
        sign_nature=_DUAL_SIGNS, prefer_varas=_COMMERCE_VARAS,
        hard_excludes=frozenset({"eclipse"}),
    ),
}

_GENERIC_RULE = _ACTIVITY_RULES["generic"]


def _rule_for(activity: str) -> ActivityRule:
    """Return the rule row for an activity, defaulting to the neutral generic
    rule for any unknown value (forward-compatible)."""
    return _ACTIVITY_RULES.get(activity, _GENERIC_RULE)
# Benefic-ruled signs (Moon, Mercury, Venus, Jupiter): a mildly favourable
# navamsa lagna when no stronger signal applies.
_BENEFIC_LORD_SIGNS = frozenset({
    "Cancer", "Gemini", "Virgo", "Taurus", "Libra", "Sagittarius", "Pisces",
})


def _navamsa_sign(longitude: float) -> str:
    """Classical continuous navamsa sign of a sidereal longitude: the zodiac is
    divided into 108 navamsas of 3°20'; navamsa N maps to sign (N mod 12).

    Computed as ``longitude * 9 / 30`` (multiply before divide) so that exact
    sign boundaries (30°, 60°, …) land on the correct navamsa rather than one
    early through floating-point error.
    """
    return utils.SIGNS[int(longitude * 9.0 / 30.0) % 12]


def _event_navamsha_factor(nav_sign: str, lagna_sign: str,
                           activity: ActivityCategory) -> tuple[bool, float]:
    """Score the event navamsa lagna. Returns (suitable, score_delta).

    Strongest signal first: Vargottama (navamsa lagna sign == rasi lagna sign),
    classically the most auspicious; else the sign NATURE matching the activity
    (movable/fixed/dual); else a benefic-ruled navamsa lagna. The magnitudes are
    a tuning choice (texts give a qualitative priority, not numbers); the
    *ordering* follows the classical priority.
    """
    if nav_sign == lagna_sign:                       # Vargottama
        return True, 0.08
    nature = _rule_for(activity).sign_nature
    if nature and nav_sign in nature:                # sign nature suits activity
        return True, 0.05
    if nav_sign in _BENEFIC_LORD_SIGNS:              # benefic navamsa lagna
        return True, 0.03
    return False, 0.0


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

_DAY_MINS = 24 * 60


def _hhmm_to_mins(hhmm: str) -> int:
    """Minutes after midnight of an ``HH:MM`` string.

    Hours past 23 are read as they stand: the scan states a vaara's
    after-midnight minutes on an EXTENDED clock (``25:30`` is 01:30 on the next
    civil date), see :func:`_ext_hhmm`.
    """
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _ext_hhmm(mins: int) -> str:
    """Render minutes on the extended clock of one vaara (no wrap at 24:00)."""
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _mins_to_hhmm(mins: int) -> str:
    mins = mins % (24 * 60)
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _in_window(time_mins: int, start_hhmm: str, end_hhmm: str) -> bool:
    s = _hhmm_to_mins(start_hhmm)
    e = _hhmm_to_mins(end_hhmm)
    if e > s:
        return s <= time_mins < e
    # spans midnight
    return time_mins >= s or time_mins < e


def _label_at(time_mins: int, windows: list[dict]) -> str | None:
    for w in windows:
        if _in_window(time_mins, w["start"], w["end"]):
            return w.get("label")
    return None


@utils.serialized_ephemeris
def _jd_for_local(date_str: str, time_mins: int, tz_offset: float) -> float:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    local_h = time_mins / 60.0
    utc_h = local_h - tz_offset
    return swe.julday(d.year, d.month, d.day, utc_h)


# ---------------------------------------------------------------------------
# Hora lord
# ---------------------------------------------------------------------------

def compute_hora_lord(date_str: str, time_mins: int, sunrise_hhmm: str) -> str:
    """The kala-hora lord at *time_mins* in the vaara that begins at sunrise on
    *date_str*.

    The vaara runs from sunrise to the next sunrise (the panchanga convention,
    "udayad udayam vaarah"), and its horas are counted from ITS sunrise: the
    first belongs to the vaara lord and the rest descend in the Chaldean order
    Saturn, Jupiter, Mars, Sun, Venus, Mercury, Moon (Surya Siddhanta
    ch. XII vv. 78-79, Burgess 1860). Equal sixty-minute horas, the 24th
    running on to the next sunrise, which can fall a minute or two more than
    24 hours later.

    *time_mins* counts from the local midnight that begins *date_str* and runs
    PAST 24:00 for the vaara's after-midnight hours (1500 is 01:00 on the next
    civil date). An instant before this vaara's sunrise belongs to the
    PREVIOUS vaara, with a different lord and a different sunrise, so it is
    refused rather than wrapped: wrapping it is exactly how a pre-dawn instant
    used to be given the lord of the day that had not yet begun.
    """
    sunrise = _hhmm_to_mins(sunrise_hhmm)
    if time_mins < sunrise:
        raise ValueError(
            f"minute {time_mins} precedes the sunrise ({sunrise_hhmm}) of the "
            f"vaara {date_str}; it belongs to the previous vaara"
        )
    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    day_lord = _WEEKDAY_LORDS[date_obj.strftime("%A")]
    hora_num = min((time_mins - sunrise) // 60, 23)
    return _CHALDEAN[(_CHALDEAN.index(day_lord) + hora_num) % 7]


# ---------------------------------------------------------------------------
# Lagna at a specific JD
# ---------------------------------------------------------------------------

@utils.serialized_ephemeris
def compute_lagna_at_jd(jd: float, lat: float, lon: float) -> tuple[str, str, float]:
    """Return (lagna_sign, lagna_lord, sidereal_ascendant_longitude) for the JD (UT)."""
    drik.set_ayanamsa_mode('LAHIRI')
    ayanamsa = drik.get_ayanamsa_value(jd)
    try:
        _, ascmc = swe.houses(jd, lat, lon, b"P")
    except Exception:
        logger.warning(
            "lagna_shuddhi_placidus_fallback_equatorial",
            extra={"lat": lat, "lon": lon}, exc_info=True,
        )
        _, ascmc = swe.houses(jd, lat, lon, b"E")
    sid_asc = (ascmc[0] - ayanamsa) % 360
    sign = utils.SIGNS[int(sid_asc // 30)]
    return sign, utils.get_sign_lord(sign), sid_asc


# ---------------------------------------------------------------------------
# Per-minute scoring
# ---------------------------------------------------------------------------

@utils.serialized_ephemeris
def _score_instant(
    jd: float,
    lagna_sign: str,
    lagna_lord: str,
    day_data: dict,
    time_mins: int,
    activity: ActivityCategory,
    lagna_long: float | None = None,
    birth_nakshatra: str | None = None,
    birth_moon_sign: str | None = None,
) -> tuple[float, dict]:
    """
    Score a single candidate instant. Returns (score 0..1, detail_dict).
    score = 0.0 means hard-disqualified (Rahu Kala / Yamaganda / Gulika).

    *day_data* is the VAARA that contains the instant (sunrise to the next
    sunrise), and *time_mins* counts from the local midnight that begins it,
    running past 24:00 for its after-midnight hours -- the scans build both
    with :class:`_ScanDays`. The tithi, karana and yoga are NOT taken from
    *day_data*: they are evaluated at *jd* itself (``panchanga_at_instant``),
    because each changes at any time of day.
    """
    # The Sun-Moon limbs IN FORCE AT THIS INSTANT (Surya Siddhanta ch. II
    # vv. 64-69). Computed first so every sample -- vetoed or not -- reports the
    # limbs of its own instant. No exception guard: see panchanga_at_instant.
    limbs = panchanga_at_instant(jd)

    inauspicious = day_data.get("inauspicious_periods", [])
    in_rahu = any(
        "Rahu" in (w.get("label") or "") and _in_window(time_mins, w["start"], w["end"])
        for w in inauspicious
    )
    in_yama = any(
        "Yamagan" in (w.get("label") or "") and _in_window(time_mins, w["start"], w["end"])
        for w in inauspicious
    )
    in_guli = any(
        "Gulika" in (w.get("label") or "") and _in_window(time_mins, w["start"], w["end"])
        for w in inauspicious
    )
    in_durm = any(
        "Durmuhurt" in (w.get("label") or "") and _in_window(time_mins, w["start"], w["end"])
        for w in inauspicious
    )
    in_varj = any(
        "Varjyam" in (w.get("label") or "") and _in_window(time_mins, w["start"], w["end"])
        for w in inauspicious
    )

    detail = {
        "in_rahu_kala": in_rahu,
        "in_yamaganda": in_yama,
        "in_gulika": in_guli,
        "in_durmuhurtam": in_durm,
        "in_varjyam": in_varj,
        "in_auspicious_muhurta": None,
        "chogadiya_label": None,
        "hora_lord": "",
        "lagna_lord_house": 0,
        "lagna_lord_dignity": "unknown",
        "malefics_in_lagna": 0,
        "tithi": limbs.tithi,
        "yoga": limbs.yoga,
        "panchanga_suitable": True,
        # Defaults for an instant hard-excluded BEFORE balam is computed — its
        # score is already 0.0/Avoid, so 'NoBirthData' (the no-penalty sentinel)
        # avoids a misleading band cap. Overwritten on the non-excluded path.
        "tara_bala": "NoBirthData",
        "chandra_bala": "NoBirthData",
        "event_navamsha": None,
        "event_navamsha_suitable": False,
        "hard_excluded": False,
    }

    if in_rahu or in_yama or in_guli:
        detail["hard_excluded"] = True
        return 0.0, detail

    # Absolute Rahu/Yama/Gulika veto could not be COMPUTED for this day → the
    # classical safety net is unverifiable, so the instant must not be
    # recommendable. Fail closed: hard-exclude (score 0.0 / band Avoid).
    if day_data.get("hard_gate_failed"):
        detail["hard_excluded"] = True
        return 0.0, detail

    # Per-activity hard vetoes (data-driven — see ActivityRule.hard_excludes).
    # Durmuhurtam/Varjyam (surgery), a locally-visible eclipse, Adhika Maasa, or
    # Bhadra (Vishti karana) disqualify the instant outright for the activities
    # that name them. Bhadra is avoided for marriage and other auspicious
    # beginnings (Muhurta Chintamani ch. 1, Shubhashubha Prakarana); it is a
    # karana, so it is tested AT THE INSTANT -- a Vishti beginning at 15:00
    # vetoes 17:00, and one that ended at 15:00 does not veto 17:00.
    rule = _rule_for(activity)
    he = rule.hard_excludes
    karana = limbs.karana
    # eclipse / adhik_maasa now carry bool | None. None == 'could not be
    # computed' → veto (fail closed), exactly like True; only an explicit False
    # clears the gate.
    if (("durm_varj" in he and (in_durm or in_varj))
            or ("eclipse" in he and day_data.get("is_eclipse_day") in (True, None))
            or ("adhik_maasa" in he and day_data.get("is_adhik_maasa") in (True, None))
            or ("vishti" in he and karana == "Vishti")):
        detail["hard_excluded"] = True
        return 0.0, detail

    in_auspicious = _label_at(time_mins, day_data.get("auspicious_muhurtas", []))
    chogadiya_label = _label_at(time_mins, day_data.get("chogadiya", []))
    hora_lord = compute_hora_lord(day_data["date"], time_mins, day_data["sunrise"])

    # Lagna lord transit position at this exact instant. No exception guard
    # here, deliberately: a graha position that cannot be computed for a
    # valid graha at a valid JD means the ephemeris layer itself is broken,
    # and the failure must SURFACE — a swallowed error here once scored
    # instants as if the lord limb were fine (house 0, dignity "neutral",
    # no signal that anything failed), which is wrong astrology reported as
    # fine. tests/test_graha_body_ids.py pins the propagation.
    lagna_sign_idx = utils.SIGNS.index(lagna_sign)
    # The lord-not-a-graha else-path (house 0 / "neutral") is unreachable in
    # practice: lagna_sign is always one of utils.SIGNS here, and every sign
    # lord in utils.SIGN_LORDS is a graha. If it were ever reached (an
    # unknown lord string), house 0 is a VISIBLE sentinel, not a silent one:
    # _ordinal(0) renders it as "unknown house" in the clearance prose, and
    # no house bonus is granted. It is deliberately not an exception path —
    # an unknown NAME is a data problem upstream, unlike a computation
    # failure for a known graha, which propagates (below).
    lord_house = 0
    lord_dignity = "neutral"
    if lagna_lord in utils.PLANETS:
        lord_lon = utils.graha_sidereal_longitude(jd, lagna_lord)
        lord_sign_idx = int(lord_lon // 30) % 12
        lord_house = (lord_sign_idx - lagna_sign_idx) % 12 + 1
        lord_dignity = utils.get_planet_dignity(lagna_lord, utils.SIGNS[lord_sign_idx])

    # Malefics in lagna sign at this instant — same no-swallow rule as above.
    malefics_in_lagna = 0
    for graha in _MALEFIC_GRAHAS:
        m_lon = utils.graha_sidereal_longitude(jd, graha)
        if int(m_lon // 30) % 12 == lagna_sign_idx:
            malefics_in_lagna += 1

    detail.update({
        "in_auspicious_muhurta": in_auspicious,
        "chogadiya_label": chogadiya_label,
        "hora_lord": hora_lord,
        "lagna_lord_house": lord_house,
        "lagna_lord_dignity": lord_dignity,
        "malefics_in_lagna": malefics_in_lagna,
    })

    # --- Base score ---
    score = 0.4

    if in_durm:
        score -= 0.12
    if in_varj:
        score -= 0.12

    # Lagna lord dignity
    dignity_bonus = {
        "exalted": 0.20, "moolatrikona": 0.15, "own sign": 0.15,
        "friendly": 0.08, "neutral": 0.0, "enemy": -0.08, "debilitated": -0.15,
    }.get(lord_dignity, 0.0)
    score += dignity_bonus

    # Lagna lord house (whole-sign from lagna)
    if lord_house in (1, 4, 7, 10):
        score += 0.15
    elif lord_house in (5, 9):
        score += 0.10
    elif lord_house in (2, 3, 11):
        score += 0.05
    elif lord_house in (6, 8, 12):
        score -= 0.15

    # In auspicious muhurta
    if in_auspicious:
        score += 0.12 if in_auspicious == "Abhijit Muhurta" else 0.08

    # Favorable chogadiya (per-activity weight — travel/vehicle value it more)
    if chogadiya_label in _FAVORABLE_CHOGADIYA:
        score += rule.chogadiya_bonus

    # Benefic hora lord
    if hora_lord in _FAVORABLE_HORA:
        score += 0.05

    # Malefics in lagna
    score -= min(malefics_in_lagna * 0.08, 0.16)

    # Activity-specific weighting (data-driven — see ActivityRule):
    # amplify the lagna-lord dignity weight, and credit a kendra-placed lagna
    # lord for the activities that ask for it.
    score += dignity_bonus * (rule.dignity_weight - 1.0)
    if lord_house in (1, 4, 7, 10):
        score += rule.kendra_lord_bonus

    # --- Muhurta factor gates. Classical priority (B.V. Raman, "Muhurtha";
    # Panchanga Shuddhi): toxic periods are an absolute veto (applied above as a
    # hard 0.0); nakshatra-based strength (Tara / Chandra Bala) is the primary
    # limb; tithi/yoga suitability is secondary; the Event Navamsha is a final
    # refinement. The penalty/bonus magnitudes are a tuning choice; their
    # ordering (Tara/Chandra >= tithi/yoga > navamsa) follows that priority. ---

    # Panchanga suitability, judged on the tithi and yoga AT THIS INSTANT:
    # Rikta tithis, Amavasya (new moon) and the avoided yogas deprioritise.
    # There is no 'could not be computed' arm any more: the limbs come from
    # panchanga_at_instant, which raises rather than returning a missing limb,
    # so a broken ephemeris fails the scan instead of being scored around.
    is_rikta = any(r in limbs.tithi for r in _RIKTA_TITHIS)
    is_amavasya = _AMAVASYA in limbs.tithi
    is_bad_yoga = limbs.yoga in _INAUSPICIOUS_YOGAS
    detail["panchanga_suitable"] = not (is_rikta or is_amavasya or is_bad_yoga)
    if is_rikta:
        score -= 0.10
    if is_amavasya:
        score -= 0.10
    if is_bad_yoga:
        score -= 0.10

    # Vaara (weekday) suitability — classical day-lord preference for the activity.
    vaara = (day_data.get("panchanga") or {}).get("vaara") or ""
    if vaara in rule.prefer_varas:
        score += _VARA_BONUS
    elif vaara in rule.avoid_varas:
        score -= _VARA_PENALTY

    # Tara Bala / Chandra Bala at this exact instant (parity with the family scan).
    # 'Unknown' (computation FAILED with birth data present) fails closed with a
    # penalty of the same magnitude as a classically-bad Tara. 'NoBirthData' (a
    # legitimate generic scan) carries NO penalty — there is no personal strength
    # to check.
    tara_label, chandra_str = compute_balam_at_jd(jd, birth_nakshatra, birth_moon_sign)
    detail["tara_bala"] = tara_label
    detail["chandra_bala"] = chandra_str
    if tara_label in _TARA_BAD or tara_label == "Unknown":
        score -= 0.12
    if chandra_str == "Inauspicious (Avoid)" or chandra_str == "Unknown":
        score -= 0.12
    elif chandra_str == "Good":
        score += 0.03

    # Event Navamsha — D9 of the rising sign at this instant; the minute-level
    # electional signal (Vargottama / sign-nature / benefic — see
    # _event_navamsha_factor).
    if lagna_long is not None:
        nav_sign = _navamsa_sign(lagna_long)
        suitable, nav_delta = _event_navamsha_factor(nav_sign, lagna_sign, activity)
        detail["event_navamsha"] = nav_sign
        detail["event_navamsha_suitable"] = suitable
        score += nav_delta

    return max(0.0, min(1.0, score)), detail


# ---------------------------------------------------------------------------
# Candidate window selection
# ---------------------------------------------------------------------------

def _candidate_minutes(day_data: dict) -> list[int]:
    """Sorted minutes covered by the auspicious and favourable-chogadiya windows.

    Read on the vaara's extended clock (see :class:`_ScanDays`): a minute after
    midnight comes back past 1440, never folded onto the start of the day it
    does not belong to.
    """
    auspicious = day_data.get("auspicious_muhurtas", [])
    chogadiya = [
        w for w in day_data.get("chogadiya", [])
        if w.get("label") in _FAVORABLE_CHOGADIYA
    ]
    minutes: set[int] = set()
    for window_list in (auspicious, chogadiya):
        for w in window_list:
            minutes.update(range(_hhmm_to_mins(w["start"]), _hhmm_to_mins(w["end"])))
    return sorted(minutes)


# ---------------------------------------------------------------------------
# Vedic days: every window on the date it falls on, every instant in its vaara
# ---------------------------------------------------------------------------
#
# compute_muhurat_for_day serves each window as bare wall-clock HH:MM, and the
# night ones run from this date's sunset to the NEXT date's sunrise. Read
# against the civil date that computed them, "02:00" from the night chogadiya
# of D was scored as 02:00 on D -- an instant in the night that began on the
# evening of D-1, with that night's labels, hora and weekday taken from the
# wrong day. Measured on the code before this change at Colombo, December 2026:
# every pre-dawn candidate carried the chogadiya of the following night, and a
# 00:00 candidate on Wednesday 16th was given Jupiter's hora instead of
# Mercury's (17th hora of Tuesday's vaara).
#
# So the scans place every window on one continuous minute axis, cut the axis
# into VAARAS -- sunrise to the next sunrise, the panchanga day -- and score an
# instant against the vaara that contains it, on that vaara's extended clock.

_WINDOW_LISTS = ("auspicious_muhurtas", "chogadiya", "inauspicious_periods")
_BRAHMA_LABEL = "Brahma Muhurtha"
_VARJYAM_LABEL = "Varjyam"


def _place_day_windows(day_data: dict, midnight: int) -> dict[str, list[tuple[int, int, dict]]]:
    """Place each window of one computed day on the scan's minute axis.

    *midnight* is the axis minute of that day's local midnight. Each window's
    DATE is fixed by its definition, because its wall-clock HH:MM cannot say:

    * Brahma Muhurtha is the two muhurtas BEFORE this day's sunrise.
    * Varjyam is a slice of the nakshatra in force at noon, so it can fall on
      the previous evening or after the coming midnight; its date comes from
      the unrendered float hours compute_muhurat_for_day hands over under
      ``VARJYAM_HOURS_KEY``. A day carrying a Varjyam window without them
      cannot be placed, and raises.
    * Every other window lies between this day's sunrise and the next one --
      the day windows, Godhuli at sunset, and the night chogadiya, Nishita,
      night Vijaya and night Durmuhurtam -- so one that reads earlier than
      this day's sunrise is after the coming midnight.

    A window whose start and end render to the same minute keeps the reading
    it has always had here: the whole civil day of the day that computed it.
    (The library returns such a zero-width Varjyam on a few days a year; for
    the surgery veto that reading fails closed, and it is not reinterpreted
    here.)

    Returns, per window list, ``(start, end, window)`` with ``end > start``.
    """
    sunrise = _hhmm_to_mins(day_data["sunrise"])
    placed: dict[str, list[tuple[int, int, dict]]] = {}
    for key in _WINDOW_LISTS:
        out = []
        for w in day_data.get(key, []):
            s, e = _hhmm_to_mins(w["start"]), _hhmm_to_mins(w["end"])
            if s == e:
                out.append((midnight, midnight + _DAY_MINS, w))
                continue
            label = w.get("label")
            if label == _BRAHMA_LABEL:
                start = s if s < sunrise else s - _DAY_MINS
            elif label == _VARJYAM_LABEL:
                hours = day_data.get(VARJYAM_HOURS_KEY)
                if hours is None:
                    raise ValueError(
                        f"the Varjyam window of {day_data.get('date')} carries no "
                        "float placement, so the date it falls on is unknown"
                    )
                start = s + _DAY_MINS * round((hours[0] * 60.0 - s) / _DAY_MINS)
            else:
                start = s if s >= sunrise else s + _DAY_MINS
            out.append((midnight + start, midnight + start + (e - s) % _DAY_MINS, w))
        placed[key] = out
    return placed


@dataclass(frozen=True)
class _Vaara:
    """One vaara, from its sunrise to the next, as the scorer reads it."""
    sunrise: int        # axis minute of this vaara's sunrise
    next_sunrise: int   # axis minute of the next sunrise (exclusive end)
    midnight: int       # axis minute of the local midnight that begins it
    # The day_data handed to the scorer for an instant before / after the
    # coming midnight. They differ only in the eclipse and Adhika Maasa flags,
    # which are answered per CIVIL date (an eclipse visible on that local
    # calendar day) and so follow the instant's own date.
    views: tuple[dict, dict]


class _ScanDays:
    """The vaaras a scan of civil dates *first* .. *last* needs, for one place.

    An instant on those dates lies in the vaaras that begin on *first* - 1
    (its pre-dawn hours) through *last*; their windows come from the days
    *first* - 1 through *last* + 1, because the night windows of a day reach
    into the next date and a Varjyam can lie on the previous evening (it is
    bounded by its nakshatra, at most about 27 hours either side of noon, so
    no further day can reach a requested date). Hence two neighbouring days
    are computed beyond the request -- and one of them can fail for the same
    reasons as a requested day (a polar day frame), which then fails the scan,
    naming that date.

    Days are computed LAZILY, as the vaaras that need them are asked for, so
    the solo scan interleaves one day's computation with the scoring of the
    vaara before it -- the same rhythm the scan had when it computed and scored
    a day at a time. Computing every day up front made a run of back-to-back
    day-sized lock holds at the start of a scan, and a concurrent chart request
    measurably waited behind it (tests/test_ephemeris_lock.py).
    """

    def __init__(self, place: drik.Place, first: date, last: date,
                 birth_nakshatra: str | None,
                 birth_moon_sign: str | None) -> None:
        self._place = place
        self._birth = (birth_nakshatra, birth_moon_sign)
        self.origin = first - timedelta(days=1)    # its midnight is axis 0
        self.last_day = last + timedelta(days=1)   # the last day computed
        self._days: dict[date, dict] = {}
        self._placed: dict[date, dict[str, list[tuple[int, int, dict]]]] = {}
        self._vaaras: dict[date, _Vaara] = {}

    def vaara_dates(self) -> list[date]:
        """The vaaras an instant on the requested dates can lie in, in order."""
        n = (self.last_day - self.origin).days
        return [self.origin + timedelta(days=k) for k in range(n)]

    def _day(self, d: date) -> dict:
        if d not in self._days:
            dd = compute_muhurat_for_day(self._place, d, *self._birth)
            self._days[d] = dd
            self._placed[d] = _place_day_windows(dd, (d - self.origin).days * _DAY_MINS)
        return self._days[d]

    def vaara(self, d: date) -> _Vaara:
        if d in self._vaaras:
            return self._vaaras[d]
        nxt = d + timedelta(days=1)
        midnight = (d - self.origin).days * _DAY_MINS
        lo = midnight + _hhmm_to_mins(self._day(d)["sunrise"])
        hi = midnight + _DAY_MINS + _hhmm_to_mins(self._day(nxt)["sunrise"])
        lists: dict[str, list[dict]] = {key: [] for key in _WINDOW_LISTS}
        # Only the neighbouring days can reach this vaara (see the class
        # docstring); each list keeps its served order, day by day.
        for f in (d + timedelta(days=k) for k in range(-2, 3)):
            if not self.origin <= f <= self.last_day:
                continue
            self._day(f)
            for key in _WINDOW_LISTS:
                for s, e, w in self._placed[f][key]:
                    s, e = max(s, lo), min(e, hi)
                    if e > s:
                        lists[key].append({
                            **w,
                            "start": _ext_hhmm(s - midnight),
                            "end": _ext_hhmm(e - midnight),
                        })
        view = {**self._days[d], **lists, "date": d.isoformat()}
        after_midnight = {
            **view,
            "is_eclipse_day": self._days[nxt].get("is_eclipse_day"),
            "is_adhik_maasa": self._days[nxt].get("is_adhik_maasa"),
        }
        self._vaaras[d] = _Vaara(lo, hi, midnight, (view, after_midnight))
        return self._vaaras[d]

    def candidates_in(self, d: date, first: date, last: date,
                      step_mins: int) -> list[tuple[str, int]]:
        """(civil date, minute of day) of the candidates of vaara *d* that fall
        on *first* .. *last*, in time order.

        The step is applied to the minute of the CIVIL day, as it always was,
        so samples land on genuine step-minute clock marks.
        """
        v = self.vaara(d)
        lo = (first - self.origin).days * _DAY_MINS
        hi = ((last - self.origin).days + 1) * _DAY_MINS
        out: list[tuple[str, int]] = []
        for m in _candidate_minutes(v.views[0]):
            axis = v.midnight + m
            if lo <= axis < hi and (axis % _DAY_MINS) % step_mins == 0:
                civil = self.origin + timedelta(days=axis // _DAY_MINS)
                out.append((civil.isoformat(), axis % _DAY_MINS))
        return out

    def candidates(self, first: date, last: date, step_mins: int) -> set[tuple[str, int]]:
        """Every candidate on *first* .. *last*, across all the vaaras."""
        out: set[tuple[str, int]] = set()
        for d in self.vaara_dates():
            out.update(self.candidates_in(d, first, last, step_mins))
        return out

    def locate(self, date_str: str, time_mins: int) -> tuple[dict, int]:
        """The vaara view containing a civil instant, and its extended-clock minute."""
        civil = date.fromisoformat(date_str)
        axis = (civil - self.origin).days * _DAY_MINS + time_mins
        for d in (civil, civil - timedelta(days=1)):
            if not self.origin <= d < self.last_day:
                continue
            v = self.vaara(d)
            if v.sunrise <= axis < v.next_sunrise:
                m = axis - v.midnight
                return v.views[0 if m < _DAY_MINS else 1], m
        raise LookupError(f"{date_str} {_mins_to_hhmm(time_mins)} is outside the scanned vaaras")


# ---------------------------------------------------------------------------
# Clearance summary
# ---------------------------------------------------------------------------

def _ordinal(n: int) -> str:
    if not n:
        return "unknown house"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _balam_disp(value: str | None) -> str:
    """Render a Tara/Chandra Bala value for prose, never leaking the literal
    sentinel strings 'Unknown' / 'NoBirthData' / 'None'."""
    if value in (None, "Unknown"):
        return "could not be computed"
    if value == "NoBirthData":
        return "not applicable (no birth data supplied)"
    return value


def _build_clearance_summary(sample: dict, activity: ActivityCategory) -> str:
    """Plain-English why-this-window summary built from a scored sample's factors.

    Defensive throughout: a limb that could not be computed says so, and the
    literal strings 'None' / 'Unknown' / 'NoBirthData' never reach the prose.
    """
    # Rahu/Yama/Gulika sentence — conditional on whether the absolute veto could
    # be computed for this day (hard_gate_failed carried onto the sample).
    if sample.get("hard_gate_failed"):
        rahu_sentence = (
            "Rahu Kala / Yamaganda / Gulika status could not be computed — "
            "treated as unverified."
        )
    else:
        rahu_sentence = "Clear of Rahu Kala, Yamaganda and Gulika."

    # Panchanga sentence — a None tithi/yoga means suitability cannot be verified.
    tithi_disp = sample.get("tithi") or "could not be computed"
    yoga_disp = sample.get("yoga") or "could not be computed"
    if sample.get("tithi") is None or sample.get("yoga") is None:
        pan = "panchanga suitability could not be verified"
    elif sample.get("panchanga_suitable", True):
        pan = "suitable"
    else:
        pan = "inauspicious (Rikta tithi, Amavasya or avoided yoga)"

    parts = [
        rahu_sentence,
        f"Panchanga: {tithi_disp}, yoga {yoga_disp} — {pan}.",
        f"Tara Bala: {_balam_disp(sample.get('tara_bala'))}; "
        f"Chandra Bala: {_balam_disp(sample.get('chandra_bala'))}.",
        f"Rising {sample.get('lagna_sign')} (lord {sample.get('lagna_lord')}) in the "
        f"{_ordinal(sample.get('lagna_lord_house', 0))}, {sample.get('lagna_lord_dignity')}.",
    ]
    nav = sample.get("event_navamsha")
    if nav:
        fit = "suitable" if sample.get("event_navamsha_suitable") else "not specially indicated"
        parts.append(f"Event Navamsha lagna {nav} ({fit} for {activity}).")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Quality band + factor breakdown (additive presentation over the 0..1 score)
# ---------------------------------------------------------------------------

Band = Literal["Excellent", "Good", "Fair", "Avoid"]

# Tara levels that are classically favourable (bare label, no description).
# _TARA_BAD (Janma/Vipat/Pratyak/Naidhana) is defined further down for the family
# gate; both are resolved at call time, so order of definition does not matter.
_TARA_GOOD = frozenset({"Sampat", "Kshema", "Sadhana", "Mitra", "Paramitra"})
_BAND_ORDER = {"Avoid": 0, "Fair": 1, "Good": 2, "Excellent": 3}

# Maximum number of diversified alternatives to return alongside the best instant.
MAX_ALTERNATIVES = 5
# Two alternatives (or an alternative vs best) on the SAME date must be at least
# this many minutes apart.  ±5 min is the tolerance band half-width; 60 min
# guarantees alternatives are not minute-adjacent clusters of the best or each other.
# Distinct dates are always allowed (no same-day constraint across dates).
ALT_MIN_SEPARATION_MINS = 60


def derive_band(score: float, sample: dict) -> Band:
    """Map a 0..1 score + its classical signals onto a four-level quality band.

    Hybrid rule — nakshatra strength dominates, then score granularity:
      * a hard inauspicious period (Rahu/Yama/Gulika) or a zero score -> Avoid
      * bad Tara Bala (Janma/Vipat/Pratyak/Naidhana) or Chandra "Avoid" -> at most Fair
      * a FAILED Tara/Chandra compute ('Unknown', birth data expected) -> at most
        Fair (fail closed). 'NoBirthData' (a generic scan) does NOT cap.
      * else by score: >=0.85 Excellent, >=0.60 Good, otherwise Fair
    """
    if (score <= 0.0 or sample.get("in_rahu_kala")
            or sample.get("in_yamaganda") or sample.get("in_gulika")):
        return "Avoid"
    if (sample.get("tara_bala") in _TARA_BAD
            or sample.get("tara_bala") == "Unknown"
            or sample.get("chandra_bala") == "Inauspicious (Avoid)"
            or sample.get("chandra_bala") == "Unknown"):
        return "Fair"
    if score >= 0.85:
        return "Excellent"
    if score >= 0.60:
        return "Good"
    return "Fair"


def _factor(name: str, impact: str, detail: str) -> dict:
    return {"name": name, "impact": impact, "detail": detail}


def build_factors(sample: dict) -> list[dict]:
    """Compact, ordered list of the salient classical contributors for a sample.

    Pure presentation: reads the signals already on the scored sample (no
    re-computation). Classical priority — toxic-period clearance, Tara/Chandra
    Bala, panchanga (tithi/yoga), lagna-lord dignity & house, then the finer
    muhurta/chogadiya/navamsa refinements. Only non-neutral signals are emitted.
    """
    factors: list[dict] = []

    # Toxic-period clearance (the hard gate the scan already enforces).
    if not (sample.get("in_rahu_kala") or sample.get("in_yamaganda")
            or sample.get("in_gulika")):
        factors.append(_factor("Inauspicious periods", "positive",
                               "Clear of Rahu Kala, Yamaganda and Gulika."))
    else:
        factors.append(_factor("Inauspicious periods", "negative",
                               "Falls in Rahu Kala, Yamaganda or Gulika."))
    if sample.get("in_durmuhurtam"):
        factors.append(_factor("Durmuhurtam", "negative", "Within Durmuhurtam."))
    if sample.get("in_varjyam"):
        factors.append(_factor("Varjyam", "negative", "Within Varjyam."))

    # Tara Bala. 'Unknown' (failed compute) is a negative factor; 'NoBirthData'
    # (generic scan, no birth data) emits nothing.
    tara = sample.get("tara_bala")
    if tara in _TARA_GOOD:
        factors.append(_factor("Tara Bala", "positive", f"{tara} — favourable."))
    elif tara in _TARA_BAD:
        factors.append(_factor("Tara Bala", "negative", f"{tara} — unfavourable."))
    elif tara == "Unknown":
        factors.append(_factor("Tara Bala", "negative",
                               "Could not be computed — personal suitability unverified."))

    # Chandra Bala. 'Unknown' (failed compute) is a negative factor; 'NoBirthData'
    # emits nothing.
    chandra = sample.get("chandra_bala")
    if chandra == "Good":
        factors.append(_factor("Chandra Bala", "positive",
                               "Moon well placed from the birth sign."))
    elif chandra == "Inauspicious (Avoid)":
        factors.append(_factor("Chandra Bala", "negative",
                               "Moon poorly placed from the birth sign."))
    elif chandra == "Unknown":
        factors.append(_factor("Chandra Bala", "negative",
                               "Chandra Bala could not be computed."))

    # Panchanga (tithi / yoga) suitability — three-valued. A None limb (could not
    # be computed) is a distinct negative factor; an unsuitable-but-computed pair
    # keeps the Rikta/Amavasya/avoided-yoga wording; only a computed AND suitable
    # pair is positive. f-strings guard None so the literal 'None' never renders.
    tithi_disp = sample.get("tithi")
    yoga_disp = sample.get("yoga")
    limb_missing = tithi_disp is None or yoga_disp is None
    if not sample.get("panchanga_suitable", True) and limb_missing:
        factors.append(_factor("Panchanga", "negative",
                               "Tithi or yoga could not be computed."))
    elif sample.get("panchanga_suitable", True):
        factors.append(_factor("Panchanga", "positive",
                               f"{tithi_disp}, {yoga_disp} yoga — suitable."))
    else:
        factors.append(_factor("Panchanga", "negative",
                               f"{tithi_disp}, {yoga_disp} yoga — "
                               "Rikta tithi, Amavasya or avoided yoga."))

    # Lagna-lord dignity.
    dignity = sample.get("lagna_lord_dignity")
    if dignity in ("exalted", "moolatrikona", "own sign", "friendly"):
        factors.append(_factor("Lagna lord dignity", "positive",
                               f"Lord {sample.get('lagna_lord')} {dignity}."))
    elif dignity in ("enemy", "debilitated"):
        factors.append(_factor("Lagna lord dignity", "negative",
                               f"Lord {sample.get('lagna_lord')} {dignity}."))

    # Lagna-lord house (whole-sign from lagna).
    house = sample.get("lagna_lord_house") or 0
    if house in (1, 4, 7, 10, 5, 9):
        factors.append(_factor("Lagna lord house", "positive",
                               f"Lord in the {_ordinal(house)} (kendra/trikona)."))
    elif house in (6, 8, 12):
        factors.append(_factor("Lagna lord house", "negative",
                               f"Lord in the {_ordinal(house)} (dusthana)."))

    # Auspicious muhurta window.
    musec = sample.get("in_auspicious_muhurta")
    if musec:
        factors.append(_factor("Muhurta", "positive", f"Within {musec}."))

    # Favourable chogadiya.
    if sample.get("chogadiya_label") in _FAVORABLE_CHOGADIYA:
        factors.append(_factor("Chogadiya", "positive", f"{sample.get('chogadiya_label')}."))

    # Event Navamsha refinement.
    if sample.get("event_navamsha_suitable"):
        factors.append(_factor("Event Navamsha", "positive",
                               f"Navamsa lagna {sample.get('event_navamsha')} suits the activity."))

    return factors


def _enrich_sample(sample: dict) -> dict:
    """Attach score_100 + band + factors to a scored sample dict, in place."""
    sample["score_100"] = round(sample.get("score", 0.0) * 100)
    sample["band"] = derive_band(sample.get("score", 0.0), sample)
    sample["factors"] = build_factors(sample)
    return sample


def _select_alternatives(ranked: list[dict], best: dict,
                         score_key: str = "score") -> list[dict]:
    """Pick up to MAX_ALTERNATIVES diversified records from a score-desc ranked list.

    `ranked` MUST be sorted descending by the caller's score key with a
    deterministic tie-break, and `best` MUST be `ranked[0]` — so no alternative
    can outscore the recommendation. Solo sorts by (-score, instant); family
    passes its gate-matched pool sorted by (-min_score, -mean_score, instant)
    with score_key='min_score' (mean_score is intentionally a finer tie-break
    than instant-only ordering).

    Diversification rule (deterministic):
      * never include `best` itself
      * an alternative is REJECTED if it lies within ALT_MIN_SEPARATION_MINS of
        ANY already-accepted instant (including `best`) ON THE SAME DATE.
        Different date => always far enough.
      * walk `ranked` in order; greedily accept the highest-scoring survivor.
    Returns accepted records (still the raw scored dicts).
    """
    accepted_keys: list[tuple[str, int]] = []  # (date_str, mins)
    b_date, b_time = best["instant"].split(" ")
    accepted_keys.append((b_date, _hhmm_to_mins(b_time)))
    out: list[dict] = []
    for rec in ranked:
        if rec is best or rec["instant"] == best["instant"]:
            continue
        r_date, r_time = rec["instant"].split(" ")
        r_mins = _hhmm_to_mins(r_time)
        too_close = any(
            d == r_date and abs(m - r_mins) < ALT_MIN_SEPARATION_MINS
            for d, m in accepted_keys
        )
        if too_close:
            continue
        accepted_keys.append((r_date, r_mins))
        out.append(rec)
        if len(out) >= MAX_ALTERNATIVES:
            break
    return out


def _tolerance_window(center: dict, same_pool: list[dict], label: str,
                      score_key: str = "score") -> dict:
    """Build a [start,end) HH:MM window around `center` using the existing
    ±5min / 0.85*center_score contiguous-run rule, restricted to same-date pool."""
    c_date, c_time = center["instant"].split(" ")
    c_mins = _hhmm_to_mins(c_time)
    c_score = center[score_key]
    threshold = 0.85 * c_score
    band_start = band_end = c_mins
    for s in sorted(same_pool, key=lambda r: r["instant"], reverse=True):
        sd, st = s["instant"].split(" ")
        if sd != c_date:
            continue
        sm = _hhmm_to_mins(st)
        if sm > c_mins:
            continue
        if c_mins - sm > 5:
            break
        if s[score_key] >= threshold:
            band_start = min(band_start, sm)
    for s in sorted(same_pool, key=lambda r: r["instant"]):
        sd, st = s["instant"].split(" ")
        if sd != c_date:
            continue
        sm = _hhmm_to_mins(st)
        if sm < c_mins:
            continue
        if sm - c_mins > 5:
            break
        if s[score_key] >= threshold:
            band_end = max(band_end, sm)
    return {"start": _mins_to_hhmm(band_start),
            "end": _mins_to_hhmm(band_end + 1), "label": label}


def _family_band(min_score: float, consensus_quality: str,
                 per_member: list[dict]) -> Band:
    """Joint band: the weakest member governs; a best-effort consensus caps at Fair."""
    if min_score <= 0.0:
        return "Avoid"
    worst: Band = "Excellent"
    for md in per_member:
        b = derive_band(md.get("score", 0.0), md)
        if _BAND_ORDER[b] < _BAND_ORDER[worst]:
            worst = b
    if consensus_quality == "best_effort" and _BAND_ORDER[worst] > _BAND_ORDER["Fair"]:
        return "Fair"
    return worst


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------

def scan_lagna_shuddhi(
    lat: float,
    lon: float,
    tz_offset: float,
    birth_nakshatra: str | None,
    birth_moon_sign: str | None,
    start_date: str,
    end_date: str,
    activity: ActivityCategory = "generic",
    step_seconds: int = 60,
) -> dict:
    """
    Scan all candidate auspicious windows across the date range at `step_seconds`
    resolution. Returns the best-scored instant + a tolerance band + top samples.

    Returns a dict with keys:
      best_instant, best_window, top_samples (list, up to 20 best)
    Each sample dict has all LagnaShuddhiSample fields.
    """
    place = utils.make_place("scan", lat, lon, tz_offset)
    step_mins = max(1, step_seconds // 60)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

    all_samples: list[dict] = []

    # Every candidate is a CIVIL instant on start_date .. end_date, scored
    # against the vaara that contains it (see _ScanDays). The step filters the
    # actual minute of the civil day, not an enumeration index, so samples
    # land on genuine step_mins-minute clock marks.
    days = _ScanDays(place, start_dt, end_dt, birth_nakshatra, birth_moon_sign)
    candidates = (
        c for d in days.vaara_dates()
        for c in days.candidates_in(d, start_dt, end_dt, step_mins)
    )
    for date_str, time_mins in candidates:
        day_data, vaara_mins = days.locate(date_str, time_mins)
        jd = _jd_for_local(date_str, time_mins, tz_offset)
        lagna_sign, lagna_lord, lagna_long = compute_lagna_at_jd(jd, lat, lon)
        score, detail = _score_instant(
            jd, lagna_sign, lagna_lord, day_data, vaara_mins, activity,
            lagna_long=lagna_long,
            birth_nakshatra=birth_nakshatra,
            birth_moon_sign=birth_moon_sign,
        )
        all_samples.append({
            "instant": f"{date_str} {_mins_to_hhmm(time_mins)}",
            "lagna_sign": lagna_sign,
            "lagna_lord": lagna_lord,
            "lagna_lord_house": detail["lagna_lord_house"],
            "lagna_lord_dignity": detail["lagna_lord_dignity"],
            "hora_lord": detail["hora_lord"],
            "chogadiya_label": detail["chogadiya_label"],
            "in_rahu_kala": detail["in_rahu_kala"],
            "in_yamaganda": detail["in_yamaganda"],
            "in_gulika": detail["in_gulika"],
            "in_durmuhurtam": detail["in_durmuhurtam"],
            "in_varjyam": detail["in_varjyam"],
            "in_auspicious_muhurta": detail["in_auspicious_muhurta"],
            "tara_bala": detail["tara_bala"],
            "chandra_bala": detail["chandra_bala"],
            "tithi": detail["tithi"],
            "yoga": detail["yoga"],
            "panchanga_suitable": detail["panchanga_suitable"],
            # Carried so the clearance prose can report an unverifiable
            # absolute-veto day (hard-gate degraded) instead of falsely
            # claiming 'Clear of Rahu Kala …'.
            "hard_gate_failed": bool(day_data.get("hard_gate_failed")),
            "event_navamsha": detail["event_navamsha"],
            "event_navamsha_suitable": detail["event_navamsha_suitable"],
            "score": round(score, 4),
        })

    if not all_samples:
        # Fallback: no auspicious windows found — return a zero-scored placeholder
        return {
            "best_instant": None,
            "best_window": None,
            "top_samples": [],
            "clearance_summary": None,
            "alternatives": [],
        }

    # Sort by score descending, instant-ascending tie-break — explicit so the
    # contracted alternatives ordering never depends on insertion order.
    ranked = sorted(all_samples, key=lambda s: (-s["score"], s["instant"]))
    best = ranked[0]

    # Tolerance band: contiguous run of samples around best_instant where
    # score >= 0.85 * best_score and within ±5 minutes of best_instant.
    # Refactored to _tolerance_window for reuse by alternatives.
    best_window = _tolerance_window(best, all_samples, f"Best window for {activity}")

    # Enrich only the samples we return (best + up to 20), never all candidates.
    returned = ranked[:20]
    for _s in returned:
        _enrich_sample(_s)

    # Diversified alternatives: up to MAX_ALTERNATIVES non-adjacent instants.
    alt_recs = _select_alternatives(ranked, best, score_key="score")
    for a in alt_recs:
        _enrich_sample(a)            # ensures score_100/band present
    alternatives = [{
        "instant": a["instant"],
        "score": round(a["score"], 4),
        "score_100": a["score_100"],
        "band": a["band"],
        "window": _tolerance_window(a, all_samples, "Alternative window", "score"),
    } for a in alt_recs]

    return {
        "best_instant": best,
        "best_window": best_window,
        "top_samples": returned,
        "clearance_summary": _build_clearance_summary(best, activity),
        "alternatives": alternatives,
    }


# ---------------------------------------------------------------------------
# Per-instant Tara / Chandra Bala helper (reuses muhurat.py constants)
# ---------------------------------------------------------------------------

def compute_balam_at_jd(
    jd: float,
    birth_nakshatra: str | None,
    birth_moon_sign: str | None,
) -> tuple[str, str]:
    """Return (tara_label, chandra_str) for the Moon's position at *jd*.

    Uses the same formula as the personal-balam block of
    ``compute_muhurat_for_day`` in muhurat.py — the ``_TARA_BALA_LEVELS``
    lookup and the chandra-bala banding beside it.  tara_label is the
    bare label string (e.g. "Vipat") without the parenthesised description.
    chandra_str is one of "Good", "Neutral", or "Inauspicious (Avoid)".

    Two non-numeric sentinels distinguish the two legitimate states the consumer
    must treat differently:
      * ("NoBirthData", "NoBirthData") when no birth data was supplied — a
        legitimate generic scan with no personal strength to check (NO penalty,
        NO band cap).
      * "Unknown" for a limb whose computation FAILED despite birth data being
        present — fail closed (penalty + band capped at Fair).
    """
    if not birth_nakshatra or not birth_moon_sign:
        return "NoBirthData", "NoBirthData"

    # --- Tara Bala ---
    try:
        transit_moon_lon = utils.graha_sidereal_longitude(jd, "Moon")
        transit_star = int(transit_moon_lon // (360 / 27)) % 27 + 1  # 1-27
        birth_star_idx = utils.NAKSHATRAS.index(birth_nakshatra) + 1
        tb_div = (((transit_star - birth_star_idx + 27) % 27) + 1) % 9
        tb_label, _ = _TARA_BALA_LEVELS.get(tb_div, ("Unknown", "Neutral"))
    except Exception:
        tb_label = "Unknown"

    # --- Chandra Bala ---
    try:
        transit_moon_lon = utils.graha_sidereal_longitude(jd, "Moon")
        transit_moon_sign_idx = int(transit_moon_lon // 30) % 12
        birth_moon_sign_idx = utils.SIGNS.index(birth_moon_sign)
        diff = (transit_moon_sign_idx - birth_moon_sign_idx) % 12 + 1
        if diff in (1, 3, 6, 7, 10, 11):
            chandra_str = "Good"
        elif diff in (2, 5, 9):
            chandra_str = "Neutral"
        else:
            chandra_str = "Inauspicious (Avoid)"
    except Exception:
        chandra_str = "Unknown"

    return tb_label, chandra_str


# ---------------------------------------------------------------------------
# Hard-gate constants for family scan
# ---------------------------------------------------------------------------

# The four classically inauspicious Taras: Janma (1st, "Not Good" — danger to
# the body, avoided for new undertakings), Vipat (3rd, "Bad"), Pratyak (5th,
# "Not Good") and Naidhana (7th, "Totally Bad"). The 9-fold cycle has exactly
# these four avoid-Taras; the other five (Sampat/Kshema/Sadhana/Mitra/Paramitra)
# are favourable. All four deprioritise uniformly here (penalty + band cap at
# Fair) — the descriptive grading ("Not Good" < "Bad" < "Totally Bad") is not
# modelled separately.
_TARA_BAD = {"Janma", "Vipat", "Pratyak", "Naidhana"}


# ---------------------------------------------------------------------------
# Family (multi-person) joint scan
# ---------------------------------------------------------------------------

def scan_family_lagna_shuddhi(
    members: list[dict],
    start_date: str,
    end_date: str,
    activity: ActivityCategory = "generic",
    step_seconds: int = 60,
) -> dict:
    """Deterministic joint muhurat scan for 2-6 family members.

    Each member dict must have keys:
      name, lat, lon, tz_offset, birth_nakshatra, birth_moon_sign

    Returns a dict with:
      instant: "YYYY-MM-DD HH:MM" | None
      best_window: {start, end, label} | None
      score: float
      per_member: list of per-member sample dicts
      consensus_quality: "strict" | "best_effort"
      compromised_members: list[str]
    """
    step_mins = max(1, step_seconds // 60)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Each member's vaaras over the range, at that member's own place (see
    # _ScanDays): an instant is scored for every member against the vaara that
    # contains it at THAT member's place.
    member_days = [
        _ScanDays(
            utils.make_place(m["name"], m["lat"], m["lon"], m["tz_offset"]),
            start_dt, end_dt, m.get("birth_nakshatra"), m.get("birth_moon_sign"),
        )
        for m in members
    ]

    # Collect candidate (date_str, time_mins) pairs = UNION across all members;
    # the step filters the minute of the civil day, as in scan_lagna_shuddhi.
    candidate_set: set[tuple[str, int]] = set()
    for md in member_days:
        candidate_set |= md.candidates(start_dt, end_dt, step_mins)

    # Sort candidates for determinism.
    candidates = sorted(candidate_set)

    def _score_candidate(date_str: str, time_mins: int) -> dict | None:
        """Score a single (date, minute) across all members.

        Returns None if the instant is hard-excluded for ANY member
        (Rahu/Yama/Gulika flags from _score_instant returning 0.0).
        Otherwise returns a scored record.
        """
        member_scores: list[float] = []
        member_details: list[dict] = []

        for idx, m in enumerate(members):
            dd, vaara_mins = member_days[idx].locate(date_str, time_mins)
            jd = _jd_for_local(date_str, time_mins, m["tz_offset"])
            lagna_sign, lagna_lord, lagna_long = compute_lagna_at_jd(jd, m["lat"], m["lon"])
            score, detail = _score_instant(
                jd, lagna_sign, lagna_lord, dd, vaara_mins, activity,
                lagna_long=lagna_long,
                birth_nakshatra=m.get("birth_nakshatra"),
                birth_moon_sign=m.get("birth_moon_sign"),
            )
            # Hard-exclude if Rahu / Yama / Gulika (or surgery Durm/Varj) for this member.
            if detail.get("hard_excluded"):
                return None

            member_scores.append(score)
            member_details.append({
                "name": m["name"],
                "instant": f"{date_str} {_mins_to_hhmm(time_mins)}",
                "lagna_sign": lagna_sign,
                "lagna_lord": lagna_lord,
                "lagna_lord_house": detail["lagna_lord_house"],
                "lagna_lord_dignity": detail["lagna_lord_dignity"],
                "hora_lord": detail["hora_lord"],
                "chogadiya_label": detail["chogadiya_label"],
                "in_rahu_kala": detail["in_rahu_kala"],
                "in_yamaganda": detail["in_yamaganda"],
                "in_gulika": detail["in_gulika"],
                "in_durmuhurtam": detail["in_durmuhurtam"],
                "in_varjyam": detail["in_varjyam"],
                "in_auspicious_muhurta": detail["in_auspicious_muhurta"],
                "score": round(score, 4),
                "tara_bala": detail["tara_bala"],
                "chandra_bala": detail["chandra_bala"],
                "tithi": detail["tithi"],
                "yoga": detail["yoga"],
                "panchanga_suitable": detail["panchanga_suitable"],
                # See scan_lagna_shuddhi: carried for the clearance prose.
                "hard_gate_failed": bool(dd.get("hard_gate_failed")),
                "event_navamsha": detail["event_navamsha"],
                "event_navamsha_suitable": detail["event_navamsha_suitable"],
            })

        min_score = min(member_scores)
        mean_score = sum(member_scores) / len(member_scores)
        instant_str = f"{date_str} {_mins_to_hhmm(time_mins)}"
        return {
            "instant": instant_str,
            "min_score": min_score,
            "mean_score": mean_score,
            "per_member": member_details,
        }

    def _passes_balam_gate(record: dict) -> tuple[bool, list[str]]:
        """Return (passes, compromised_names).

        Fails (returns False) if ANY member has Tara in _TARA_BAD, a FAILED
        Tara/Chandra compute ('Unknown'), or Chandra == "Inauspicious (Avoid)".
        A failed compute is fail-closed: the member is compromised so the
        consensus is best_effort, not strict. 'NoBirthData' members (generic
        scan, no birth data) are NOT compromised.
        """
        bad = []
        for md in record["per_member"]:
            if (md["tara_bala"] in _TARA_BAD
                    or md["tara_bala"] == "Unknown"
                    or md["chandra_bala"] == "Inauspicious (Avoid)"
                    or md["chandra_bala"] == "Unknown"):
                bad.append(md["name"])
        return (len(bad) == 0), bad

    # --- First pass: score all candidates, drop hard-excluded ones ---
    all_records: list[dict] = []
    for date_str, time_mins in candidates:
        rec = _score_candidate(date_str, time_mins)
        if rec is not None:
            all_records.append(rec)

    if not all_records:
        # Nothing survived even the hard gate.
        return {
            "instant": None,
            "best_window": None,
            "score": 0.0,
            "score_100": 0,
            "band": "Avoid",
            "per_member": [],
            "consensus_quality": "best_effort",
            "compromised_members": [],
            "clearance_summary": None,
            "alternatives": [],
        }

    # Stable sort key: (-min_score, -mean_score, instant_str)
    all_records.sort(key=lambda r: (-r["min_score"], -r["mean_score"], r["instant"]))

    # --- Second pass: apply balam gate ---
    strict_records = [r for r in all_records if _passes_balam_gate(r)[0]]

    if strict_records:
        # At least one instant passes all gates.
        best = strict_records[0]
        consensus_quality = "strict"
        compromised_members: list[str] = []
    else:
        # Best-effort: use top record from hard-gated list, note bad balam.
        best = all_records[0]
        consensus_quality = "best_effort"
        _, compromised_members = _passes_balam_gate(best)

    best_instant_str = best["instant"]
    best_min_score = best["min_score"]
    best_date = best_instant_str.split(" ")[0]
    best_time = best_instant_str.split(" ")[1]
    best_mins_val = _hhmm_to_mins(best_time)

    # --- Tolerance band (same ±5 min / 0.85 × best logic as single-person) ---
    # Only consider records from the same date as the best instant.
    same_day = [r for r in all_records if r["instant"].startswith(best_date + " ")]
    threshold = 0.85 * best_min_score

    band_start = best_mins_val
    band_end = best_mins_val

    for rec in sorted(same_day, key=lambda r: r["instant"], reverse=True):
        s_mins = _hhmm_to_mins(rec["instant"].split(" ")[1])
        if s_mins > best_mins_val:
            continue
        if best_mins_val - s_mins > 5:
            break
        if rec["min_score"] >= threshold:
            band_start = min(band_start, s_mins)

    for rec in sorted(same_day, key=lambda r: r["instant"]):
        s_mins = _hhmm_to_mins(rec["instant"].split(" ")[1])
        if s_mins < best_mins_val:
            continue
        if s_mins - best_mins_val > 5:
            break
        if rec["min_score"] >= threshold:
            band_end = max(band_end, s_mins)

    best_window = {
        "start": _mins_to_hhmm(band_start),
        # band_end is the last qualifying minute; +1 yields an EXCLUSIVE end
        # (the first non-qualifying minute), so the interval is [start, end).
        "end": _mins_to_hhmm(band_end + 1),
        "label": f"Best joint window for {activity}",
    }

    for _md in best["per_member"]:
        _enrich_sample(_md)

    # Diversified alternatives — window=None for family (per contract).
    # Pool matches the recommendation's gate: a strict consensus draws
    # alternatives only from balam-passing records (best is strict_records[0],
    # so no alternative can outscore it); a best_effort consensus uses the full
    # hard-gated pool (best is all_records[0] — again the pool maximum). Every
    # record in the chosen pool shares the consensus gate outcome, so
    # consensus_quality is the correct per-alternative band quality.
    alt_pool = strict_records if consensus_quality == "strict" else all_records
    alt_recs = _select_alternatives(alt_pool, best, score_key="min_score")
    alternatives = [{
        "instant": a["instant"],
        "score": round(a["min_score"], 4),
        "score_100": round(a["min_score"] * 100),
        "band": _family_band(a["min_score"], consensus_quality, a["per_member"]),
        "window": None,
    } for a in alt_recs]

    return {
        "instant": best_instant_str,
        "best_window": best_window,
        "score": round(best_min_score, 4),
        "score_100": round(best_min_score * 100),
        "band": _family_band(best_min_score, consensus_quality, best["per_member"]),
        "per_member": best["per_member"],
        "consensus_quality": consensus_quality,
        "compromised_members": compromised_members,
        "clearance_summary": (
            f"Joint {consensus_quality} window for {len(members)} members. "
            + _build_clearance_summary(best["per_member"][0], activity)
            if best.get("per_member") else None
        ),
        "alternatives": alternatives,
    }
