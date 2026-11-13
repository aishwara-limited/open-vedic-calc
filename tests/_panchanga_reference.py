"""Independent panchanga reference for the electional-scan tests.

Everything here is computed from the classical definitions and the ephemeris
DIRECTLY (``swe.calc_ut`` / ``swe.rise_trans``), never through ``bphs_core``'s
own panchanga helpers, so a test that compares the engine against these values
is comparing it against an outside statement of the rule rather than against
itself.

The definitions (Surya Siddhanta, ch. II "Spashtadhikara", vv. 64-69, Burgess
translation 1860; the same definitions every printed panchanga uses):

* tithi   -- the Moon-Sun elongation in 12-degree parts; 30 per lunar month.
* karana  -- the elongation in 6-degree parts (half a tithi); 60 per month.
  The first half of Shukla Prathama is the fixed Kimstughna; the seven movable
  karanas Bava .. Vishti then repeat eight times (karanas 2-57); the last three
  halves are the fixed Shakuni, Chatushpada and Naga.
* yoga    -- the SUM of the sidereal longitudes of Sun and Moon in parts of
  13 deg 20 min (800 arc-minutes); 27 yogas.
* vaara   -- the weekday runs from sunrise to the next sunrise (the panchanga
  convention, "udayad udayam vaarah"); the first kala-hora of a vaara belongs
  to its lord and the following ones descend in the Chaldean order Saturn,
  Jupiter, Mars, Sun, Venus, Mercury, Moon.

The NAME spellings below follow the engine's transliteration (they are the
served strings), but the tables are typed out here from the classical
sequence rather than imported, so a reorder in the engine reds the tests.
"""
from __future__ import annotations

import datetime as dt
import functools

import swisseph as swe

from bphs_core import utils

TITHI_NAMES_30 = [
    "Shukla Prathama", "Shukla Dwitiya", "Shukla Tritiya", "Shukla Chaturthi",
    "Shukla Panchami", "Shukla Shashthi", "Shukla Saptami", "Shukla Ashtami",
    "Shukla Navami", "Shukla Dashami", "Shukla Ekadashi", "Shukla Dwadashi",
    "Shukla Trayodashi", "Shukla Chaturdashi", "Shukla Purnima",
    "Krishna Prathama", "Krishna Dwitiya", "Krishna Tritiya", "Krishna Chaturthi",
    "Krishna Panchami", "Krishna Shashthi", "Krishna Saptami", "Krishna Ashtami",
    "Krishna Navami", "Krishna Dashami", "Krishna Ekadashi", "Krishna Dwadashi",
    "Krishna Trayodashi", "Krishna Chaturdashi", "Krishna Amavasya",
]

_MOVABLE_KARANAS = ["Bava", "Balava", "Kaulava", "Taitila", "Gara", "Vanija", "Vishti"]
KARANA_NAMES_60 = (
    ["Kimstughna"] + _MOVABLE_KARANAS * 8 + ["Shakuni", "Chatushpada", "Naga"]
)

YOGA_NAMES_27 = [
    "Vishkumbha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda",
    "Sukarma", "Dhriti", "Shula", "Ganda", "Vridhi", "Dhruva", "Vyaghata",
    "Harshana", "Vajra", "Siddhi", "Vyatipata", "Variyan", "Parigha",
    "Shiva", "Siddha", "Sadhya", "Shubha", "Shukla", "Brahma", "Indra",
    "Vaidhriti",
]

NAKSHATRA_SPAN = 360.0 / 27.0

CHALDEAN = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]
WEEKDAY_LORDS = {  # Python weekday(): Monday == 0
    0: "Moon", 1: "Mars", 2: "Mercury", 3: "Jupiter", 4: "Venus",
    5: "Saturn", 6: "Sun",
}

# Within this many degrees of a bucket edge a comparison is skipped: the engine
# reads geometric (FLG_TRUEPOS) positions and this reference reads the library
# default, a convention gap of about 75 arc-seconds for the Moon. 0.05 degrees
# of elongation is about six minutes of time -- an order of magnitude wider than
# that gap and two orders narrower than the shortest limb.
EDGE_MARGIN_DEG = 0.05


def _ensure_state() -> None:
    # The ephemeris path and sidereal mode are THREAD-local in pyswisseph; a
    # decorated engine call applies the path for this thread before we read.
    utils.probe_ephemeris_source()
    swe.set_sid_mode(swe.SIDM_LAHIRI)


def _tropical(jd_ut: float, body: int) -> float:
    return swe.calc_ut(jd_ut, body)[0][0]


def elongation(jd_ut: float) -> float:
    _ensure_state()
    return (_tropical(jd_ut, swe.MOON) - _tropical(jd_ut, swe.SUN)) % 360.0


def sidereal_sum(jd_ut: float) -> float:
    _ensure_state()
    ayanamsa = swe.get_ayanamsa_ut(jd_ut)
    return (
        _tropical(jd_ut, swe.MOON) + _tropical(jd_ut, swe.SUN) - 2.0 * ayanamsa
    ) % 360.0


def _near_edge(value: float, span: float) -> bool:
    r = value % span
    return min(r, span - r) < EDGE_MARGIN_DEG


def tithi_at(jd_ut: float) -> str | None:
    """Tithi name at the instant, or None within EDGE_MARGIN_DEG of a change."""
    e = elongation(jd_ut)
    if _near_edge(e, 12.0):
        return None
    return TITHI_NAMES_30[int(e // 12.0)]


def karana_at(jd_ut: float) -> str | None:
    e = elongation(jd_ut)
    if _near_edge(e, 6.0):
        return None
    return KARANA_NAMES_60[int(e // 6.0)]


def yoga_at(jd_ut: float) -> str | None:
    s = sidereal_sum(jd_ut)
    if _near_edge(s, NAKSHATRA_SPAN):
        return None
    return YOGA_NAMES_27[int(s // NAKSHATRA_SPAN)]


def _sidereal_moon(jd_ut: float) -> float:
    _ensure_state()
    return (_tropical(jd_ut, swe.MOON) - swe.get_ayanamsa_ut(jd_ut)) % 360.0


def nakshatra_index(jd_ut: float) -> int:
    """0-based nakshatra of the Moon at the instant (no edge margin)."""
    return int(_sidereal_moon(jd_ut) // NAKSHATRA_SPAN)


def nakshatra_at(jd_ut: float) -> str | None:
    moon = _sidereal_moon(jd_ut)
    if _near_edge(moon, NAKSHATRA_SPAN):
        return None
    return utils.NAKSHATRAS[int(moon // NAKSHATRA_SPAN)]


def local_jd_ut(day: dt.date, minutes: float, tz: float) -> float:
    """UT Julian Day of local wall-clock *minutes* after midnight of *day*."""
    return swe.julday(day.year, day.month, day.day, minutes / 60.0 - tz)


def local_from_jd_ut(jd_ut: float, tz: float) -> tuple[dt.date, float]:
    """(local civil date, minutes after its local midnight) of a UT JD."""
    y, m, d, h = swe.revjul(jd_ut + tz / 24.0)
    minutes = h * 60.0
    day = dt.date(y, m, d)
    if minutes >= 1440.0 - 1e-6:  # a float hour of 24.0 is next midnight
        return day + dt.timedelta(days=1), 0.0
    return day, minutes


@functools.lru_cache(maxsize=None)
def sunrise_minutes(day: dt.date, lat: float, lon: float, tz: float) -> float:
    """Local sunrise of *day* in minutes after its local midnight.

    Hindu rising (centre of the disc on the true horizon, no refraction) --
    the convention the engine's panchanga is built on -- read straight from
    ``swe.rise_trans``.
    """
    _ensure_state()
    start = local_jd_ut(day, 0.0, tz)
    _, tret = swe.rise_trans(
        start, swe.SUN, swe.CALC_RISE | swe.BIT_HINDU_RISING, (lon, lat, 0.0),
    )
    return (tret[0] - start) * 1440.0


def vedic_day(day: dt.date, minutes: float, lat: float, lon: float,
              tz: float) -> tuple[dt.date, float]:
    """The vaara an instant belongs to, and the minutes since its sunrise.

    An instant before the civil date's sunrise still belongs to the vaara that
    began at the PREVIOUS sunrise.
    """
    rise = sunrise_minutes(day, lat, lon, tz)
    if minutes >= rise:
        return day, minutes - rise
    prev = day - dt.timedelta(days=1)
    return prev, minutes + 1440.0 - sunrise_minutes(prev, lat, lon, tz)


def hora_lord_at(day: dt.date, minutes: float, lat: float, lon: float,
                 tz: float) -> tuple[str, float]:
    """(kala-hora lord, minutes to the nearest hora boundary) at an instant.

    Equal sixty-minute horas counted from the vaara's sunrise, the 24th hora
    running on to the next sunrise.
    """
    vaara, elapsed = vedic_day(day, minutes, lat, lon, tz)
    n = min(int(elapsed // 60), 23)
    r = elapsed % 60.0
    lord = WEEKDAY_LORDS[vaara.weekday()]
    return CHALDEAN[(CHALDEAN.index(lord) + n) % 7], min(r, 60.0 - r)
