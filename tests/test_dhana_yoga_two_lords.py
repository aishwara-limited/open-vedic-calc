"""A Dhana Yoga by association needs two DIFFERENT lords.

THE RULE
--------
The engine's Dhana Yoga is the association of two house lords: the lord of the
2nd with the lord of the 11th, or the lord of the 5th with the lord of the 9th,
standing in one sign. An association is a relation between two grahas. When ONE
graha rules both houses of a pair there is nothing for it to associate with: a
graha is never conjunct with itself.

That happens for exactly two ascendants, counted by hand in whole signs:

* Leo rising: the 2nd is Virgo and the 11th is Gemini, both Mercury's.
* Aquarius rising: the 2nd is Pisces and the 11th is Sagittarius, both
  Jupiter's.

The 5th and the 9th are four signs apart, and no graha rules two signs four
apart (Mars's signs are 7 apart, Venus's 5, Mercury's and Jupiter's 3, Saturn's
1), so the 5/9 pair always has two lords.

Brihat Parashara Hora Shastra grants no wealth yoga to a single graha for
ruling both the 2nd and the 11th; for these two ascendants its own verdict on
that graha is the opposite. Ch. 34 (sloka numbers in the standard Sanskrit
numbering) names Mercury among the malefics for Leo (34.29-30) and Jupiter
among the killers for Aquarius (34.41-42). So the single graha gets no Dhana
Yoga entry of any kind here.

THE DEFECT THIS CLOSED
----------------------
``detect_dhana_yogas`` compared the houses of the two lords of a pair without
checking that they were two grahas. For Leo and Aquarius both lookups returned
the same graha, its house always equalled itself, and every Leo and every
Aquarius chart was served "Mercury and Mercury conjunct" or "Jupiter and Jupiter
conjunct" as a wealth yoga, wherever the graha stood.

Synthetic charts only; no personal data.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bphs_core.chart import ChartSnapshot, PersonalData, PlanetData
from bphs_core.yogas import detect_all_yogas, detect_dhana_yogas

_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]
_LORD = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn",
    "Pisces": "Jupiter",
}
_GRAHAS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")

# HAND TABLE: ascendant -> ((2nd lord, 11th lord), (5th lord, 9th lord)),
# counted by hand in whole signs from the ascendant.
_LORDS = {
    "Aries": (("Venus", "Saturn"), ("Sun", "Jupiter")),
    "Taurus": (("Mercury", "Jupiter"), ("Mercury", "Saturn")),
    "Gemini": (("Moon", "Mars"), ("Venus", "Saturn")),
    "Cancer": (("Sun", "Venus"), ("Mars", "Jupiter")),
    "Leo": (("Mercury", "Mercury"), ("Jupiter", "Mars")),
    "Virgo": (("Venus", "Moon"), ("Saturn", "Venus")),
    "Libra": (("Mars", "Sun"), ("Saturn", "Mercury")),
    "Scorpio": (("Jupiter", "Mercury"), ("Jupiter", "Moon")),
    "Sagittarius": (("Saturn", "Venus"), ("Mars", "Sun")),
    "Capricorn": (("Saturn", "Mars"), ("Venus", "Mercury")),
    "Aquarius": (("Jupiter", "Jupiter"), ("Mercury", "Venus")),
    "Pisces": (("Mars", "Saturn"), ("Moon", "Mars")),
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


def _dhana(yogas) -> list[tuple[list[str], list[int]]]:
    return [(y.planets_involved, y.houses_involved) for y in yogas if y.name == "Dhana Yoga"]


@pytest.mark.parametrize("lagna", _SIGNS)
def test_the_hand_table_is_the_lordship_of_each_ascendant(lagna):
    first = _SIGNS.index(lagna)

    def lord_of(house: int) -> str:
        return _LORD[_SIGNS[(first + house - 1) % 12]]

    assert _LORDS[lagna] == ((lord_of(2), lord_of(11)), (lord_of(5), lord_of(9)))


def test_exactly_leo_and_aquarius_have_one_lord_for_the_second_and_eleventh():
    assert sorted(k for k, (two_eleven, _) in _LORDS.items() if two_eleven[0] == two_eleven[1]) == [
        "Aquarius", "Leo",
    ]
    assert [k for k, (_, five_nine) in _LORDS.items() if five_nine[0] == five_nine[1]] == []


@pytest.mark.parametrize("lagna", _SIGNS)
@pytest.mark.parametrize("sign", _SIGNS)
def test_all_grahas_together_serve_one_dhana_yoga_per_pair_of_two_lords(lagna, sign):
    """Every graha in one sign, so every pair of two lords is together. The
    served Dhana Yogas are exactly the pairs whose two lords differ."""
    two_eleven, five_nine = _LORDS[lagna]
    expected = [
        (list(lords), houses)
        for lords, houses in ((two_eleven, [2, 11]), (five_nine, [5, 9]))
        if lords[0] != lords[1]
    ]
    served = _dhana(detect_dhana_yogas(_snapshot(lagna, dict.fromkeys(_GRAHAS, sign))))
    assert served == expected


@pytest.mark.parametrize("lagna,graha", [("Leo", "Mercury"), ("Aquarius", "Jupiter")])
@pytest.mark.parametrize("sign", _SIGNS)
def test_the_lord_of_both_the_second_and_eleventh_alone_is_no_dhana_yoga(lagna, graha, sign):
    """Worked by hand: Leo's 2nd (Virgo) and 11th (Gemini) are Mercury's;
    Aquarius's 2nd (Pisces) and 11th (Sagittarius) are Jupiter's. That graha,
    the only one placed, in each of the twelve signs: no Dhana Yoga at all."""
    assert _dhana(detect_all_yogas(_snapshot(lagna, {graha: sign}))) == []


def test_worked_example_leo_mercury_in_virgo_with_the_fifth_and_ninth_lords_apart():
    """Leo rising, Mercury in Virgo (2nd, its own sign), Jupiter (5th lord,
    Sagittarius) in Aries and Mars (9th lord, Aries) in Taurus. No two lords of
    a pair share a sign, so there is no Dhana Yoga."""
    placed = {"Mercury": "Virgo", "Jupiter": "Aries", "Mars": "Taurus"}
    assert _dhana(detect_all_yogas(_snapshot("Leo", placed))) == []


def test_worked_example_aquarius_mercury_and_venus_together():
    """Aquarius rising: the 5th is Gemini (Mercury) and the 9th Libra (Venus).
    Mercury and Venus together in Libra are two lords of the 5/9 pair in one
    sign: one Dhana Yoga. Jupiter, lord of both the 2nd and the 11th, stands
    with them and adds nothing."""
    placed = {"Mercury": "Libra", "Venus": "Libra", "Jupiter": "Libra"}
    assert _dhana(detect_all_yogas(_snapshot("Aquarius", placed))) == [
        (["Mercury", "Venus"], [5, 9]),
    ]


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
def test_yogas_route_serves_the_dhana_yogas_the_chart_positions_make(
    client, one_birth_per_ascendant, lagna
):
    birth = one_birth_per_ascendant[lagna]
    signs = {p["planet"]: p["sign"] for p in birth["chart"]["rasi"]}
    two_eleven, five_nine = _LORDS[lagna]
    expected = [
        {"planets_involved": list(lords), "houses_involved": houses}
        for lords, houses in ((two_eleven, [2, 11]), (five_nine, [5, 9]))
        if lords[0] != lords[1] and signs[lords[0]] == signs[lords[1]]
    ]
    r = client.post("/v1/yogas", json=birth["person"])
    assert r.status_code == 200, r.text
    served = [
        {"planets_involved": y["planets_involved"], "houses_involved": y["houses_involved"]}
        for y in r.json()
        if y["name"] == "Dhana Yoga"
    ]
    assert served == expected, lagna
