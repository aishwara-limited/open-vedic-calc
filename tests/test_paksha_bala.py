"""The Moon's benefic/malefic polarity, wherever Shadbala reads it.

BPHS 3.11 makes the waning Moon a malefic. Waxing = (Moon - Sun) mod 360 in
the open interval (0, 180); the boundaries 0 and 180 are not waxing. The same
polarity must decide all three places it is read:

  1. paksha bala (BPHS 27.10-11): a benefic takes arc / 3, a malefic 60 less;
  2. drik bala (BPHS 27.19): a quarter of the Moon's drishti added when she
     is benefic, deducted when she is malefic;
  3. bhava drishti bala (BPHS 27.29): the same rule on a bhava's point.

All fixtures are synthetic; no personal data used.
"""
import pytest

from bphs_core import strength as st
from bphs_core.strength import StrengthInputs

_OTHERS_FAR_AWAY = {"Mars": 300.0, "Mercury": 330.0, "Jupiter": 320.0,
                    "Venus": 310.0, "Saturn": 305.0, "Rahu": 250.0, "Ketu": 70.0}


def _inputs(sun: float, moon: float) -> StrengthInputs:
    return StrengthInputs(
        longitudes={"Sun": sun, "Moon": moon, **_OTHERS_FAR_AWAY},
        latitudes={}, varga_signs={}, ayanamsa=0.0, ascendant=0.0,
        midheaven=270.0, birth_jd=2451545.0, sunrise_jd=2451544.8,
        sunset_jd=2451545.3, next_sunrise_jd=2451545.8,
        local_apparent_hours=12.0, hindu_day_jdn=2451545,
    )


@pytest.mark.parametrize("elongation,waxing", [
    (90.0, True), (270.0, False), (0.0, False), (180.0, False),
    (179.999, True), (180.001, False), (0.001, True),
])
def test_moon_paksha_follows_her_phase(elongation, waxing):
    """The Moon's own paksha bala: arc/3 while waxing, 60 - arc/3 while
    waning (not doubled, Santhanam's BPHS 27.10-11)."""
    inp = _inputs(10.0, (10.0 + elongation) % 360.0)
    arc = min(elongation, 360.0 - elongation)
    want = arc / 3.0 if waxing else 60.0 - arc / 3.0
    assert st._paksha_bala("Moon", inp) == pytest.approx(want)


def test_elongation_wraps_across_zero_aries():
    """Sun 350, Moon 20: elongation 30, waxing."""
    assert st.is_benefic("Moon", {"Sun": 350.0, "Moon": 20.0}) is True
    assert st.is_benefic("Moon", {"Sun": 20.0, "Moon": 350.0}) is False


@pytest.mark.parametrize("moon,sign", [(160.0, 1), (220.0, -1)])
def test_moon_drik_and_bhava_drishti_share_her_polarity(moon, sign):
    """The point 180 degrees from the Moon receives her full drishti, 60.
    With the Sun at 10, a Moon at 160 is waxing and adds a quarter (+15); at
    220 she is waning and deducts it (-15). Every other graha sits 5 degrees
    behind the point and the Sun 330 or 30 degrees behind it, where every
    drishti is nil (BPHS 26.6-12), so the Moon's quarter is all there is,
    on a graha (drik bala) and on a bhava's point alike."""
    target = (moon + 180.0) % 360.0
    longitudes = {"Sun": 10.0, "Moon": moon}
    longitudes.update({g: (target - 5.0) % 360.0 for g in _OTHERS_FAR_AWAY})
    assert st.sphuta_drishti("Moon", target - moon) == 60.0
    assert st._aspect_strength(target, longitudes) == pytest.approx(sign * 15.0)
    inp = StrengthInputs(
        longitudes=longitudes, latitudes={}, varga_signs={}, ayanamsa=0.0,
        ascendant=target, midheaven=(target - 90.0) % 360.0, birth_jd=2451545.0,
        sunrise_jd=2451544.8, sunset_jd=2451545.3, next_sunrise_jd=2451545.8,
        local_apparent_hours=12.0, hindu_day_jdn=2451545,
    )
    assert st.bhava_virupas(1, inp)[1] == pytest.approx(sign * 15.0)
