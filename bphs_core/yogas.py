from dataclasses import dataclass, field

from . import utils
from .chart import _ASPECTS, ChartSnapshot

DUSTHANA = {6, 8, 12}
KENDRA = {1, 4, 7, 10}
TRIKONA = {1, 5, 9}
UPACHAYA = {3, 6, 10, 11}
# BPHS 34.15: a kendra or kona lord that also owns an evil house does not
# make the pair Raja Yoga by relation alone. The evil houses, as ruled for
# this engine, are the 3rd, 6th, 8th and 11th, and the lagna lord is exempt
# (34.2-7 call the lord of the lagna specially auspicious).
BLEMISHING_HOUSES = (3, 6, 8, 11)


@dataclass
class Yoga:
    name: str
    description: str
    planets_involved: list[str]
    houses_involved: list[int]
    strength: str
    is_viparita_raja: bool = False
    activating_lords: list[str] = field(default_factory=list)


def _house_lord(snapshot: ChartSnapshot, house: int) -> str | None:
    sign = utils.SIGNS[int(snapshot.house_cusps[house - 1] // 30) % 12]
    return utils.get_sign_lord(sign)


def _owned_signs(planet: str) -> set[str]:
    return {sign for sign in utils.SIGNS if utils.get_sign_lord(sign) == planet}


def _aspects_sign(planet: str, from_sign: str, to_sign: str) -> bool:
    """Full graha drishti, BPHS 26.2-5: every graha aspects the 7th sign
    from its own; Saturn also the 3rd and 10th, Jupiter the 5th and 9th,
    Mars the 4th and 8th (the offsets of ``chart._ASPECTS``)."""
    offset = (utils.SIGNS.index(to_sign) - utils.SIGNS.index(from_sign)) % 12 + 1
    return offset in _ASPECTS.get(planet, ())


def _pair_relations(a: str, a_sign: str, b: str, b_sign: str) -> list[str]:
    """The relations of BPHS 34.11-12 between graha *a* in *a_sign* and
    graha *b* in *b_sign*, as the phrases a Raja Yoga description carries:
    together in one sign, an exchange of signs, one standing in the other's
    sign, and a full aspect each on the other. Empty when unrelated."""
    relations: list[str] = []
    if a_sign == b_sign:
        relations.append("conjunct")
    a_in_b = a_sign in _owned_signs(b)
    b_in_a = b_sign in _owned_signs(a)
    if a_in_b and b_in_a:
        relations.append("exchange signs")
    elif a_in_b:
        relations.append(f"{a} in {b}'s sign")
    elif b_in_a:
        relations.append(f"{b} in {a}'s sign")
    if _aspects_sign(a, a_sign, b_sign) and _aspects_sign(b, b_sign, a_sign):
        relations.append("mutual aspect")
    return relations


def _planet_house(snapshot: ChartSnapshot, planet: str) -> int:
    pd = snapshot.rasi_chart.get(planet)
    return pd.house if pd else 0


def _compute_yoga_strength(snapshot: ChartSnapshot, planets: list[str]) -> str:
    dignities = []
    for p in planets:
        pd = snapshot.rasi_chart.get(p)
        if pd:
            dignities.append(pd.dignity)
    if not dignities:
        return "moderate"
    if any(d in ("debilitated", "enemy") for d in dignities):
        return "mild"
    if all(d in ("exalted", "own sign", "moolatrikona") for d in dignities):
        return "strong"
    return "moderate"


def detect_viparita_raja_yoga(snapshot: ChartSnapshot) -> list[Yoga]:
    yogas: list[Yoga] = []
    configs = [
        ("Harsha Yoga", 6, "6th lord in 6/8/12 — disease and enemies vanquished"),
        ("Sarala Yoga", 8, "8th lord in 6/8/12 — longevity and hidden gains"),
        ("Vimala Yoga", 12, "12th lord in 6/8/12 — liberation from expenditure"),
    ]
    for name, dusthana_house, desc in configs:
        lord = _house_lord(snapshot, dusthana_house)
        if lord is None:
            continue
        lord_house = _planet_house(snapshot, lord)
        if lord_house in DUSTHANA:
            yogas.append(Yoga(
                name=name, description=desc,
                planets_involved=[lord],
                houses_involved=[dusthana_house, lord_house],
                strength=_compute_yoga_strength(snapshot, [lord]),
                is_viparita_raja=True,
                activating_lords=[lord],
            ))
    return yogas


def detect_panchamahapurusha(snapshot: ChartSnapshot) -> list[Yoga]:
    configs = [
        ("Ruchaka Yoga", "Mars", ["Aries", "Scorpio", "Capricorn"], KENDRA,
         "Mars in own/exalt in kendra — fierce, commanding"),
        ("Bhadra Yoga", "Mercury", ["Gemini", "Virgo"], KENDRA,
         "Mercury in own/exalt in kendra — intelligent, eloquent"),
        ("Hamsa Yoga", "Jupiter", ["Sagittarius", "Pisces", "Cancer"], KENDRA,
         "Jupiter in own/exalt in kendra — wise, righteous"),
        ("Malavya Yoga", "Venus", ["Taurus", "Libra", "Pisces"], KENDRA,
         "Venus in own/exalt in kendra — artistic, prosperous"),
        ("Sasa Yoga", "Saturn", ["Capricorn", "Aquarius", "Libra"], KENDRA,
         "Saturn in own/exalt in kendra — disciplined, powerful"),
    ]
    yogas: list[Yoga] = []
    for name, planet, signs, houses, desc in configs:
        pd = snapshot.rasi_chart.get(planet)
        if pd and pd.sign in signs and pd.house in houses:
            yogas.append(Yoga(
                name=name, description=desc,
                planets_involved=[planet],
                houses_involved=[pd.house],
                strength=_compute_yoga_strength(snapshot, [planet]),
                activating_lords=[planet],
            ))
    return yogas


def detect_raja_yogas(snapshot: ChartSnapshot) -> list[Yoga]:
    # BPHS ch. 34 (the chapter on yoga-karakas; sloka numbers in the standard
    # Sanskrit numbering) gives two ways a kendra lordship and a kona lordship
    # make a Raja Yoga.
    #
    # THE PAIR (34.11-12): the lord of a kendra and the lord of a kona related to
    # each other. The text names four relations and all four are detected
    # (_pair_relations): an exchange of signs, the two in one sign, a full aspect
    # each on the other (26.2-5), and one standing in the other's sign. A pair is
    # reported once, however many kendra/kona roles its two grahas hold.
    # House 1 is both a kendra and a kona (34.3), and the lagna lord joining the
    # 5th or 9th lord is such a pair, so house 1 stays in BOTH lists.
    #
    # THE BLEMISH (34.15): a pair is not reported when either lord, other than
    # the lagna lord, also rules the 3rd, 6th, 8th or 11th (BLEMISHING_HOUSES).
    #
    # THE YOGAKARAKA (34.13): one graha holding a kona lordship and a kendra
    # lordship. Here house 1 does NOT count on either side. 34.3 calls the lagna
    # itself auspicious for being kendra and kona at once; it does not make the
    # lagna lord a yogakaraka through whichever other house that lord rules.
    # The ascendant-by-ascendant slokas (34.19-44) name a single graha as the
    # maker of the yoga for Taurus (34.23, Saturn), Cancer (34.27, Mars),
    # Capricorn (34.40, Venus) and Aquarius (34.41, Venus), each ruling a
    # kendra and a kona away from the lagna; Mars for Leo (34.29) and Saturn
    # for Libra (34.33) are counted auspicious and hold the same pair of
    # lordships. For the four dual-sign ascendants, whose lord also rules the
    # 4th or 10th, the lord is never named alone (Gemini 34.25, Virgo 34.31,
    # Sagittarius 34.37, Pisces 34.43). Counting house 1 there served a Raja
    # Yoga on every Gemini, Virgo, Sagittarius and Pisces chart, wherever the
    # lagna lord stood. The six that remain are the six get_yoga_karaka_planet
    # lists; the two are pinned to each other, and to the text, by
    # tests/test_raja_yoga_yogakaraka.py. The yogakaraka is one by lordship
    # alone: no placement condition, and 34.15 cannot touch it (a graha ruling a
    # kendra and a kona with its two signs rules no third house). The pair rule
    # is pinned for all twelve ascendants by tests/test_raja_yoga_pair_rule.py.
    yogas: list[Yoga] = []
    kendra_lords = [(h, _house_lord(snapshot, h)) for h in sorted(KENDRA)]
    trikona_lords = [(h, _house_lord(snapshot, h)) for h in sorted(TRIKONA)]
    lagna_lord = _house_lord(snapshot, 1)
    blemished = {_house_lord(snapshot, h) for h in BLEMISHING_HOUSES} - {lagna_lord}
    seen_single: set[str] = set()
    seen_pairs: set[frozenset] = set()
    for kh, kl in kendra_lords:
        for th, tl in trikona_lords:
            if not kl or not tl:
                continue
            if kl == tl:
                # One planet lords both a kendra and a trikona (yoga karaka):
                # a kendra and a kona other than the lagna (see above).
                if kh == 1 or th == 1 or kl in seen_single:
                    continue
                seen_single.add(kl)
                yogas.append(Yoga(
                    name="Raja Yoga",
                    description=f"{kl} lords both kendra and trikona",
                    planets_involved=[kl], houses_involved=sorted({kh, th}),
                    strength=_compute_yoga_strength(snapshot, [kl]),
                    activating_lords=[kl],
                ))
            else:
                pair = frozenset({kl, tl})
                if pair in seen_pairs or kl in blemished or tl in blemished:
                    continue
                kl_pd = snapshot.rasi_chart.get(kl)
                tl_pd = snapshot.rasi_chart.get(tl)
                if not kl_pd or not tl_pd:
                    continue
                relations = _pair_relations(kl, kl_pd.sign, tl, tl_pd.sign)
                if not relations:
                    continue
                seen_pairs.add(pair)
                yogas.append(Yoga(
                    name="Raja Yoga",
                    description=(
                        f"{kl} (kendra lord) and {tl} (trikona lord): "
                        + ", ".join(relations)
                    ),
                    planets_involved=[kl, tl],
                    houses_involved=sorted({kl_pd.house, tl_pd.house}),
                    strength=_compute_yoga_strength(snapshot, [kl, tl]),
                    activating_lords=[kl, tl],
                ))
    return yogas


def detect_dhana_yogas(snapshot: ChartSnapshot) -> list[Yoga]:
    yogas: list[Yoga] = []
    lord2 = _house_lord(snapshot, 2)
    lord11 = _house_lord(snapshot, 11)
    lord5 = _house_lord(snapshot, 5)
    lord9 = _house_lord(snapshot, 9)
    for a, b, houses in [(lord2, lord11, [2, 11]), (lord5, lord9, [5, 9])]:
        # An association needs two grahas: a graha is never conjunct with
        # itself. One graha rules both the 2nd and the 11th for Leo (Mercury)
        # and Aquarius (Jupiter); BPHS grants it no wealth yoga for that, and
        # ch. 34 counts it among the malefics for Leo (34.29-30) and the
        # killers for Aquarius (34.41-42). The 5th and 9th never share a lord.
        # Pinned by tests/test_dhana_yoga_two_lords.py.
        if not a or not b or a == b:
            continue
        a_pd = snapshot.rasi_chart.get(a)
        b_pd = snapshot.rasi_chart.get(b)
        if a_pd and b_pd and a_pd.house == b_pd.house:
            yogas.append(Yoga(
                name="Dhana Yoga",
                description=f"{a} and {b} conjunct — wealth accumulation",
                planets_involved=[a, b],
                houses_involved=houses,
                strength=_compute_yoga_strength(snapshot, [a, b]),
                activating_lords=[a, b],
            ))
    return yogas


# A TUPLE in the engine's declared graha order (``utils.PLANETS``: Sun, Moon,
# Mars, Mercury, Jupiter, Venus, Saturn), never a set. This order decides which
# graha a Parivartana description names first and the order of the entries when
# a chart has several exchanges. It used to be a set of strings, whose iteration
# order follows string hashing and so changes with every interpreter start
# (PYTHONHASHSEED): the same chart was described as "Venus in Aquarius (owned by
# Saturn) exchanges signs with Saturn in Libra" by one process and "Saturn in
# Libra (owned by Venus) exchanges signs with Venus in Aquarius" by the next.
# Contract: tests/test_parivartana_order.py and
# tests/test_response_determinism.py::test_every_route_answers_identically_under_any_hash_seed.
_KARAKA_PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")


def detect_parivartana_yoga(snapshot: ChartSnapshot) -> list[Yoga]:
    """Mutual sign exchange (Parivartana) between any two of the 7 planets.

    Planet A is in a sign owned by planet B, and B is in a sign owned by A.
    The graha earlier in ``_KARAKA_PLANETS`` is named first, and exchanges are
    listed in the order of their first-named graha.
    """
    yogas: list[Yoga] = []
    planets = [p for p in _KARAKA_PLANETS if p in snapshot.rasi_chart]
    checked: set[frozenset] = set()

    for p_a in planets:
        sign_a = snapshot.rasi_chart[p_a].sign
        lord_of_a = utils.get_sign_lord(sign_a)
        if lord_of_a == p_a or lord_of_a not in snapshot.rasi_chart:
            continue
        sign_b = snapshot.rasi_chart[lord_of_a].sign
        lord_of_b = utils.get_sign_lord(sign_b)
        if lord_of_b != p_a:
            continue
        pair = frozenset({p_a, lord_of_a})
        if pair in checked:
            continue
        checked.add(pair)
        house_a = snapshot.rasi_chart[p_a].house
        house_b = snapshot.rasi_chart[lord_of_a].house
        yogas.append(Yoga(
            name="Parivartana Yoga",
            description=(
                f"{p_a} in {sign_a} (owned by {lord_of_a}) exchanges signs with "
                f"{lord_of_a} in {sign_b} (owned by {p_a}) — "
                f"houses {house_a} and {house_b} deeply interlinked"
            ),
            planets_involved=sorted([p_a, lord_of_a]),
            houses_involved=sorted([house_a, house_b]),
            strength=_compute_yoga_strength(snapshot, sorted([p_a, lord_of_a])),
            activating_lords=sorted([p_a, lord_of_a]),
        ))
    return yogas


def detect_all_yogas(snapshot: ChartSnapshot) -> list[Yoga]:
    yogas: list[Yoga] = []
    yogas.extend(detect_viparita_raja_yoga(snapshot))
    yogas.extend(detect_panchamahapurusha(snapshot))
    yogas.extend(detect_raja_yogas(snapshot))
    yogas.extend(detect_dhana_yogas(snapshot))
    yogas.extend(detect_parivartana_yoga(snapshot))
    return yogas


def get_yoga_karaka_planet(snapshot: ChartSnapshot) -> str:
    lagna = snapshot.lagna
    # Yoga karakas by lagna sign, BPHS 34.13 (one graha ruling a kendra and a
    # kona, the lagna counted on neither side), by lordship alone, as named
    # ascendant by ascendant: Taurus 34.23, Cancer 34.27, Leo 34.29, Libra
    # 34.33, Capricorn 34.40, Aquarius 34.41.
    YOGA_KARAKAS: dict[str, str] = {
        "Taurus": "Saturn", "Libra": "Saturn",
        "Cancer": "Mars", "Leo": "Mars",
        "Capricorn": "Venus", "Aquarius": "Venus",
    }
    return YOGA_KARAKAS.get(lagna, "")
