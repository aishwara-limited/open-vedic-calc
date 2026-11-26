"""Vimshopaka Bala — 20-point cross-varga strength (BPHS Dashavarga scheme).

Vimshopaka ("twenty-fold") strength rates how well a graha is placed across a
set of divisional charts. This module implements the **Dashavarga** (ten-varga)
scheme of BPHS ch. 7 vv. 20-27.

Weights
-------
The ten vargas and their point-weights (BPHS 7.20) are taken **verbatim from
pyjhora** (``jhora.const.dhasavarga_amsa_vimsopaka``):

    D1 Rasi 3, D2 Hora 1.5, D3 Drekkana 1.5, D7 Saptamsa 1.5, D9 Navamsa 1.5,
    D10 Dasamsa 1.5, D12 Dwadasamsa 1.5, D16 Shodasamsa 1.5, D30 Trimsamsa 1.5,
    D60 Shashtiamsa 5  ——  total 20.

We assert at import time that this wrapped table both sums to 20 and matches
the BPHS Dashavarga set, so a future pyjhora bump can never silently change
the weighting underneath us.

Score in each varga
-------------------
BPHS 7.24-25: a graha in its own sign in a varga scores 20; otherwise it scores
by its five-fold (compound) relationship with the lord of that varga sign —
adhimitra (great friend) 18, mitra (friend) 15, sama (neutral) 10, shatru
(enemy) 7, adhishatru (great enemy) 5. The compound relationship is BPHS
3.55-58: the natural relationship combined with the temporary one, which is
read from the rasi chart (``strength.compound_relationship``, the function
Shadbala's saptavargaja bala uses). The varga's share is its weight times that
score over 20. The verse has no separate step for exaltation or debilitation:
a graha exalted or debilitated in a varga scores by its relationship with the
sign's lord like any other. pyjhora's ``_vimsopaka_bala_of_planets`` applies
the same rule; it recomputes every divisional chart from the raw ``jd``, so
this module scores the snapshot's own vargas instead.

Grades
------
BPHS 7.26-27 read a total below 5 as unable to give good results, 5-10 as
meagre, 10-15 as middling and 15 or more as full. ``grade`` serves those four
bands under this API's labels: very weak, weak, good and excellent.
"""
from dataclasses import dataclass, field

from . import utils
from .chart import ChartSnapshot
from .strength import compound_relationship

try:  # wrap pyjhora's pinned Dashavarga weight table
    from jhora import const as _jhora_const
    _DASHAVARGA_WEIGHTS_RAW: dict[int, float] = dict(_jhora_const.dhasavarga_amsa_vimsopaka)
except Exception:  # fail-closed: fall back to the literal BPHS table if pyjhora moves it
    _DASHAVARGA_WEIGHTS_RAW = {1: 3, 2: 1.5, 3: 1.5, 7: 1.5, 9: 1.5,
                              10: 1.5, 12: 1.5, 16: 1.5, 30: 1.5, 60: 5}

# Map the pyjhora divisional-chart-factor (Dnn) to the ChartSnapshot attribute
# holding that varga. Ordered as BPHS lists the Dashavarga.
_VARGA_ATTR: dict[int, str] = {
    1: "rasi_chart",
    2: "hora_chart",
    3: "drekkana_chart",
    7: "saptamsa_chart",
    9: "navamsa_chart",
    10: "decamsa_chart",
    12: "dwadasamsa_chart",
    16: "shodasamsa_chart",
    30: "trimshamsa_chart",
    60: "shashtyamsa_chart",
}

# Human-readable Dnn -> varga label for the contributions map.
_VARGA_LABEL: dict[int, str] = {
    1: "D1", 2: "D2", 3: "D3", 7: "D7", 9: "D9",
    10: "D10", 12: "D12", 16: "D16", 30: "D30", 60: "D60",
}

# Validate the wrapped table at import: it must be exactly the BPHS Dashavarga
# set and sum to 20. A pyjhora change that breaks either invariant fails loudly.
assert set(_DASHAVARGA_WEIGHTS_RAW) == set(_VARGA_ATTR), (
    "pyjhora dhasavarga_amsa_vimsopaka no longer matches the BPHS Dashavarga set"
)
assert abs(sum(_DASHAVARGA_WEIGHTS_RAW.values()) - 20.0) < 1e-9, (
    "Dashavarga Vimshopaka weights must total 20"
)

# BPHS 7.24-25: the score out of 20 in one varga, by the graha's own sign or
# its compound relationship (BPHS 3.55-58) with the varga sign's lord.
_VIMSHOPAKA_SCORE: dict[str, float] = {
    "own": 20.0,
    "great friend": 18.0,
    "friend": 15.0,
    "neutral": 10.0,
    "enemy": 7.0,
    "great enemy": 5.0,
}


# Grade bands, BPHS 7.26-27 (0-20 scale), served under this API's labels:
#   < 5   very weak  (unable to give good results)
#   5-10  weak       (meagre)
#   10-15 good       (middling)
#   >= 15 excellent  (full)
def _grade(total: float) -> str:
    if total >= 15.0:
        return "excellent"
    if total >= 10.0:
        return "good"
    if total >= 5.0:
        return "weak"
    return "very weak"


@dataclass
class VimshopakaResult:
    planet: str
    total: float                       # 0-20, rounded 2dp
    grade: str                         # very weak | weak | good | excellent
    contributions: dict[str, float] = field(default_factory=dict)  # {varga_label: points}


# The seven grahas. Rahu and Ketu are excluded: they lord no sign in the
# sign-lordship table this engine reads (utils.SIGN_LORDS) and have no natural
# relationships in it (utils._FRIENDLY / utils._ENEMY), so neither "own varga"
# nor the compound relationship with a varga lord is defined for them.
_VIMSHOPAKA_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]


def _rasi_longitudes(snapshot: ChartSnapshot) -> dict[str, float]:
    """The rasi sign of each graha, as a longitude at the start of the sign:
    the temporary relationship of BPHS 3.56 counts signs, not degrees.

    Fail closed: every graha may be a varga lord, so a rasi chart without all
    seven cannot be scored, and is refused rather than scored as nothing.
    """
    missing = [p for p in _VIMSHOPAKA_PLANETS if p not in snapshot.rasi_chart]
    if missing:
        raise ValueError(f"Vimshopaka needs all seven grahas; the chart lacks {missing}")
    return {
        p: utils.SIGNS.index(snapshot.rasi_chart[p].sign) * 30.0
        for p in _VIMSHOPAKA_PLANETS
    }


def _varga_score(planet: str, sign: str, rasi_longitudes: dict[str, float]) -> float:
    if sign in utils._OWN_SIGNS[planet]:
        return _VIMSHOPAKA_SCORE["own"]
    lord = utils.SIGN_LORDS[sign]
    return _VIMSHOPAKA_SCORE[compound_relationship(planet, lord, rasi_longitudes)]


def compute_vimshopaka(snapshot: ChartSnapshot, planet: str) -> VimshopakaResult:
    """Vimshopaka Bala (Dashavarga, 0-20) for one graha over the snapshot."""
    rasi_longitudes = _rasi_longitudes(snapshot)
    contributions: dict[str, float] = {}
    total = 0.0
    for dcf, attr in _VARGA_ATTR.items():
        weight = _DASHAVARGA_WEIGHTS_RAW[dcf]
        varga = getattr(snapshot, attr, None) or {}
        pd = varga.get(planet)
        if pd is None:
            # Fail-closed: a missing placement contributes nothing.
            points = 0.0
        else:
            points = weight * _varga_score(planet, pd.sign, rasi_longitudes) / 20.0
        contributions[_VARGA_LABEL[dcf]] = round(points, 4)
        total += points
    total = round(total, 2)
    return VimshopakaResult(
        planet=planet,
        total=total,
        grade=_grade(total),
        contributions=contributions,
    )


def compute_all_vimshopaka(snapshot: ChartSnapshot) -> list[VimshopakaResult]:
    """Vimshopaka Bala for all seven grahas (Rahu/Ketu excluded — see module note)."""
    return [compute_vimshopaka(snapshot, p) for p in _VIMSHOPAKA_PLANETS]
