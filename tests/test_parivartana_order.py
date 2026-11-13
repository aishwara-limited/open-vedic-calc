"""Parivartana Yoga: one fixed wording and one fixed order for every exchange.

The detector used to iterate a ``set`` of graha names. A set of strings is
ordered by string hash, and string hashing is randomised per interpreter start,
so the same chart produced "Saturn in Libra (owned by Venus) exchanges signs
with Venus in Aquarius ..." from one process and "Venus in Aquarius (owned by
Saturn) exchanges signs with Saturn in Libra ..." from the next, and a chart
with two exchanges listed them in either order. Nothing astrological changed;
the served bytes did, which defeats exact replay and response caching.

The order is now the engine's declared graha order (``utils.PLANETS``: Sun,
Moon, Mars, Mercury, Jupiter, Venus, Saturn): the graha that comes first in it
is named first, and exchanges are listed in the order of their first-named
graha. The expectations below are written out by hand from the classical sign
lordships, never derived from the detector or from the engine's own lord table.
"""
from __future__ import annotations

import itertools

from bphs_core.yogas import detect_parivartana_yoga
from tests.test_yogas_spec import mock_chart

_GRAHA_ORDER = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")

_SIGNS = ("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
          "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces")

# The classical sign lordships, by hand: Mars rules Aries and Scorpio, Venus
# Taurus and Libra, Mercury Gemini and Virgo, the Moon Cancer, the Sun Leo,
# Jupiter Sagittarius and Pisces, Saturn Capricorn and Aquarius.
_LORD = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn",
    "Pisces": "Jupiter",
}


def _house_from_aries(sign: str) -> int:
    return _SIGNS.index(sign) + 1


def _description(first: str, first_sign: str, second: str, second_sign: str) -> str:
    return (
        f"{first} in {first_sign} (owned by {second}) exchanges signs with "
        f"{second} in {second_sign} (owned by {first}) — houses "
        f"{_house_from_aries(first_sign)} and {_house_from_aries(second_sign)} "
        "deeply interlinked"
    )


def test_every_pair_and_sign_placement_is_named_in_graha_order() -> None:
    """All 21 graha pairs x 144 sign placements: exchange found iff it exists,
    and when it does, the graha earlier in the declared order is named first."""
    checked_exchanges = 0
    for g1, g2 in itertools.combinations(_GRAHA_ORDER, 2):
        for s1, s2 in itertools.product(_SIGNS, repeat=2):
            chart = mock_chart({
                g1: {"sign": s1, "house": _house_from_aries(s1)},
                g2: {"sign": s2, "house": _house_from_aries(s2)},
            })
            found = detect_parivartana_yoga(chart)
            exchange = _LORD[s1] == g2 and _LORD[s2] == g1
            if not exchange:
                assert found == [], (g1, s1, g2, s2, [y.description for y in found])
                continue
            checked_exchanges += 1
            assert [y.description for y in found] == [_description(g1, s1, g2, s2)], (
                g1, s1, g2, s2)
            assert found[0].planets_involved == sorted([g1, g2])
    # Sun/Moon have one sign each, the other five two: 1 + 5*2 + 5*2 + 10*4 = 61.
    assert checked_exchanges == 61


def test_worked_example_venus_saturn_names_venus_first() -> None:
    """Venus in Aquarius (11th from an Aries lagna), Saturn in Libra (7th)."""
    chart = mock_chart({
        "Saturn": {"sign": "Libra", "house": 7},
        "Venus": {"sign": "Aquarius", "house": 11},
    })
    assert [y.description for y in detect_parivartana_yoga(chart)] == [
        "Venus in Aquarius (owned by Saturn) exchanges signs with Saturn in Libra "
        "(owned by Venus) — houses 11 and 7 deeply interlinked",
    ]


def test_worked_example_two_exchanges_are_listed_in_graha_order() -> None:
    """Sun/Mars and Jupiter/Saturn: the Sun's exchange first, then Jupiter's."""
    chart = mock_chart({
        "Saturn": {"sign": "Pisces", "house": 12},
        "Jupiter": {"sign": "Capricorn", "house": 10},
        "Mars": {"sign": "Leo", "house": 5},
        "Sun": {"sign": "Aries", "house": 1},
    })
    assert [y.description for y in detect_parivartana_yoga(chart)] == [
        "Sun in Aries (owned by Mars) exchanges signs with Mars in Leo "
        "(owned by Sun) — houses 1 and 5 deeply interlinked",
        "Jupiter in Capricorn (owned by Saturn) exchanges signs with Saturn in "
        "Pisces (owned by Jupiter) — houses 10 and 12 deeply interlinked",
    ]
