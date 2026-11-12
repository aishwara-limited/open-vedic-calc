"""
Ashtakoota Milan (8-kuta marriage compatibility) and related calculations.
All logic is deterministic — no LLM calls.

BPHS does not define the koota tables. The eight-koota scheme, its 36 points
and the Nadi, Gana and Tara rules below follow the marriage chapter
(Vivaha-prakarana) of Muhurta Chintamani (Daivajna Rama, 1600 CE), as
tabulated in common professional use. Each table cites its rule where it is
defined, and tests/test_ashtakoota_classical_tables.py pins it, nakshatra by
nakshatra, against the classical grouping typed in by hand.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import utils
from .chart import ChartSnapshot
from .dashas import vimshottari_mahadashas

# ---------------------------------------------------------------------------
# Classical data tables
# ---------------------------------------------------------------------------

# Gana (temperament) of each nakshatra. Nine per gana (Muhurta Chintamani,
# Vivaha-prakarana, gana-koota): the three Purvas and the three Uttaras are
# all manushya, together with Bharani, Rohini and Ardra.
NAKSHATRA_GANA: dict[str, str] = {
    "Ashwini": "deva",          "Bharani": "manushya",      "Krittika": "rakshasa",
    "Rohini": "manushya",       "Mrigashira": "deva",       "Ardra": "manushya",
    "Punarvasu": "deva",        "Pushya": "deva",           "Ashlesha": "rakshasa",
    "Magha": "rakshasa",        "Purva Phalguni": "manushya","Uttara Phalguni": "manushya",
    "Hasta": "deva",            "Chitra": "rakshasa",        "Swati": "deva",
    "Vishakha": "rakshasa",     "Anuradha": "deva",          "Jyeshtha": "rakshasa",
    "Mula": "rakshasa",         "Purva Ashadha": "manushya", "Uttara Ashadha": "manushya",
    "Shravana": "deva",         "Dhanishta": "rakshasa",     "Shatabhisha": "rakshasa",
    "Purva Bhadrapada": "manushya","Uttara Bhadrapada": "manushya","Revati": "deva",
}

# Nadi (Muhurta Chintamani, Vivaha-prakarana, nadi-koota). The 27 nakshatras
# run through the three nadis in a SERPENTINE order -- Aadi, Madhya, Antya,
# Antya, Madhya, Aadi, repeated from Ashwini -- not a plain cycle of three:
#   Aadi:   Ashwini, Ardra, Punarvasu, Uttara Phalguni, Hasta, Jyeshtha,
#           Mula, Shatabhisha, Purva Bhadrapada
#   Madhya: Bharani, Mrigashira, Pushya, Purva Phalguni, Chitra, Anuradha,
#           Purva Ashadha, Dhanishta, Uttara Bhadrapada
#   Antya:  Krittika, Rohini, Ashlesha, Magha, Swati, Vishakha,
#           Uttara Ashadha, Shravana, Revati
# A plain index % 3 agrees on the Madhya stars only and swaps Aadi and Antya
# for Rohini, Ardra, Magha, Uttara Phalguni, Vishakha, Jyeshtha, Shravana and
# Shatabhisha, which inverts the 8-point nadi koota for about one pair in five.
_NADI_NAMES = ("Aadi", "Madhya", "Antya")
_NADI_SERPENTINE = (0, 1, 2, 2, 1, 0)


def _nakshatra_nadi(nak: str) -> str:
    idx = utils.NAKSHATRAS.index(nak)
    return _NADI_NAMES[_NADI_SERPENTINE[idx % 6]]


# Yoni: each nakshatra has an (animal, gender) pair
NAKSHATRA_YONI: dict[str, tuple[str, str]] = {
    "Ashwini":          ("horse",    "male"),
    "Bharani":          ("elephant", "male"),
    "Krittika":         ("goat",     "female"),
    "Rohini":           ("serpent",  "male"),
    "Mrigashira":       ("serpent",  "female"),
    "Ardra":            ("dog",      "female"),
    "Punarvasu":        ("cat",      "male"),
    "Pushya":           ("goat",     "male"),
    "Ashlesha":         ("cat",      "female"),
    "Magha":            ("rat",      "male"),
    "Purva Phalguni":   ("rat",      "female"),
    "Uttara Phalguni":  ("cow",      "female"),
    "Hasta":            ("buffalo",  "male"),
    "Chitra":           ("tiger",    "female"),
    "Swati":            ("buffalo",  "female"),
    "Vishakha":         ("tiger",    "male"),
    "Anuradha":         ("deer",     "male"),
    "Jyeshtha":         ("deer",     "female"),
    "Mula":             ("dog",      "male"),
    "Purva Ashadha":    ("monkey",   "male"),
    "Uttara Ashadha":   ("mongoose", "male"),
    "Shravana":         ("monkey",   "female"),
    "Dhanishta":        ("lion",     "female"),
    "Shatabhisha":      ("horse",    "female"),
    "Purva Bhadrapada": ("lion",     "male"),
    "Uttara Bhadrapada":("cow",      "male"),
    "Revati":           ("elephant", "female"),
}

# Enemy animal pairs (mutual enemies)
_YONI_ENEMIES: frozenset[frozenset] = frozenset({
    frozenset(["horse",    "buffalo"]),
    frozenset(["elephant", "lion"]),
    frozenset(["goat",     "monkey"]),
    frozenset(["serpent",  "mongoose"]),
    frozenset(["dog",      "deer"]),
    frozenset(["cat",      "rat"]),
    frozenset(["cow",      "tiger"]),
})

# Varna level by Moon sign (rashi): Brahmin=4, Kshatriya=3, Vaishya=2, Shudra=1
_VARNA_LEVEL: dict[str, int] = {
    "Cancer": 4, "Scorpio": 4, "Pisces": 4,        # Brahmin (water)
    "Aries": 3,  "Leo": 3,    "Sagittarius": 3,    # Kshatriya (fire)
    "Taurus": 2, "Virgo": 2,  "Capricorn": 2,      # Vaishya (earth)
    "Gemini": 1, "Libra": 1,  "Aquarius": 1,       # Shudra (air)
}

_VARNA_NAMES: dict[int, str] = {4: "Brahmin", 3: "Kshatriya", 2: "Vaishya", 1: "Shudra"}

# Vasya (magnetic control) group by Moon sign
_VASYA_GROUP: dict[str, str] = {
    "Aries":       "chatushpada",
    "Taurus":      "chatushpada",
    "Gemini":      "nara",
    "Cancer":      "jalchar",
    "Leo":         "vanchar",
    "Virgo":       "nara",
    "Libra":       "nara",
    "Scorpio":     "keeta",
    "Sagittarius": "nara",
    "Capricorn":   "chatushpada",
    "Aquarius":    "nara",
    "Pisces":      "jalchar",
}

# Vasya control: sign → set of signs it controls
_VASYA_CONTROLS: dict[str, set[str]] = {
    "Leo":     {"Aries"},
    "Cancer":  {"Scorpio"},
    "Aquarius":{"Capricorn"},
    "Virgo":   {"Pisces"},
}

# ---------------------------------------------------------------------------
# Planet relationship helpers
# ---------------------------------------------------------------------------

def _planet_rel(planet_a: str, planet_b: str) -> str:
    """How planet_a views planet_b: 'friend', 'neutral', or 'enemy'."""
    if planet_b in utils._FRIENDLY.get(planet_a, []):
        return "friend"
    if planet_b in utils._ENEMY.get(planet_a, []):
        return "enemy"
    return "neutral"


def _combined_rel(a: str, b: str) -> tuple[str, str]:
    return _planet_rel(a, b), _planet_rel(b, a)


_MAITRI_SCORE: dict[tuple[str, str], float] = {
    ("friend",  "friend"):  5.0,
    ("friend",  "neutral"): 4.0,
    ("neutral", "friend"):  4.0,
    ("neutral", "neutral"): 3.0,
    ("friend",  "enemy"):   1.0,
    ("enemy",   "friend"):  1.0,
    ("neutral", "enemy"):   0.5,
    ("enemy",   "neutral"): 0.5,
    ("enemy",   "enemy"):   0.0,
}


def _maitri_score(lord_a: str, lord_b: str) -> float:
    if lord_a == lord_b:
        return 5.0
    return _MAITRI_SCORE.get(_combined_rel(lord_a, lord_b), 3.0)


# ---------------------------------------------------------------------------
# Individual kuta calculators
# ---------------------------------------------------------------------------

def _varna(sign_a: str, sign_b: str) -> tuple[float, str]:
    """Varna kuta score for a pair of Moon signs.

    Convention: sign_a is the groom's Moon sign, sign_b is the bride's.

    The rule is directional: the match is auspicious (1.0) only when the groom's
    varna level is equal to or higher than the bride's. If the groom is of a
    lower varna than the bride the score is 0.0 (the classical texts state the
    groom's varna must be at least as high as the bride's for harmony). The
    maximum points for this kuta is 1 out of 36.
    """
    va = _VARNA_LEVEL.get(sign_a, 2)  # groom's varna level
    vb = _VARNA_LEVEL.get(sign_b, 2)  # bride's varna level
    score = 1.0 if va >= vb else 0.0
    names = f"{_VARNA_NAMES[va]} / {_VARNA_NAMES[vb]}"
    if va == vb:
        interp = f"Both partners share the {_VARNA_NAMES[va]} varna, indicating excellent spiritual alignment."
    elif va > vb:
        interp = f"{names} varna pairing: groom's varna is higher, indicating auspicious compatibility."
    else:
        interp = f"{names} varna difference: bride's varna is higher than the groom's, which is inauspicious per classical rules."
    return score, interp


def _vasya(sign_a: str, sign_b: str) -> tuple[float, str]:
    ga = _VASYA_GROUP.get(sign_a, "nara")
    gb = _VASYA_GROUP.get(sign_b, "nara")
    if ga == gb:
        return 2.0, "Both partners belong to the same vasya group, indicating natural magnetic harmony."
    controlled_by_b = _VASYA_CONTROLS.get(sign_b, set())
    if sign_a in controlled_by_b:
        return 1.0, "One partner's sign falls within the vasya of the other, indicating a supportive power dynamic."
    controlled_by_a = _VASYA_CONTROLS.get(sign_a, set())
    if sign_b in controlled_by_a:
        return 0.5, "Partial vasya relationship exists; one partner may feel less drawn than the other."
    return 0.0, "The partners' vasya groups have no natural affinity, requiring effort to maintain attraction."


# Tara (Dina) koota (Muhurta Chintamani, Vivaha-prakarana, tara-koota): count
# inclusively from one birth star to the other and divide by nine; only the
# remainders 3 (Vipat), 5 (Pratyak) and 7 (Vadha) are inauspicious. Remainder
# 1 (Janma: the same star, the 10th, the 19th) is NOT among them. Each
# auspicious direction is worth 1.5 points.
_TARA_INAUSPICIOUS = frozenset({3, 5, 7})


def _tara(nak_a: str, nak_b: str) -> tuple[float, str]:
    idx_a = utils.NAKSHATRAS.index(nak_a)
    idx_b = utils.NAKSHATRAS.index(nak_b)

    count_ab = (idx_b - idx_a) % 27 + 1
    count_ba = (idx_a - idx_b) % 27 + 1

    fav_ab = (count_ab % 9) not in _TARA_INAUSPICIOUS
    fav_ba = (count_ba % 9) not in _TARA_INAUSPICIOUS

    if fav_ab and fav_ba:
        return 3.0, "Both birth-star counts fall in favorable tara positions, indicating strong karmic resonance."
    # At most one direction can be inauspicious: for two different stars the
    # inclusive counts sum to 29, so the two remainders sum to 2 (mod 9), which
    # no two of 3, 5 and 7 do; the same star gives remainder 1 both ways. A
    # zero tara score therefore cannot arise under the classical rule.
    return 1.5, "One tara direction is favorable; this pair has mixed star compatibility with some friction."


def _yoni(nak_a: str, nak_b: str) -> tuple[float, str]:
    ya = NAKSHATRA_YONI.get(nak_a)
    yb = NAKSHATRA_YONI.get(nak_b)
    if not ya or not yb:
        return 2.0, "Yoni compatibility is moderate; standard biological-instinctive harmony expected."
    animal_a, _ = ya
    animal_b, _ = yb
    if animal_a == animal_b:
        return 4.0, f"Both nakshatras share the {animal_a} yoni, indicating deep instinctive and biological compatibility."
    pair = frozenset([animal_a, animal_b])
    if pair in _YONI_ENEMIES:
        return 0.0, f"The {animal_a} and {animal_b} yoni are natural enemies, suggesting significant instinctive friction."
    return 2.0, f"The {animal_a} and {animal_b} yoni are neutral toward each other, providing acceptable compatibility."


def _graha_maitri(sign_a: str, sign_b: str) -> tuple[float, str]:
    lord_a = utils.SIGN_LORDS.get(sign_a, "")
    lord_b = utils.SIGN_LORDS.get(sign_b, "")
    score = _maitri_score(lord_a, lord_b)
    rel_ab, rel_ba = _combined_rel(lord_a, lord_b) if lord_a != lord_b else ("friend", "friend")
    if score >= 5.0:
        interp = f"{lord_a} and {lord_b} are mutual natural friends, offering excellent emotional accord."
    elif score >= 4.0:
        interp = f"{lord_a} and {lord_b} share a friendly-neutral bond, supporting general compatibility."
    elif score >= 3.0:
        interp = f"{lord_a} and {lord_b} are neutral to each other, providing a stable but unremarkable foundation."
    elif score >= 1.0:
        interp = f"{lord_a} and {lord_b} have a mixed or mildly tense relationship; conscious communication helps."
    else:
        interp = f"{lord_a} and {lord_b} are natural enemies, requiring significant effort to build harmony."
    return score, interp


def _gana(nak_a: str, nak_b: str) -> tuple[float, str]:
    ga = NAKSHATRA_GANA.get(nak_a, "manushya")
    gb = NAKSHATRA_GANA.get(nak_b, "manushya")
    if ga == gb:
        return 6.0, f"Both partners are {ga} gana, indicating harmonious temperaments and matching life rhythms."
    pair = frozenset([ga, gb])
    if pair == frozenset(["deva", "manushya"]):
        return 5.0, "Deva and manushya gana pairing is generally compatible, with minor temperament adjustments needed."
    if pair == frozenset(["manushya", "rakshasa"]):
        return 0.0, "Manushya and rakshasa gana combination indicates conflicting temperaments requiring deep mutual respect."
    # deva + rakshasa
    return 0.0, "Deva and rakshasa gana are fundamentally mismatched in disposition; strong effort is needed."


def _bhakoot(sign_a: str, sign_b: str) -> tuple[float, str]:
    idx_a = utils.SIGNS.index(sign_a)
    idx_b = utils.SIGNS.index(sign_b)
    count_ab = (idx_b - idx_a) % 12 + 1
    count_ba = (idx_a - idx_b) % 12 + 1
    dosha_pairs = {(2, 12), (12, 2), (6, 8), (8, 6), (5, 9), (9, 5)}
    if (count_ab, count_ba) in dosha_pairs:
        return 0.0, (
            f"The {count_ab}-{count_ba} rashi relationship creates a bhakoot dosha, "
            f"warning of emotional and financial discord."
        )
    return 7.0, (
        f"The {count_ab}-{count_ba} rashi relationship is free of bhakoot dosha, "
        f"supporting emotional and financial harmony."
    )


def _nadi(nak_a: str, nak_b: str) -> tuple[float, str]:
    na = _nakshatra_nadi(nak_a)
    nb = _nakshatra_nadi(nak_b)
    if na == nb:
        return 0.0, (
            f"Both partners share the {na} nadi, creating a nadi dosha that may affect "
            f"health and progeny; remedial measures are advised."
        )
    return 8.0, (
        f"{na} and {nb} nadi combination is fully compatible, indicating complementary "
        f"constitutions and strong progeny potential."
    )


# ---------------------------------------------------------------------------
# Mangal dosha
# ---------------------------------------------------------------------------

@dataclass
class MangalDoshaInfo:
    has_dosha: bool
    severity: str  # "none" | "mild" | "strong"
    cancellation: str


def _mangal_dosha_raw(snapshot: ChartSnapshot) -> tuple[bool, str, list[str]]:
    """Returns (has_dosha, severity, cancellation_reasons)."""
    mars = snapshot.rasi_chart.get("Mars")
    if mars is None:
        return False, "none", []

    if mars.house not in {1, 2, 4, 7, 8, 12}:
        return False, "none", []

    severity = "strong" if mars.house in {8, 12} else "mild"

    reasons: list[str] = []
    if mars.sign in ("Aries", "Scorpio", "Capricorn"):
        reasons.append(f"Mars in {mars.sign} (own sign or exalted) cancels the dosha.")
    if "Jupiter" in mars.conjunctions or "Jupiter" in mars.aspects:
        reasons.append("Jupiter's influence on Mars cancels the Mangal Dosha.")
    moon = snapshot.rasi_chart.get("Moon")
    if snapshot.lagna in ("Aries", "Scorpio") or (moon and moon.sign in ("Aries", "Scorpio")):
        reasons.append("Mars-ruled lagna or Moon sign cancels the Mangal Dosha.")
    if mars.house == 2 and mars.sign in ("Gemini", "Virgo"):
        reasons.append(f"Mars in 2nd house in {mars.sign} cancels the dosha.")

    return True, severity, reasons


def compute_mangal_dosha(snap_a: ChartSnapshot, snap_b: ChartSnapshot) -> tuple[MangalDoshaInfo, MangalDoshaInfo]:
    has_a, sev_a, cancel_a = _mangal_dosha_raw(snap_a)
    has_b, sev_b, cancel_b = _mangal_dosha_raw(snap_b)

    # Mutual cancellation takes priority
    if has_a and has_b:
        cancel_a = ["Both charts carry Mangal Dosha, which mutually cancels the affliction."]
        cancel_b = ["Both charts carry Mangal Dosha, which mutually cancels the affliction."]

    return (
        MangalDoshaInfo(has_dosha=has_a, severity=sev_a if has_a else "none",
                        cancellation=cancel_a[0] if cancel_a else ""),
        MangalDoshaInfo(has_dosha=has_b, severity=sev_b if has_b else "none",
                        cancellation=cancel_b[0] if cancel_b else ""),
    )


# ---------------------------------------------------------------------------
# Dasha overlap windows
# ---------------------------------------------------------------------------

@dataclass
class DashaOverlapResult:
    start_date: str   # YYYY-MM-DD
    end_date: str     # YYYY-MM-DD
    person_a_lord: str
    person_b_lord: str
    quality: str      # "favorable" | "neutral" | "challenging"


def _dasha_quality(lord_a: str, lord_b: str) -> str:
    if lord_a == lord_b:
        return "favorable"
    rel_ab, rel_ba = _combined_rel(lord_a, lord_b)
    if rel_ab == "friend" and rel_ba == "friend":
        return "favorable"
    if rel_ab == "enemy" or rel_ba == "enemy":
        return "challenging"
    return "neutral"


def compute_dasha_overlaps(
    snap_a: ChartSnapshot,
    snap_b: ChartSnapshot,
    today: date,
) -> list[DashaOverlapResult]:
    window_start = datetime(today.year, today.month, today.day)
    window_end = window_start + timedelta(days=25 * 365.25)

    birth_a = datetime.combine(snap_a.person.birth_date, snap_a.person.birth_time)
    birth_b = datetime.combine(snap_b.person.birth_date, snap_b.person.birth_time)

    mds_a = vimshottari_mahadashas(snap_a, birth_a)
    mds_b = vimshottari_mahadashas(snap_b, birth_b)

    overlaps: list[DashaOverlapResult] = []
    for md_a in mds_a:
        a_s = max(md_a.start_date, window_start)
        a_e = min(md_a.end_date, window_end)
        if a_s >= a_e:
            continue
        for md_b in mds_b:
            b_s = max(md_b.start_date, window_start)
            b_e = min(md_b.end_date, window_end)
            if b_s >= b_e:
                continue
            ov_s = max(a_s, b_s)
            ov_e = min(a_e, b_e)
            if ov_s < ov_e:
                overlaps.append(DashaOverlapResult(
                    start_date=ov_s.strftime("%Y-%m-%d"),
                    end_date=ov_e.strftime("%Y-%m-%d"),
                    person_a_lord=md_a.lord,
                    person_b_lord=md_b.lord,
                    quality=_dasha_quality(md_a.lord, md_b.lord),
                ))

    overlaps.sort(key=lambda o: o.start_date)
    return overlaps


# ---------------------------------------------------------------------------
# Nakshatra compatibility prose
# ---------------------------------------------------------------------------

def nakshatra_compatibility_prose(
    nak_a: str, nak_b: str, sign_a: str, sign_b: str, tara_sc: float,
) -> str:
    ga = NAKSHATRA_GANA.get(nak_a, "manushya")
    gb = NAKSHATRA_GANA.get(nak_b, "manushya")
    lord_a = utils.SIGN_LORDS.get(sign_a, "")
    lord_b = utils.SIGN_LORDS.get(sign_b, "")

    if ga == gb:
        gana_sent = f"Both Moon nakshatras belong to the {ga} gana, reflecting compatible temperaments."
    elif frozenset([ga, gb]) == frozenset(["deva", "manushya"]):
        gana_sent = "The deva and manushya gana combination is broadly compatible, with occasional lifestyle differences."
    else:
        gana_sent = f"The {ga} and {gb} gana pairing calls for patience, as the partners' natures differ significantly."

    rel_ab, rel_ba = _combined_rel(lord_a, lord_b) if lord_a != lord_b else ("friend", "friend")
    if rel_ab == "friend" and rel_ba == "friend":
        lord_sent = f"The rashi lords {lord_a} and {lord_b} are mutual friends, strengthening emotional accord."
    elif "enemy" in (rel_ab, rel_ba):
        lord_sent = f"The rashi lords {lord_a} and {lord_b} share tension; conscious communication is essential."
    else:
        lord_sent = f"The rashi lords {lord_a} and {lord_b} maintain a neutral bond, offering a steady, if understated, rapport."

    if tara_sc >= 2.5:
        tara_sent = "The tara count is harmonious, pointing to karmic ease and mutual growth."
    elif tara_sc > 0:
        tara_sent = "The tara count is partially favorable; some star-level friction may surface, especially during transitions."
    else:
        tara_sent = "The tara count reveals friction; the partners may face recurring tests of patience and commitment."

    return f"{gana_sent} {lord_sent} {tara_sent}"


# ---------------------------------------------------------------------------
# Composite strength notes
# ---------------------------------------------------------------------------

def composite_strength_notes(snap_a: ChartSnapshot, snap_b: ChartSnapshot) -> str:
    from .strength import compute_all_bhavabala

    bala_a = {b.house_number: b for b in compute_all_bhavabala(snap_a)}
    bala_b = {b.house_number: b for b in compute_all_bhavabala(snap_b)}

    h7a = bala_a.get(7)
    h7b = bala_b.get(7)

    if h7a and h7b:
        ra, rb = h7a.rank, h7b.rank
        if ra == rb == "strong":
            return ("Both charts have strong 7th-house bhavabala, indicating mutual commitment "
                    "and shared investment in the partnership.")
        if ra == "strong":
            return (f"Person A's 7th-house bhavabala is strong while Person B's is {rb}; "
                    f"Person A may take the lead in nurturing the relationship.")
        if rb == "strong":
            return (f"Person B's 7th-house bhavabala is strong while Person A's is {ra}; "
                    f"Person B brings grounding energy to the union.")
        if ra == rb:
            return (f"Both charts show {ra} 7th-house bhavabala; the couple benefits from building "
                    f"deliberate partnership structures together.")
        return (f"Person A has {ra} and Person B has {rb} 7th-house bhavabala; "
                f"complementary partnership strengths can balance each other.")

    return ("7th-house bhavabala data is incomplete; a full shadbala analysis of each chart "
            "is recommended to assess partnership strength.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

@dataclass
class KutaResult:
    name: str
    score: float
    max_score: float
    interpretation: str


@dataclass
class CompatResult:
    total_score: float
    max_score: float
    kutas: list[KutaResult]
    mangal_dosha_a: MangalDoshaInfo
    mangal_dosha_b: MangalDoshaInfo
    nakshatra_compatibility: str
    dasha_overlaps: list[DashaOverlapResult]
    composite_strength_notes: str


def compute_compat(snap_a: ChartSnapshot, snap_b: ChartSnapshot, today: date) -> CompatResult:
    moon_a = snap_a.rasi_chart.get("Moon")
    moon_b = snap_b.rasi_chart.get("Moon")
    # A missing Moon means the snapshot is corrupt. Defaulting to Aries/Ashwini
    # would return a plausible but entirely wrong compatibility score with no
    # error surfaced — fail loudly instead.
    if moon_a is None or moon_b is None:
        raise ValueError("Moon absent from rasi_chart; cannot compute compatibility")

    sign_a = moon_a.sign
    sign_b = moon_b.sign
    nak_a  = moon_a.nakshatra
    nak_b  = moon_b.nakshatra

    # 8 kutas in BPHS order
    v_sc, v_int   = _varna(sign_a, sign_b)
    va_sc, va_int = _vasya(sign_a, sign_b)
    t_sc, t_int   = _tara(nak_a, nak_b)
    y_sc, y_int   = _yoni(nak_a, nak_b)
    gm_sc, gm_int = _graha_maitri(sign_a, sign_b)
    g_sc, g_int   = _gana(nak_a, nak_b)
    b_sc, b_int   = _bhakoot(sign_a, sign_b)
    n_sc, n_int   = _nadi(nak_a, nak_b)

    kutas = [
        KutaResult("varna",        v_sc,  1.0, v_int),
        KutaResult("vasya",        va_sc, 2.0, va_int),
        KutaResult("tara",         t_sc,  3.0, t_int),
        KutaResult("yoni",         y_sc,  4.0, y_int),
        KutaResult("graha_maitri", gm_sc, 5.0, gm_int),
        KutaResult("gana",         g_sc,  6.0, g_int),
        KutaResult("bhakoot",      b_sc,  7.0, b_int),
        KutaResult("nadi",         n_sc,  8.0, n_int),
    ]

    total = round(sum(k.score for k in kutas), 4)
    max_sc = 36.0

    dosha_a, dosha_b = compute_mangal_dosha(snap_a, snap_b)
    overlaps = compute_dasha_overlaps(snap_a, snap_b, today)
    nak_prose = nakshatra_compatibility_prose(nak_a, nak_b, sign_a, sign_b, t_sc)
    strength_note = composite_strength_notes(snap_a, snap_b)

    return CompatResult(
        total_score=total,
        max_score=max_sc,
        kutas=kutas,
        mangal_dosha_a=dosha_a,
        mangal_dosha_b=dosha_b,
        nakshatra_compatibility=nak_prose,
        dasha_overlaps=overlaps,
        composite_strength_notes=strength_note,
    )
