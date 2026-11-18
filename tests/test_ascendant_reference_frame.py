"""The ascendant is served in the same reference frame as the grahas.

THE FRAME
---------
A sidereal longitude is measured from a point fixed among the stars. The
tropical longitude of date is measured from the TRUE equinox, which nutation
swings back and forth along the ecliptic by up to about 19 arcsec over an
18.6-year cycle. To reach the sidereal value both the slow precession (the mean
ayanamsa) and that swing (the nutation in longitude) have to come off:

    sidereal = tropical(true equinox of date) - nutation in longitude - mean ayanamsa

That is the frame every graha is served in: the position word carries the
sidereal flag, and the ephemeris then leaves nutation out of the position and
subtracts the mean ayanamsa (``bphs_core/utils.py``, ``POSITION_FLAGS``). It is
the only consistent choice -- putting the nutation back would make every
sidereal longitude wobble against the stars it is measured from.

THE DEFECT THIS CLOSED
----------------------
The ascendant and the Bhava-Chalit cusps were built as the tropical house
points minus the MEAN ayanamsa only. The nutation term was left in, so the
lagna sat in a different frame from the grahas, off by the nutation in
longitude for the birth epoch: +17.4 arcsec in 1936, -18.2 arcsec in 1982 and
2001. That is about 1.2 seconds of birth time. It moved the lagna SIGN only for
a birth within that distance of a sign boundary -- two such births are worked
below -- but the same shift went into the varga lagna of every divisional chart
and into all twelve cusps.

The ascendant and cusps now come from the library's own sidereal house call
(``bphs_core.utils.sidereal_houses``), which removes both terms.

WHAT IS PINNED
--------------
* Through ``POST /v1/chart``: all twelve served cusps equal the tropical house
  points of date minus the nutation in longitude minus the mean Lahiri
  ayanamsa, each taken from the ephemeris directly, to 0.01 arcsec.
* The first cusp also equals the ascendant worked from the spherical-astronomy
  formula (apparent sidereal time, true obliquity, latitude), reduced the same
  way.
* The ascendant and each classical graha differ from their tropical
  true-equinox longitudes by ONE common amount.
* Two births beside a sign boundary are served the lagna of the consistent
  frame, and every house and the navamsa lagna follow it.
* The polar fallback is in the same frame, and so is a thread that has never
  computed before.

Every expected value is computed here from the ephemeris or by hand; none is
read back from the engine. The tolerances hold on the Swiss data files and on
the analytical fallback alike: house points, nutation and the ayanamsa read no
data file.

Synthetic charts only; no personal data.
"""
from __future__ import annotations

import datetime
import math
import threading

import pytest
import swisseph as swe
from fastapi.testclient import TestClient

from app.main import app
from bphs_core import utils
from bphs_core.chart import Chart, PersonalData

_ARCSEC = 1.0 / 3600.0
_TOLERANCE_DEG = 0.01 * _ARCSEC

_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# (id, birth_date, birth_time, latitude, longitude, timezone_offset_hours).
# Epochs chosen for a LARGE nutation in longitude, both signs, so a frame that
# keeps it in cannot pass by being close.
_CHARTS = [
    ("1936-north", "1936-03-10", "04:15:00", 12.5, 77.5, 5.5),      # about +17.5 arcsec
    ("1954-high-lat", "1954-09-30", "18:20:00", 64.1, -21.9, -1.0),  # about +16.1 arcsec
    ("1982-south", "1982-11-23", "23:10:00", -33.9, 151.2, 10.0),    # about -18.2 arcsec
    ("1990-mid", "1990-06-15", "10:30:00", 12.97, 77.59, 5.5),       # about +12.8 arcsec
    ("2001-equator", "2001-05-05", "00:05:00", 1.3, 103.8, 8.0),     # about -18.2 arcsec
    ("2015-west", "2015-08-04", "07:45:00", 40.7, -74.0, -4.0),      # about +2.3 arcsec
]
_IDS = [c[0] for c in _CHARTS]


def _person(chart) -> dict:
    _id, birth_date, birth_time, lat, lon, tz = chart
    return {
        "name": "sample", "birth_date": birth_date, "birth_time": birth_time,
        "birth_place": "Sample City", "latitude": lat, "longitude": lon,
        "timezone_offset_hours": tz,
    }


def _jd_utc(chart) -> float:
    _id, birth_date, birth_time, _lat, _lon, tz = chart
    y, m, d = (int(x) for x in birth_date.split("-"))
    hh, mm, ss = (int(x) for x in birth_time.split(":"))
    return swe.julday(y, m, d, hh + mm / 60 + ss / 3600 - tz)


def _wrap(delta_deg: float) -> float:
    """Signed difference in (-180, 180]."""
    return (delta_deg + 180.0) % 360.0 - 180.0


def _nutation_in_longitude(jd_utc: float) -> float:
    return swe.calc_ut(jd_utc, swe.ECL_NUT)[0][2]


def _true_obliquity(jd_utc: float) -> float:
    return swe.calc_ut(jd_utc, swe.ECL_NUT)[0][0]


def _mean_lahiri_ayanamsa(jd_utc: float) -> float:
    """The Lahiri ayanamsa WITHOUT nutation, asked of the ephemeris explicitly."""
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    return swe.get_ayanamsa_ex_ut(jd_utc, swe.FLG_SWIEPH | swe.FLG_NONUT)[1]


def _to_sidereal(tropical_true_deg: float, jd_utc: float) -> float:
    return (
        tropical_true_deg - _nutation_in_longitude(jd_utc) - _mean_lahiri_ayanamsa(jd_utc)
    ) % 360.0


def _tropical_house_points(jd_utc: float, lat: float, lon: float, system: bytes):
    """(twelve cusps, ascendant) from the plain house call: true equinox of date."""
    cusps, ascmc = swe.houses(jd_utc, lat, lon, system)
    return list(cusps), ascmc[0]


def _ascendant_by_formula(jd_utc: float, lat: float, lon: float) -> float:
    """The tropical ascendant from first principles.

    With RAMC the right ascension of the meridian (apparent sidereal time plus
    east longitude), eps the true obliquity and phi the latitude:

        tan(asc) = cos(RAMC) / -(sin(RAMC) cos(eps) + tan(phi) sin(eps))
    """
    ramc = math.radians((swe.sidtime(jd_utc) * 15.0 + lon) % 360.0)
    eps = math.radians(_true_obliquity(jd_utc))
    phi = math.radians(lat)
    return math.degrees(math.atan2(
        math.cos(ramc), -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps))
    )) % 360.0


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers={"X-Calc-Service-Token": "test"}) as c:
        yield c


# ---------------------------------------------------------------------------
# The served cusps
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chart", _CHARTS, ids=_IDS)
def test_served_cusps_are_the_tropical_points_less_nutation_and_mean_ayanamsa(client, chart):
    r = client.post("/v1/chart", json=_person(chart))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["house_system"] == "placidus"
    jd = _jd_utc(chart)
    cusps, ascendant = _tropical_house_points(jd, chart[3], chart[4], b"P")
    served = body["bhava_chalit_cusps"]
    assert len(served) == 12
    for i in range(12):
        assert abs(_wrap(served[i] - _to_sidereal(cusps[i], jd))) < _TOLERANCE_DEG, (
            chart[0], i + 1, served[i], _to_sidereal(cusps[i], jd)
        )
    # Cusp 1 is the ascendant, and its sign is the served lagna.
    expected_ascendant = _to_sidereal(ascendant, jd)
    assert abs(_wrap(served[0] - expected_ascendant)) < _TOLERANCE_DEG
    assert body["lagna"] == _SIGNS[int(expected_ascendant // 30)]


@pytest.mark.parametrize("chart", _CHARTS, ids=_IDS)
def test_served_ascendant_matches_the_spherical_formula(client, chart):
    r = client.post("/v1/chart", json=_person(chart))
    assert r.status_code == 200, r.text
    jd = _jd_utc(chart)
    by_hand = _to_sidereal(_ascendant_by_formula(jd, chart[3], chart[4]), jd)
    assert abs(_wrap(r.json()["bhava_chalit_cusps"][0] - by_hand)) < _TOLERANCE_DEG


@pytest.mark.parametrize("chart", _CHARTS, ids=_IDS)
def test_the_nutation_left_in_was_the_whole_error(client, chart):
    """The old construction, rebuilt here from the ephemeris: the tropical ascendant
    minus the mean ayanamsa. It differs from the served value by the nutation in
    longitude, and by nothing else worth an arc-tenth."""
    r = client.post("/v1/chart", json=_person(chart))
    jd = _jd_utc(chart)
    _cusps, ascendant = _tropical_house_points(jd, chart[3], chart[4], b"P")
    nutation_kept = (ascendant - _mean_lahiri_ayanamsa(jd)) % 360.0
    difference = _wrap(nutation_kept - r.json()["bhava_chalit_cusps"][0])
    assert abs(difference - _nutation_in_longitude(jd)) < 0.01 * _ARCSEC
    # Nutation in longitude never exceeds about 19 arcsec.
    assert abs(difference) < 20 * _ARCSEC


# ---------------------------------------------------------------------------
# One frame for the ascendant and the grahas
# ---------------------------------------------------------------------------

_GRAHA_BODY = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN,
}


def _snapshot(chart):
    _id, birth_date, birth_time, lat, lon, tz = chart
    return Chart(PersonalData(
        name="sample",
        birth_date=datetime.datetime.strptime(birth_date, "%Y-%m-%d"),
        birth_time=datetime.time.fromisoformat(birth_time),
        birth_place="Sample City", latitude=lat, longitude=lon,
        timezone_offset_hours=tz,
    )).snapshot()


@pytest.mark.parametrize("chart", _CHARTS, ids=_IDS)
def test_ascendant_and_grahas_share_one_frame(chart):
    """Tropical true-equinox longitude minus served sidereal longitude is ONE
    number for the ascendant and for every graha: the mean ayanamsa plus the
    nutation in longitude."""
    snapshot = _snapshot(chart)
    jd = _jd_utc(chart)
    _cusps, ascendant = _tropical_house_points(jd, chart[3], chart[4], b"P")
    ascendant_offset = _wrap(ascendant - snapshot.chalit_cusps[0])
    frame = _mean_lahiri_ayanamsa(jd) + _nutation_in_longitude(jd)
    assert abs(ascendant_offset - frame) < _TOLERANCE_DEG
    # Geometric (FLG_TRUEPOS) tropical position of date, as the position word
    # asks for, but with the sidereal flag left off.
    tropical_flags = swe.FLG_SWIEPH | swe.FLG_TRUEPOS | swe.FLG_SPEED
    for graha, body in _GRAHA_BODY.items():
        tropical = swe.calc_ut(jd, body, tropical_flags)[0][0]
        graha_offset = _wrap(tropical - snapshot.rasi_chart[graha].longitude_abs)
        assert abs(graha_offset - ascendant_offset) < _TOLERANCE_DEG, (
            chart[0], graha, graha_offset / _ARCSEC, ascendant_offset / _ARCSEC
        )


# ---------------------------------------------------------------------------
# Two births beside a sign boundary -- worked examples
# ---------------------------------------------------------------------------
# Found by stepping one day at one-second resolution with the ephemeris alone.
#
# A. 1936-03-10 16:36:55 at 12.5 N 77.5 E, UTC+5:30. Nutation +17.38 arcsec. The
#    nutation-free ascendant stands 8.9 arcsec short of the end of Cancer; with
#    the nutation left in it reads 8.4 arcsec into Leo.
# B. 1982-11-23 18:04:46 at 33.9 S 151.2 E, UTC+10. Nutation -18.23 arcsec. The
#    nutation-free ascendant stands 10.1 arcsec into Taurus; with the nutation
#    left in it reads 8.2 arcsec short of the end of Aries.
_BOUNDARY = [
    (("A", "1936-03-10", "16:36:55", 12.5, 77.5, 5.5), "Cancer", "Leo"),
    (("B", "1982-11-23", "18:04:46", -33.9, 151.2, 10.0), "Taurus", "Aries"),
]


@pytest.mark.parametrize("chart,lagna,with_nutation", _BOUNDARY, ids=["A", "B"])
def test_a_birth_beside_a_sign_boundary_gets_the_consistent_lagna(
    client, chart, lagna, with_nutation
):
    jd = _jd_utc(chart)
    _cusps, ascendant = _tropical_house_points(jd, chart[3], chart[4], b"P")
    consistent = _to_sidereal(ascendant, jd)
    nutation_kept = (ascendant - _mean_lahiri_ayanamsa(jd)) % 360.0
    # The premise, re-measured: the two frames name different signs, each by a
    # margin of whole arcseconds.
    assert _SIGNS[int(consistent // 30)] == lagna
    assert _SIGNS[int(nutation_kept // 30)] == with_nutation
    for value in (consistent, nutation_kept):
        to_boundary = min(value % 30, 30 - value % 30)
        assert 5 * _ARCSEC < to_boundary < 15 * _ARCSEC

    r = client.post("/v1/chart", json=_person(chart))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lagna"] == lagna
    # Whole-sign houses are counted from that lagna ...
    first = _SIGNS.index(lagna)
    for placement in body["rasi"]:
        assert placement["house"] == (_SIGNS.index(placement["sign"]) - first) % 12 + 1
    # ... and the navamsa lagna is the navamsa of the same ascendant: the ninth
    # parts run on from Aries without a break (BPHS 6.12), so the navamsa sign
    # of a longitude is its count of 3 deg 20 min parts, modulo twelve.
    navamsa_lagna = int(consistent // (30.0 / 9.0)) % 12
    for placement in body["navamsa"]:
        assert placement["house"] == (
            (_SIGNS.index(placement["sign"]) - navamsa_lagna) % 12 + 1
        )


# ---------------------------------------------------------------------------
# The fallback, a new thread, and the declared word
# ---------------------------------------------------------------------------

def test_the_polar_fallback_is_in_the_same_frame(client):
    chart = ("polar", "1990-06-15", "10:30:00", 70.0, 18.96, 1.0)
    r = client.post("/v1/chart", json=_person(chart))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["house_system"] == "equatorial"
    jd = _jd_utc(chart)
    cusps, ascendant = _tropical_house_points(jd, 70.0, 18.96, b"E")
    served = body["bhava_chalit_cusps"]
    assert abs(_wrap(served[0] - _to_sidereal(ascendant, jd))) < _TOLERANCE_DEG
    for i in range(12):
        assert abs(_wrap(served[i] - _to_sidereal(cusps[i], jd))) < _TOLERANCE_DEG


def test_a_thread_that_never_computed_gets_the_lahiri_frame():
    """The sidereal mode is per-thread state. A thread left on the library
    default would answer in another ayanamsa, most of a degree away."""
    chart = _CHARTS[0]
    jd = _jd_utc(chart)
    _cusps, ascendant = _tropical_house_points(jd, chart[3], chart[4], b"P")
    expected = _to_sidereal(ascendant, jd)
    result: dict = {}

    def work():
        try:
            result["ascmc"] = utils.sidereal_houses(jd, chart[3], chart[4], b"P")[1]
        except BaseException as exc:  # noqa: BLE001 - reported on the main thread
            result["error"] = exc

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert "error" not in result, result.get("error")
    assert abs(_wrap(result["ascmc"][0] - expected)) < _TOLERANCE_DEG


def test_the_lahiri_frame_is_reasserted_on_every_house_call():
    """Not only applied once per thread: a thread whose sidereal mode was moved
    after it first computed (the library's own close/reset calls do that) still
    answers in the Lahiri frame, because the house call re-asserts the mode."""
    chart = _CHARTS[0]
    jd = _jd_utc(chart)
    _cusps, ascendant = _tropical_house_points(jd, chart[3], chart[4], b"P")
    expected = _to_sidereal(ascendant, jd)
    result: dict = {}

    def work():
        try:
            utils.sidereal_houses(jd, chart[3], chart[4], b"P")  # thread initialised
            swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)             # ... then knocked over
            result["moved"] = swe.houses_ex(jd, chart[3], chart[4], b"P", swe.FLG_SIDEREAL)[1][0]
            result["served"] = utils.sidereal_houses(jd, chart[3], chart[4], b"P")[1][0]
        except BaseException as exc:  # noqa: BLE001 - reported on the main thread
            result["error"] = exc

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert "error" not in result, result.get("error")
    # The premise: on the other ayanamsa the answer is most of a degree away.
    assert abs(_wrap(result["moved"] - expected)) > 0.5
    assert abs(_wrap(result["served"] - expected)) < _TOLERANCE_DEG


def test_the_house_frame_word_is_declared_and_is_what_a_chart_passes(monkeypatch):
    """The sidereal flag and nothing else: FLG_NONUT here would compute the
    houses from the MEAN obliquity and sidereal time, a different horizon."""
    assert utils.HOUSE_FLAGS == swe.FLG_SIDEREAL
    assert not utils.HOUSE_FLAGS & swe.FLG_NONUT
    assert utils.HOUSE_FLAGS & utils.POSITION_FLAGS == swe.FLG_SIDEREAL
    passed: list[int] = []
    real = swe.houses_ex

    def recording(jd, lat, lon, system, flags):
        passed.append(flags)
        return real(jd, lat, lon, system, flags)

    monkeypatch.setattr(swe, "houses_ex", recording)
    _snapshot(_CHARTS[0])
    assert passed == [utils.HOUSE_FLAGS]
