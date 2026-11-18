"""The single-graha Raja Yoga is the classical yogakaraka, and nothing wider.

THE RULE (Brihat Parashara Hora Shastra, ch. 34, the chapter on yoga-karakas;
sloka numbers in the standard Sanskrit numbering)
---------------------------------------------------------------------------
* 34.11-12: the lord of a kendra and the lord of a kona form a yoga when they
  exchange houses, sit together in one sign, one sits in the other's sign, or
  they aspect each other fully.
* 34.13: when ONE graha holds the lordship of a kona and of a kendra, it is a
  yogakaraka in its own right.
* 34.3: the lagna is at once a kendra and a kona, which is why the lagna itself
  is specially auspicious. That is a statement about the lagna, and the text
  does not go on to pair the lagna with its lord's OTHER house.
* 34.19-44 then go through the twelve ascendants. A single graha is named as the
  maker of the yoga for Taurus (34.23, Saturn), Cancer (34.27, Mars), Capricorn
  (34.40, Venus alone) and Aquarius (34.41, Venus alone); Mars for Leo (34.29)
  and Saturn for Libra (34.33) are counted auspicious and rule a kendra and a
  kona each. For the four dual-sign ascendants, whose lord also rules the 4th
  or the 10th, the lord is never named alone: Gemini has "Venus alone
  auspicious" (34.25); Virgo names Venus and Mercury as a pair (34.31),
  Sagittarius the Sun and Mercury (34.37) and Pisces Mars and Jupiter (34.43).

So a graha is a yogakaraka by lordship when it rules a kendra other than the
lagna (4th, 7th or 10th) AND a kona other than the lagna (5th or 9th). That
happens for exactly six ascendants.

THE DEFECT THIS CLOSED
----------------------
The detector kept the first house in both the kendra list and the kona list (it
has to, for the pair rule: the lagna lord joining the 5th or 9th lord is a Raja
Yoga) and skipped only the first house paired with itself. So the lagna lord of
Gemini (1st + 4th), Virgo (1st + 10th), Sagittarius (1st + 4th) and Pisces
(1st + 10th) was served as "lords both kendra and trikona" on every chart with
those ascendants, wherever it stood -- a Raja Yoga as a fixed property of four
of the twelve ascendants, which no text supports. The same response already
contradicted itself: ``yoga_karaka`` on ``/v1/chart`` was empty for those four.

WHAT IS PINNED
--------------
* All twelve ascendants, with an EMPTY rasi chart so no placement can add a
  yoga: the single-graha entry appears for the six classical ascendants, with
  the classical graha and houses, and for no other.
* The same twelve through the real routes: ``/v1/yogas`` agrees with the table
  and with the ``yoga_karaka`` served by ``/v1/chart`` for the same birth.
* The lagna lord still makes a Raja Yoga WITH a kona lord (the pair rule), on a
  dual-sign ascendant too.

The expected values are a hand table read from the verses above and a
derivation written out here -- never values copied from the detector.

Synthetic charts only; no personal data.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData
from bphs_core.yogas import detect_all_yogas, detect_raja_yogas, get_yoga_karaka_planet

_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]
# Sign lords, written out here rather than imported from the engine.
_LORD = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn",
    "Pisces": "Jupiter",
}

# HAND TABLE: ascendant -> (yogakaraka, [the kendra and the kona it rules]),
# or None. Read from BPHS ch. 34 as cited in the module docstring; the houses
# are counted by hand in whole signs from the ascendant.
_YOGAKARAKA = {
    "Aries": None,                      # 34.19-22: no single maker
    "Taurus": ("Saturn", [9, 10]),      # 34.23: Capricorn 9th, Aquarius 10th
    "Gemini": None,                     # 34.25: Venus alone auspicious
    "Cancer": ("Mars", [5, 10]),        # 34.27: Scorpio 5th, Aries 10th
    "Leo": ("Mars", [4, 9]),            # 34.29: Scorpio 4th, Aries 9th
    "Virgo": None,                      # 34.31: Venus and Mercury as a pair
    "Libra": ("Saturn", [4, 5]),        # 34.33: Capricorn 4th, Aquarius 5th
    "Scorpio": None,                    # 34.35-36: no single maker
    "Sagittarius": None,                # 34.37: the Sun and Mercury as a pair
    "Capricorn": ("Venus", [5, 10]),    # 34.40: Taurus 5th, Libra 10th
    "Aquarius": ("Venus", [4, 9]),      # 34.41: Taurus 4th, Libra 9th
    "Pisces": None,                     # 34.43: Mars and Jupiter as a pair
}

_PERSON = PersonalData(
    name="sample", birth_date=datetime.datetime(2000, 1, 1),
    birth_time=datetime.time(12, 0), birth_place="Sample City",
    latitude=0.0, longitude=0.0, timezone_offset_hours=0.0,
)


def _snapshot(lagna: str, planets: dict[str, tuple[str, int]] | None = None) -> ChartSnapshot:
    """A whole-sign chart for *lagna*. ``planets`` maps graha -> (sign, house);
    left empty, no graha has a position, so only lordship can make a yoga."""
    first = _SIGNS.index(lagna)
    rasi = {
        name: PlanetData(
            planet=name, sign=sign, degrees=10.0, nakshatra="Ashwini",
            dignity="neutral", house=house, conjunctions=[], aspects=[],
            is_retrograde=False,
        )
        for name, (sign, house) in (planets or {}).items()
    }
    return ChartSnapshot(
        person=_PERSON, rasi_chart=rasi, hora_chart={}, drekkana_chart={},
        navamsa_chart={}, decamsa_chart={}, dwadasamsa_chart={},
        chaturvimsa_chart={}, trimshamsa_chart={}, saptamsa_chart={},
        shashtyamsa_chart={}, lagna=lagna, lagna_lord=_LORD[lagna],
        ayanamsa_value=0.0,
        house_cusps=[((first + i) % 12) * 30.0 for i in range(12)],
    )


def _single_graha_raja_yogas(yogas) -> list[tuple[str, list[int]]]:
    return [
        (y.planets_involved[0], y.houses_involved)
        for y in yogas
        if y.name == "Raja Yoga" and len(y.planets_involved) == 1
    ]


# ---------------------------------------------------------------------------
# The hand table itself, checked against the rule it is read from
# ---------------------------------------------------------------------------

def _derived_yogakaraka(lagna: str) -> tuple[str, list[int]] | None:
    """34.13 applied by hand: the graha ruling a kendra other than the lagna
    (4, 7, 10) and a kona other than the lagna (5, 9)."""
    first = _SIGNS.index(lagna)

    def lord_of(house: int) -> str:
        return _LORD[_SIGNS[(first + house - 1) % 12]]

    found = {
        lord_of(k): sorted({k, t})
        for k in (4, 7, 10)
        for t in (5, 9)
        if lord_of(k) == lord_of(t)
    }
    assert len(found) <= 1, (lagna, found)
    return next(iter(found.items()), None)


@pytest.mark.parametrize("lagna", _SIGNS)
def test_the_hand_table_is_the_rule_applied_to_each_ascendant(lagna):
    assert _derived_yogakaraka(lagna) == _YOGAKARAKA[lagna]


def test_exactly_six_ascendants_have_a_yogakaraka():
    assert sorted(k for k, v in _YOGAKARAKA.items() if v) == [
        "Aquarius", "Cancer", "Capricorn", "Leo", "Libra", "Taurus",
    ]


# ---------------------------------------------------------------------------
# The detector, on every ascendant, with nothing placed anywhere
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lagna", _SIGNS)
def test_single_graha_raja_yoga_is_the_classical_yogakaraka(lagna):
    served = _single_graha_raja_yogas(detect_raja_yogas(_snapshot(lagna)))
    expected = _YOGAKARAKA[lagna]
    assert served == ([expected] if expected else []), lagna


@pytest.mark.parametrize("lagna", _SIGNS)
def test_no_raja_yoga_at_all_without_a_placement_unless_a_yogakaraka(lagna):
    """With an empty rasi chart the pair rule cannot fire, so the WHOLE yoga
    list holds at most the one yogakaraka entry."""
    yogas = [y for y in detect_all_yogas(_snapshot(lagna)) if y.name == "Raja Yoga"]
    assert len(yogas) == (1 if _YOGAKARAKA[lagna] else 0), lagna


@pytest.mark.parametrize("lagna", _SIGNS)
def test_the_detector_and_the_served_yoga_karaka_field_agree(lagna):
    snapshot = _snapshot(lagna)
    served = _single_graha_raja_yogas(detect_raja_yogas(snapshot))
    named = get_yoga_karaka_planet(snapshot)
    assert [graha for graha, _ in served] == ([named] if named else []), lagna
    assert named == (_YOGAKARAKA[lagna][0] if _YOGAKARAKA[lagna] else ""), lagna


# Two worked examples, by hand.
def test_worked_example_taurus_saturn_rules_the_ninth_and_tenth():
    """Taurus rising: the 9th sign from Taurus is Capricorn and the 10th is
    Aquarius, both Saturn's. One graha, a kona (9) and a kendra (10): the
    yogakaraka of 34.13, and 34.23 says so in words."""
    assert _single_graha_raja_yogas(detect_raja_yogas(_snapshot("Taurus"))) == [
        ("Saturn", [9, 10]),
    ]


def test_worked_example_gemini_mercury_rules_the_first_and_fourth_only():
    """Gemini rising: Mercury rules the 1st (Gemini) and the 4th (Virgo). The
    konas are Libra (5th, Venus) and Aquarius (9th, Saturn); the other kendras
    are Sagittarius (7th) and Pisces (10th), both Jupiter's. No graha rules a
    kendra and a kona, and 34.25 names Venus alone as auspicious -- so there is
    no single-graha Raja Yoga, wherever Mercury stands."""
    for house in range(1, 13):
        sign = _SIGNS[(_SIGNS.index("Gemini") + house - 1) % 12]
        snapshot = _snapshot("Gemini", {"Mercury": (sign, house)})
        assert _single_graha_raja_yogas(detect_raja_yogas(snapshot)) == [], house


@pytest.mark.parametrize("lagna", ["Gemini", "Virgo", "Sagittarius", "Pisces"])
@pytest.mark.parametrize("house", range(1, 13))
def test_a_dual_sign_lagna_lord_alone_is_never_a_raja_yoga(lagna, house):
    """The four ascendants the defect touched, the lagna lord in every house."""
    lord = _LORD[lagna]
    sign = _SIGNS[(_SIGNS.index(lagna) + house - 1) % 12]
    yogas = detect_raja_yogas(_snapshot(lagna, {lord: (sign, house)}))
    assert [y for y in yogas if y.name == "Raja Yoga"] == []


@pytest.mark.parametrize("house", range(1, 13))
def test_a_yogakaraka_is_one_by_lordship_wherever_it_stands(house):
    """34.13 makes the graha a yogakaraka by its two lordships; the entry does
    not depend on the house it occupies."""
    sign = _SIGNS[(_SIGNS.index("Taurus") + house - 1) % 12]
    yogas = detect_raja_yogas(_snapshot("Taurus", {"Saturn": (sign, house)}))
    assert _single_graha_raja_yogas(yogas) == [("Saturn", [9, 10])]


# ---------------------------------------------------------------------------
# House 1 counts on NEITHER side of the single-graha rule
# ---------------------------------------------------------------------------
# With the classical sign lords the lagna lord can share a house only with the
# 4th or 10th, so real charts exercise the "kona is the lagna" half alone. The
# rule is stated for both halves, and each is pinned here with a lordship table
# written for the purpose: only which houses share a lord matters to the rule.

@pytest.mark.parametrize(
    "shared,expected",
    [
        ((4, 5), [("X", [4, 5])]),    # a kendra and a kona away from the lagna
        ((10, 9), [("X", [9, 10])]),
        ((7, 5), [("X", [5, 7])]),
        ((4, 1), []),                 # the kona is the lagna
        ((10, 1), []),
        ((1, 5), []),                 # the kendra is the lagna
        ((1, 9), []),
        ((4, 5, 9), [("X", [4, 5])]),  # one graha, one entry
    ],
    ids=lambda v: "-".join(map(str, v)) if isinstance(v, tuple) else None,
)
def test_house_one_counts_on_neither_side(monkeypatch, shared, expected):
    from bphs_core import yogas as yogas_mod

    lords = {house: f"L{house}" for house in range(1, 13)}
    for house in shared:
        lords[house] = "X"
    monkeypatch.setattr(yogas_mod, "_house_lord", lambda _snapshot, house: lords[house])
    served = _single_graha_raja_yogas(yogas_mod.detect_raja_yogas(_snapshot("Aries")))
    assert served == expected


# ---------------------------------------------------------------------------
# The pair rule keeps the lagna lord
# ---------------------------------------------------------------------------

def test_the_lagna_lord_joining_a_kona_lord_is_still_a_raja_yoga():
    """Virgo rising, 34.31: Venus (9th lord) with Mercury (lagna and 10th lord)
    makes the yoga. Both in the 9th, Taurus."""
    yogas = detect_raja_yogas(
        _snapshot("Virgo", {"Mercury": ("Taurus", 9), "Venus": ("Taurus", 9)})
    )
    raja = [y for y in yogas if y.name == "Raja Yoga"]
    assert len(raja) == 1
    assert sorted(raja[0].planets_involved) == ["Mercury", "Venus"]
    assert raja[0].houses_involved == [9]


def test_the_same_pair_apart_makes_no_raja_yoga():
    yogas = detect_raja_yogas(
        _snapshot("Virgo", {"Mercury": ("Taurus", 9), "Venus": ("Gemini", 10)})
    )
    assert [y for y in yogas if y.name == "Raja Yoga"] == []


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
def test_yogas_route_serves_the_classical_yogakaraka_only(
    client, one_birth_per_ascendant, lagna
):
    birth = one_birth_per_ascendant[lagna]
    r = client.post("/v1/yogas", json=birth["person"])
    assert r.status_code == 200, r.text
    served = [
        (y["planets_involved"][0], y["houses_involved"])
        for y in r.json()
        if y["name"] == "Raja Yoga" and len(y["planets_involved"]) == 1
    ]
    expected = _YOGAKARAKA[lagna]
    assert served == ([expected] if expected else []), lagna
    # ... and it is the graha the chart route names for the same birth.
    assert birth["chart"]["yoga_karaka"] == (expected[0] if expected else ""), lagna
