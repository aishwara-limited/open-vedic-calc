"""The kendra-lord / kona-lord Raja Yoga pair, as Parashara states it.

THE RULE (Brihat Parashara Hora Shastra, ch. 34, the chapter on yoga-karakas;
sloka numbers in the standard Sanskrit numbering)
---------------------------------------------------------------------------
* 34.11-12: the lord of a kendra and the lord of a kona make a yoga when they
  are related, and the text names four relations: they exchange signs, they
  stand together in one sign, they aspect each other, or one stands in the
  other's sign.
* 34.15: a kendra or kona lord that also owns an evil house does not make the
  yoga by those relations alone. The evil houses, as ruled for this engine, are
  the 3rd, 6th, 8th and 11th, and the lagna lord is exempt: 34.2-7 call the lord
  of the lagna specially auspicious, so its own second lordship does not blemish
  it.
* The aspects are the full graha drishti of BPHS 26.2-5: every graha aspects
  the 7th sign from itself; Saturn also the 3rd and 10th, Jupiter the 5th and
  9th, Mars the 4th and 8th. Rahu and Ketu own no sign and are never a lord.

THE DEFECTS THIS CLOSED
-----------------------
* Only one of the four relations was detected: the two lords standing in one
  sign. A kendra lord and a kona lord that exchanged signs, aspected each other
  across the chart, or with one standing in the other's sign made no Raja Yoga.
* 34.15 was not applied at all: a pair was served even when a lord other than
  the lagna lord also ruled the 3rd, 6th, 8th or 11th (Saturn, lord of the 10th
  and 11th for Aries, with the 9th lord Jupiter, for example).

WHAT IS PINNED
--------------
* A HAND TABLE, one row per ascendant, of every unordered pair of DIFFERENT
  grahas in which one rules a kendra and the other a kona, split into the pairs
  that form and the pairs 34.15 suppresses. It is counted by hand in whole signs
  from the ascendant and checked against the rule written out in this file.
* The detector on every ascendant, for every pair in the table, under each of
  the four relations alone, and with no relation at all.
* Worked examples computed by hand.
* The real ``/v1/yogas`` route for one birth per ascendant: the served pairs are
  exactly the formed pairs that the served positions relate.

The single-graha yogakaraka of 34.13 is pinned by
tests/test_raja_yoga_yogakaraka.py and is not changed here.

Synthetic charts only; no personal data.
"""
from __future__ import annotations

import datetime
from itertools import product

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData
from bphs_core.yogas import detect_raja_yogas

_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]
# Sign lords and graha drishti, written out here rather than imported from the
# engine.
_LORD = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn",
    "Pisces": "Jupiter",
}
_OWNS = {g: {s for s, lord in _LORD.items() if lord == g} for g in set(_LORD.values())}
# BPHS 26.2-5: the signs aspected, counted from the graha's own sign as 1.
_DRISHTI = {
    "Sun": {7}, "Moon": {7}, "Mercury": {7}, "Venus": {7},
    "Mars": {4, 7, 8}, "Jupiter": {5, 7, 9}, "Saturn": {3, 7, 10},
}


def _p(a: str, b: str) -> frozenset[str]:
    return frozenset({a, b})


# HAND TABLE: ascendant -> (pairs that form, pairs 34.15 suppresses). In the
# comment of each row: the kendra lords (K, houses 1, 4, 7, 10), the kona lords
# (T, houses 1, 5, 9) and the grahas blemished under 34.15 (lord of 3, 6, 8 or
# 11 and not the lagna lord).
_PAIRS: dict[str, tuple[set[frozenset[str]], set[frozenset[str]]]] = {
    # K: Mars, Moon, Venus, Saturn. T: Mars, Sun, Jupiter. Blemished: Mercury
    # (3, 6), Saturn (11). Mars rules the 8th but is the lagna lord.
    "Aries": (
        {_p("Mars", "Sun"), _p("Mars", "Jupiter"), _p("Moon", "Mars"),
         _p("Moon", "Sun"), _p("Moon", "Jupiter"), _p("Venus", "Mars"),
         _p("Venus", "Sun"), _p("Venus", "Jupiter")},
        {_p("Saturn", "Mars"), _p("Saturn", "Sun"), _p("Saturn", "Jupiter")},
    ),
    # K: Venus, Sun, Mars, Saturn. T: Venus, Mercury, Saturn. Blemished: Moon
    # (3), Jupiter (8, 11). Venus rules the 6th but is the lagna lord.
    "Taurus": (
        {_p("Venus", "Mercury"), _p("Venus", "Saturn"), _p("Sun", "Venus"),
         _p("Sun", "Mercury"), _p("Sun", "Saturn"), _p("Mars", "Venus"),
         _p("Mars", "Mercury"), _p("Mars", "Saturn"), _p("Saturn", "Mercury")},
        set(),
    ),
    # K: Mercury, Jupiter. T: Mercury, Venus, Saturn. Blemished: Sun (3), Mars
    # (6, 11), Saturn (8).
    "Gemini": (
        {_p("Mercury", "Venus"), _p("Jupiter", "Mercury"), _p("Jupiter", "Venus")},
        {_p("Mercury", "Saturn"), _p("Jupiter", "Saturn")},
    ),
    # K: Moon, Venus, Saturn, Mars. T: Moon, Mars, Jupiter. Blemished: Mercury
    # (3), Jupiter (6), Saturn (8), Venus (11).
    "Cancer": (
        {_p("Moon", "Mars")},
        {_p("Moon", "Jupiter"), _p("Venus", "Moon"), _p("Venus", "Mars"),
         _p("Venus", "Jupiter"), _p("Saturn", "Moon"), _p("Saturn", "Mars"),
         _p("Saturn", "Jupiter"), _p("Mars", "Jupiter")},
    ),
    # K: Sun, Mars, Saturn, Venus. T: Sun, Jupiter, Mars. Blemished: Venus (3),
    # Saturn (6), Jupiter (8), Mercury (11).
    "Leo": (
        {_p("Sun", "Mars")},
        {_p("Sun", "Jupiter"), _p("Mars", "Jupiter"), _p("Saturn", "Sun"),
         _p("Saturn", "Jupiter"), _p("Saturn", "Mars"), _p("Venus", "Sun"),
         _p("Venus", "Jupiter"), _p("Venus", "Mars")},
    ),
    # K: Mercury, Jupiter. T: Mercury, Saturn, Venus. Blemished: Mars (3, 8),
    # Saturn (6), Moon (11).
    "Virgo": (
        {_p("Mercury", "Venus"), _p("Jupiter", "Mercury"), _p("Jupiter", "Venus")},
        {_p("Mercury", "Saturn"), _p("Jupiter", "Saturn")},
    ),
    # K: Venus, Saturn, Mars, Moon. T: Venus, Saturn, Mercury. Blemished:
    # Jupiter (3, 6), Sun (11). Venus rules the 8th but is the lagna lord.
    "Libra": (
        {_p("Venus", "Saturn"), _p("Venus", "Mercury"), _p("Saturn", "Mercury"),
         _p("Mars", "Venus"), _p("Mars", "Saturn"), _p("Mars", "Mercury"),
         _p("Moon", "Venus"), _p("Moon", "Saturn"), _p("Moon", "Mercury")},
        set(),
    ),
    # K: Mars, Saturn, Venus, Sun. T: Mars, Jupiter, Moon. Blemished: Saturn
    # (3), Mercury (8, 11). Mars rules the 6th but is the lagna lord.
    "Scorpio": (
        {_p("Mars", "Jupiter"), _p("Mars", "Moon"), _p("Venus", "Mars"),
         _p("Venus", "Jupiter"), _p("Venus", "Moon"), _p("Sun", "Mars"),
         _p("Sun", "Jupiter"), _p("Sun", "Moon")},
        {_p("Saturn", "Mars"), _p("Saturn", "Jupiter"), _p("Saturn", "Moon")},
    ),
    # K: Jupiter, Mercury. T: Jupiter, Mars, Sun. Blemished: Saturn (3), Venus
    # (6, 11), Moon (8).
    "Sagittarius": (
        {_p("Jupiter", "Mars"), _p("Jupiter", "Sun"), _p("Mercury", "Jupiter"),
         _p("Mercury", "Mars"), _p("Mercury", "Sun")},
        set(),
    ),
    # K: Saturn, Mars, Moon, Venus. T: Saturn, Venus, Mercury. Blemished:
    # Jupiter (3), Mercury (6), Sun (8), Mars (11).
    "Capricorn": (
        {_p("Saturn", "Venus"), _p("Moon", "Saturn"), _p("Moon", "Venus")},
        {_p("Saturn", "Mercury"), _p("Mars", "Saturn"), _p("Mars", "Venus"),
         _p("Mars", "Mercury"), _p("Moon", "Mercury"), _p("Venus", "Mercury")},
    ),
    # K: Saturn, Venus, Sun, Mars. T: Saturn, Mercury, Venus. Blemished: Mars
    # (3), Moon (6), Mercury (8), Jupiter (11).
    "Aquarius": (
        {_p("Saturn", "Venus"), _p("Sun", "Saturn"), _p("Sun", "Venus")},
        {_p("Saturn", "Mercury"), _p("Venus", "Mercury"), _p("Sun", "Mercury"),
         _p("Mars", "Saturn"), _p("Mars", "Mercury"), _p("Mars", "Venus")},
    ),
    # K: Jupiter, Mercury. T: Jupiter, Moon, Mars. Blemished: Venus (3, 8), Sun
    # (6), Saturn (11).
    "Pisces": (
        {_p("Jupiter", "Moon"), _p("Jupiter", "Mars"), _p("Mercury", "Jupiter"),
         _p("Mercury", "Moon"), _p("Mercury", "Mars")},
        set(),
    ),
}

_PERSON = PersonalData(
    name="sample", birth_date=datetime.datetime(2000, 1, 1),
    birth_time=datetime.time(12, 0), birth_place="Sample City",
    latitude=0.0, longitude=0.0, timezone_offset_hours=0.0,
)


def _house(lagna: str, sign: str) -> int:
    return (_SIGNS.index(sign) - _SIGNS.index(lagna)) % 12 + 1


def _snapshot(lagna: str, placed: dict[str, str]) -> ChartSnapshot:
    """A whole-sign chart for *lagna*; ``placed`` maps graha -> sign."""
    first = _SIGNS.index(lagna)
    rasi = {
        name: PlanetData(
            planet=name, sign=sign, degrees=10.0, nakshatra="Ashwini",
            dignity="neutral", house=_house(lagna, sign), conjunctions=[],
            aspects=[], is_retrograde=False,
        )
        for name, sign in placed.items()
    }
    return ChartSnapshot(
        person=_PERSON, rasi_chart=rasi, hora_chart={}, drekkana_chart={},
        navamsa_chart={}, decamsa_chart={}, dwadasamsa_chart={},
        chaturvimsa_chart={}, trimshamsa_chart={}, saptamsa_chart={},
        shashtyamsa_chart={}, lagna=lagna, lagna_lord=_LORD[lagna],
        ayanamsa_value=0.0,
        house_cusps=[((first + i) % 12) * 30.0 for i in range(12)],
    )


def _aspects(graha: str, from_sign: str, to_sign: str) -> bool:
    offset = (_SIGNS.index(to_sign) - _SIGNS.index(from_sign)) % 12 + 1
    return offset in _DRISHTI[graha]


def _relations(a: str, sa: str, b: str, sb: str) -> set[str]:
    """The 34.11-12 relations between graha *a* in *sa* and *b* in *sb*."""
    found = set()
    if sa == sb:
        found.add("conjunct")
    if sa in _OWNS[b] and sb in _OWNS[a]:
        found.add("exchange")
    elif sa in _OWNS[b]:
        found.add("a_in_b")
    elif sb in _OWNS[a]:
        found.add("b_in_a")
    if sa != sb and _aspects(a, sa, sb) and _aspects(b, sb, sa):
        found.add("mutual_aspect")
    return found


def _placement(a: str, b: str, wanted: set[str]) -> tuple[str, str]:
    """The first pair of signs for *a* and *b* whose relations are EXACTLY
    *wanted*. Every case below has one; the assertion says so if not."""
    for sa, sb in product(_SIGNS, _SIGNS):
        if _relations(a, sa, b, sb) == wanted:
            return sa, sb
    raise AssertionError(f"no placement of {a} and {b} gives exactly {wanted}")


def _served_pairs(yogas) -> set[frozenset[str]]:
    """The served two-graha Raja Yogas as a set of pairs, after checking
    that no pair is served twice (a pair can hold several kendra/kona roles,
    Venus and Saturn for Taurus for one: 1st and 9th, and 10th and 1st)."""
    served = [
        frozenset(y.planets_involved)
        for y in yogas
        if y.name == "Raja Yoga" and len(y.planets_involved) == 2
    ]
    assert len(served) == len(set(served)), served
    return set(served)


# ---------------------------------------------------------------------------
# The hand table itself, checked against the rule it is read from
# ---------------------------------------------------------------------------

def _derived_pairs(lagna: str) -> tuple[set[frozenset[str]], set[frozenset[str]]]:
    """34.11-12 and 34.15 applied by hand."""
    first = _SIGNS.index(lagna)

    def lord_of(house: int) -> str:
        return _LORD[_SIGNS[(first + house - 1) % 12]]

    lagna_lord = lord_of(1)
    blemished = {lord_of(h) for h in (3, 6, 8, 11)} - {lagna_lord}
    candidates = {
        frozenset({lord_of(k), lord_of(t)})
        for k in (1, 4, 7, 10)
        for t in (1, 5, 9)
        if lord_of(k) != lord_of(t)
    }
    suppressed = {pair for pair in candidates if pair & blemished}
    return candidates - suppressed, suppressed


@pytest.mark.parametrize("lagna", _SIGNS)
def test_the_hand_table_is_the_rule_applied_to_each_ascendant(lagna):
    assert _derived_pairs(lagna) == _PAIRS[lagna]


def test_the_table_covers_every_ascendant_and_both_outcomes():
    assert sorted(_PAIRS) == sorted(_SIGNS)
    assert sum(len(formed) for formed, _ in _PAIRS.values()) == 58
    assert sum(len(suppressed) for _, suppressed in _PAIRS.values()) == 38


# ---------------------------------------------------------------------------
# The detector, every ascendant, every pair, every relation
# ---------------------------------------------------------------------------

_RELATIONS = {
    "conjunct": {"conjunct"},
    "exchange": {"exchange"},
    "first_in_second_sign": {"a_in_b"},
    "second_in_first_sign": {"b_in_a"},
    "mutual_aspect": {"mutual_aspect"},
}

_CASES = [
    (lagna, tuple(sorted(pair)), formed)
    for lagna, (formed_set, suppressed_set) in _PAIRS.items()
    for pair, formed in (
        [(p, True) for p in formed_set] + [(p, False) for p in suppressed_set]
    )
]


@pytest.mark.parametrize("relation", sorted(_RELATIONS))
@pytest.mark.parametrize("lagna,pair,formed", _CASES)
def test_each_relation_alone_forms_the_pair_unless_34_15_suppresses_it(
    lagna, pair, formed, relation
):
    a, b = pair
    sa, sb = _placement(a, b, _RELATIONS[relation])
    served = _served_pairs(detect_raja_yogas(_snapshot(lagna, {a: sa, b: sb})))
    assert served == ({frozenset(pair)} if formed else set()), (lagna, sa, sb)


@pytest.mark.parametrize("lagna,pair,formed", _CASES)
def test_an_aspect_one_way_only_is_no_raja_yoga(lagna, pair, formed):
    """34.11-12 asks that the two aspect EACH OTHER. Where one graha's
    special aspect reaches the other and nothing comes back, there is no
    relation. Mars, Jupiter or Saturn must be in the pair for that to be
    possible; other pairs have no such placement and are skipped here."""
    a, b = pair
    one_way = [
        (sa, sb) for sa, sb in product(_SIGNS, _SIGNS)
        if not _relations(a, sa, b, sb)
        and (_aspects(a, sa, sb) or _aspects(b, sb, sa))
    ]
    if not {a, b} & {"Mars", "Jupiter", "Saturn"}:
        assert one_way == []
        return
    assert one_way, (a, b)
    for sa, sb in one_way:
        served = _served_pairs(detect_raja_yogas(_snapshot(lagna, {a: sa, b: sb})))
        assert served == set(), (lagna, sa, sb)


@pytest.mark.parametrize("lagna,pair,formed", _CASES)
def test_no_relation_no_raja_yoga(lagna, pair, formed):
    a, b = pair
    sa, sb = _placement(a, b, set())
    served = _served_pairs(detect_raja_yogas(_snapshot(lagna, {a: sa, b: sb})))
    assert served == set(), (lagna, sa, sb)


@pytest.mark.parametrize("lagna", _SIGNS)
@pytest.mark.parametrize("sign", _SIGNS)
def test_all_grahas_together_serve_exactly_the_formed_pairs(lagna, sign):
    """Every graha in one sign: every pair is conjunct, so the served pairs
    are exactly the row's formed pairs and none of its suppressed ones."""
    placed = dict.fromkeys(_DRISHTI, sign)
    served = _served_pairs(detect_raja_yogas(_snapshot(lagna, placed)))
    assert served == _PAIRS[lagna][0]


# ---------------------------------------------------------------------------
# Worked examples, by hand
# ---------------------------------------------------------------------------

def _raja_pairs(lagna: str, placed: dict[str, str]):
    return [
        y for y in detect_raja_yogas(_snapshot(lagna, placed))
        if y.name == "Raja Yoga" and len(y.planets_involved) == 2
    ]


def test_worked_example_cancer_moon_and_mars_exchange_signs():
    """Cancer rising: the Moon rules the 1st (Cancer); Mars rules the 5th
    (Scorpio) and the 10th (Aries). The Moon in Aries (10th) and Mars in
    Cancer (1st) stand each in the other's sign: an exchange, 34.11-12, and
    neither lord rules the 3rd (Virgo, Mercury), 6th (Sagittarius, Jupiter),
    8th (Aquarius, Saturn) or 11th (Taurus, Venus). One Raja Yoga."""
    yogas = _raja_pairs("Cancer", {"Moon": "Aries", "Mars": "Cancer"})
    assert len(yogas) == 1
    assert sorted(yogas[0].planets_involved) == ["Mars", "Moon"]
    assert yogas[0].houses_involved == [1, 10]
    assert "exchange signs" in yogas[0].description


def test_worked_example_aries_moon_and_jupiter_in_mutual_aspect():
    """Aries rising: the Moon rules the 4th (Cancer), Jupiter the 9th
    (Sagittarius) and the 12th (Pisces), neither an evil house of 34.15. The
    Moon in Cancer and Jupiter in Capricorn are seven signs apart, so each
    aspects the other (26.2-5); neither stands in the other's sign. One Raja
    Yoga by mutual aspect."""
    yogas = _raja_pairs("Aries", {"Moon": "Cancer", "Jupiter": "Capricorn"})
    assert len(yogas) == 1
    assert sorted(yogas[0].planets_involved) == ["Jupiter", "Moon"]
    assert yogas[0].houses_involved == [4, 10]
    assert "mutual aspect" in yogas[0].description


def test_worked_example_sagittarius_mercury_in_the_sun_sign():
    """Sagittarius rising: Mercury rules the 7th (Gemini) and the 10th
    (Virgo), the Sun the 9th (Leo). Mercury in Leo (9th) stands in the Sun's
    sign; the Sun in Libra (11th) is in Venus's sign, and Leo and Libra are two
    signs apart, which neither graha aspects. One Raja Yoga, by Mercury standing
    in the kona lord's sign alone."""
    yogas = _raja_pairs("Sagittarius", {"Mercury": "Leo", "Sun": "Libra"})
    assert len(yogas) == 1
    assert sorted(yogas[0].planets_involved) == ["Mercury", "Sun"]
    assert yogas[0].houses_involved == [9, 11]
    assert "Mercury in Sun's sign" in yogas[0].description


def test_worked_example_aries_saturn_with_jupiter_is_suppressed():
    """Aries rising: Saturn rules the 10th (Capricorn) and the 11th
    (Aquarius); Jupiter rules the 9th. Together in Sagittarius they are a
    kendra lord and a kona lord in one sign, but Saturn also owns the 11th and
    is not the lagna lord, so 34.15 withholds the yoga."""
    assert _raja_pairs("Aries", {"Saturn": "Sagittarius", "Jupiter": "Sagittarius"}) == []


def test_worked_example_cancer_moon_with_jupiter_is_suppressed():
    """Cancer rising: Jupiter rules the 9th (Pisces) and also the 6th
    (Sagittarius). With the lagna lord Moon in Pisces the pair is related, but
    Jupiter is a 6th lord, so 34.15 withholds the yoga."""
    assert _raja_pairs("Cancer", {"Moon": "Pisces", "Jupiter": "Pisces"}) == []


def test_worked_example_libra_lagna_lord_owning_the_eighth_is_exempt():
    """Libra rising: Venus rules the 1st (Libra) and the 8th (Taurus). It is
    the lagna lord, so its 8th lordship does not blemish it: Venus with Saturn
    (lord of the 4th, Capricorn, and the 5th, Aquarius) in Capricorn is a Raja
    Yoga."""
    yogas = _raja_pairs("Libra", {"Venus": "Capricorn", "Saturn": "Capricorn"})
    assert len(yogas) == 1
    assert sorted(yogas[0].planets_involved) == ["Saturn", "Venus"]
    assert yogas[0].houses_involved == [4]
    assert "conjunct" in yogas[0].description


# ---------------------------------------------------------------------------
# Through the real routes, one real chart per ascendant
# ---------------------------------------------------------------------------

_BIRTH = {
    "name": "sample", "birth_date": "1990-06-15", "birth_place": "Sample City",
    "latitude": 12.0, "longitude": 77.0, "timezone_offset_hours": 5.5,
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers={"X-Calc-Service-Token": "test"}) as c:
        yield c


@pytest.fixture(scope="module")
def one_birth_per_ascendant(client) -> dict[str, dict]:
    """Step the birth time through one day and keep the first birth found for
    each of the twelve ascendants, as the chart route itself reports it."""
    found: dict[str, dict] = {}
    for minutes in range(0, 24 * 60, 20):
        person = {**_BIRTH, "birth_time": f"{minutes // 60:02d}:{minutes % 60:02d}:00"}
        r = client.post("/v1/chart", json=person)
        assert r.status_code == 200, r.text
        found.setdefault(r.json()["lagna"], {"person": person, "chart": r.json()})
    assert sorted(found) == sorted(_SIGNS)
    return found


@pytest.mark.parametrize("lagna", _SIGNS)
def test_yogas_route_serves_exactly_the_formed_pairs_the_chart_relates(
    client, one_birth_per_ascendant, lagna
):
    birth = one_birth_per_ascendant[lagna]
    signs = {p["planet"]: p["sign"] for p in birth["chart"]["rasi"]}
    expected = set()
    for pair in _PAIRS[lagna][0]:
        a, b = sorted(pair)
        if _relations(a, signs[a], b, signs[b]):
            expected.add(pair)
    r = client.post("/v1/yogas", json=birth["person"])
    assert r.status_code == 200, r.text
    served = {
        frozenset(y["planets_involved"])
        for y in r.json()
        if y["name"] == "Raja Yoga" and len(y["planets_involved"]) == 2
    }
    assert served == expected, lagna
