import logging
from contextlib import contextmanager
from datetime import date as date_type
from typing import NamedTuple

import swisseph as swe
from jhora.panchanga import drik

from . import utils

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-limb failure modes
#
# Project decision, 2026-08-17: a limb failure that can change WHICH time is
# recommended must RAISE (fail loud); only genuinely supplementary limbs may
# degrade, and then only behind an EXPLICIT per-limb flag.
#
# Before that decision every limb here failed the same way — a log line plus a
# default, a dropped window, or a None — so a day assembled from a broken frame
# was indistinguishable on the wire from a day assembled from a good one. The
# split below is drawn from what the scan pipeline actually reads
# (bphs_core/lagna_shuddhi.py), not from how central a limb sounds:
#
#   * ``_candidate_minutes`` builds the ENTIRE candidate-minute set for a day
#     from ``auspicious_muhurtas`` + the favourable ``chogadiya`` windows. A
#     dropped window there does not make the engine cautious; it deletes
#     candidate minutes, so the recommended minute moves.
#   * ``_score_instant`` hard-excludes on the Rahu/Yamaganda/Gulika windows and,
#     per activity, on Durmuhurtam/Varjyam, the Vishti karana, the eclipse flag
#     and the adhika-maasa flag. A dropped window or an unverifiable flag there
#     silently DELETES a classical veto (or, for the ``None`` vetoes, silently
#     deletes whole candidate days).
#   * It derives the hora lord and the vaara from the served ``sunrise`` and
#     ``date``, so a fabricated day frame moves every hora.
#   * It does NOT read this day's tithi, karana or yoga NAMES: those are
#     evaluated at each candidate instant (``panchanga_at_instant``), because a
#     limb changes at any time of day and the day panchanga served here is the
#     one prevailing at sunrise. The tithi and karana NAMES still raise — they
#     are the served day panchanga, and a wrong one is not a degraded display
#     but a wrong answer.
#
# Limbs with ZERO reads anywhere in that pipeline — moonrise, moonset, the four
# panchanga end-times, the amrita windows, the 30-muhurta display table and the
# personal-balam strings — are the ones that may degrade. They still degrade
# VISIBLY: the served field falls back to its documented sentinel and the limb
# names itself in ``degraded_limbs``, from which the summary ``degraded`` flag
# is derived, so the flag and the list cannot disagree.
#
# Contract: tests/test_muhurat_limb_failure_modes.py. It discovers the ``drik``
# entry points by parsing this module and fails on any limb that carries no
# recorded classification, so a limb added later cannot ship silent.
# ---------------------------------------------------------------------------

class MuhurtaLimbError(RuntimeError):
    """A limb that decides WHICH time can be recommended could not be computed.

    Carries the limb name so a caller (and a log line) can say what failed
    rather than reporting a generic computation error. The originating
    exception is preserved as ``__cause__``.
    """

    def __init__(self, limb: str, target_date: date_type, hint: str = "") -> None:
        self.limb = limb
        self.target_date = target_date
        self.hint = hint
        message = (
            f"muhurat limb {limb!r} could not be computed for "
            f"{target_date.strftime('%Y-%m-%d')}"
        )
        if hint:
            message = f"{message}: {hint}"
        super().__init__(message)


@contextmanager
def _require(limb: str, target_date: date_type, event: str, hint: str = ""):
    """Guard a recommendation-affecting limb: any failure becomes a raise.

    The broad ``except`` covering both the library call and the parse of its
    result is deliberate here and does NOT conflict with the try/except/else
    rule that governs the degrading limbs: that rule exists so a contract break
    cannot be SWALLOWED, and nothing is swallowed on a path that re-raises. What
    the wrapper adds is the limb name and the diagnosable hint.
    """
    try:
        yield
    except MuhurtaLimbError:
        raise
    except Exception as exc:
        logger.error(event, exc_info=True)
        raise MuhurtaLimbError(limb, target_date, hint) from exc


@contextmanager
def _degradable(field: str, degraded_limbs: list[str], event: str):
    """Guard a supplementary limb: a failure degrades, naming itself.

    The caller assigns the fallback value BEFORE the block, so the served
    sentinel is visible at the site rather than hidden in a handler.
    """
    try:
        yield
    except MuhurtaLimbError:
        # A recommendation-affecting failure must never be absorbed by a
        # supplementary guard on its way out.
        raise
    except Exception:
        logger.warning(event, exc_info=True)
        if field not in degraded_limbs:
            degraded_limbs.append(field)


# One full wrap of the local day. Rise/set events legitimately land after local
# midnight (a night-side event on the target date), so the bound is 48h, not 24h.
#
# Measured 2026-08-17 against the real Swiss data files: over 5980 rise/set
# samples (latitude -66..66 in steps of 6, five longitudes, thirteen dates,
# sunrise/sunset/moonrise/moonset) the float-hour element ran min 0.0033 h,
# max 26.0241 h and NONE fell outside [0, 48). Over 600 polar samples
# (|latitude| 67..89, three longitudes, ten dates, sunrise/sunset) 228 were real
# events inside the bound and the other 372 were all large negative sentinels in
# [-59073516.0, -59064996.0].
_EVENT_HOURS_LIMIT = 48.0


def _event_hours(raw: object) -> float:
    """The float-hour element of a ``drik`` rise/set result, validated.

    This is the check the ``except`` handlers could never make, because at a
    latitude where a body neither rises nor sets ``drik.sunrise``/``sunset``/
    ``moonrise``/``moonset`` do NOT raise — they return a large negative
    sentinel. ``float_hours_to_hhmm`` reduces that modulo 24, so the sentinel
    renders as a perfectly plausible wall-clock string.

    Measured 2026-08-17 on the unguarded code, latitude 78.0 / 2026-06-21:
    ``drik.sunrise`` returned ``-59069099.0`` and the day was served as
    ``sunrise`` "13:00", ``sunset`` "13:00", ``degraded`` False,
    ``hard_gate_failed`` False, with 30 muhurtas, 16 chogadiya windows and
    three ZERO-WIDTH absolute-veto windows — a complete, clean-looking
    recommendation resting on a day frame that does not exist.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"rise/set event hour is not a number: {raw!r}")
    hours = float(raw)
    if not 0.0 <= hours < _EVENT_HOURS_LIMIT:
        raise ValueError(
            f"rise/set event hour {hours!r} lies outside [0, {_EVENT_HOURS_LIMIT}): "
            f"this is the library's no-rise/no-set sentinel — the body neither "
            f"rises nor sets at this latitude on this date (polar day/night)"
        )
    return hours


# The internal (never served) key under which compute_muhurat_for_day hands the
# electional scan the Varjyam window's float hours from local midnight. Every
# other window the scan reads has a placement fixed by its definition (see
# lagna_shuddhi._place_day_windows); Varjyam's is not, because it is a slice of
# a nakshatra rather than of the day.
VARJYAM_HOURS_KEY = "_varjyam_hours"

# Named on the day-frame errors so a polar request is diagnosable from the
# message alone rather than from a stack trace.
_DAY_FRAME_HINT = (
    "the day frame could not be established — the Sun may neither rise nor set "
    "at this latitude on this date (polar day/night). Every panchanga limb and "
    "every candidate window is measured from sunrise/sunset, so no time can be "
    "recommended without it"
)

TITHIS = [
    "Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shashthi",
    "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi",
    "Trayodashi", "Chaturdashi", "Purnima",
    "Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shashthi",
    "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi",
    "Trayodashi", "Chaturdashi", "Amavasya"
]

YOGAS = [
    "Vishkumbha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda",
    "Sukarma", "Dhriti", "Shula", "Ganda", "Vridhi", "Dhruva", "Vyaghata",
    "Harshana", "Vajra", "Siddhi", "Vyatipata", "Variyan", "Parigha",
    "Shiva", "Siddha", "Sadhya", "Shubha", "Shukla", "Brahma", "Indra", "Vaidhriti"
]

KARANAS = [
    "Bava", "Balava", "Kaulava", "Taitila", "Gara", "Vanija", "Vishti"
]

FIXED_KARANAS = {
    1: "Kimstughna",
    58: "Shakuni",
    59: "Chatushpada",
    60: "Naga"
}

_TARA_BALA_LEVELS = {
    1: ("Janma", "Not Good"),
    2: ("Sampat", "Very Good"),
    3: ("Vipat", "Bad"),
    4: ("Kshema", "Good"),
    5: ("Pratyak", "Not Good"),
    6: ("Sadhana", "Very Good"),
    7: ("Naidhana", "Totally Bad"),
    8: ("Mitra", "Good"),
    0: ("Paramitra", "Good"),
}

_CHOGHADIYA_TYPES = {
    0: "Udveg (Inauspicious)",
    1: "Chara (Auspicious)",
    2: "Labh (Auspicious)",
    3: "Amrit (Highly Auspicious)",
    4: "Kaal (Inauspicious)",
    5: "Shubh (Auspicious)",
    6: "Rog (Inauspicious)",
}

# The 30 standard Muhurtas of the day/night
_MUHURTA_NAMES = [
    "Rudra", "Ahi", "Mitra", "Pitri", "Vasu", "Vara", "Vishwadeva", "Vidhi",
    "Sathamukhi", "Puruhuta", "Vahni", "Naktanchara", "Varuna", "Aryaman", "Bhaga",
    "Girish", "Ajapad", "Ahirbudhnya", "Pusa", "Ashwini", "Yama", "Agni", "Vidhatri",
    "Chanda", "Aditi", "Jiva", "Visnu", "Dyumani", "Brahma", "Samudra"
]


# The contracted shape of one ``drik.muhurthas`` entry. Element 1 is the
# library's own auspicious flag (0 = inauspicious, 1 = auspicious); it is
# validated but not currently served — ``TimeWindow`` (app/schemas.py) carries
# no such field, and adding one is a wire-contract change, not a parse fix.
_MUHURTHA_ENTRY_SHAPE = "(name, auspicious_flag, (start_hours, end_hours))"


def _muhurtha_bounds(entry: object) -> tuple[float, float]:
    """The ``(start_hours, end_hours)`` pair of one ``drik.muhurthas`` entry.

    Boundaries are float hours from midnight of the local date and legitimately
    exceed 24 for the night muhurtas that fall after it; the caller renders them
    through :func:`float_hours_to_hhmm`, which wraps to wall clock as it does for
    every other window in this module.

    Raises TypeError on anything that does not match the contracted shape. This
    is deliberate: a muhurta table that cannot be read must not be served as an
    empty one, because an empty list is indistinguishable from a real result.
    """
    if (
        not isinstance(entry, tuple)
        or len(entry) != 3
        or not isinstance(entry[0], str)
        or not isinstance(entry[1], int)
        or not isinstance(entry[2], tuple)
        or len(entry[2]) != 2
        or not all(isinstance(b, float) for b in entry[2])
    ):
        raise TypeError(
            f"muhurtha entry does not match the contracted shape "
            f"{_MUHURTHA_ENTRY_SHAPE}: {entry!r}"
        )
    return entry[2]


def float_hours_to_hhmm(fh: float) -> str:
    """Render float hours as ``HH:MM`` on a 24h wall clock — the ONE clock this
    module serves.

    The minute shown is the minute the instant FALLS IN: the residual is rounded
    to whole seconds and the minute is then truncated. This is *exactly* what
    pyjhora's own ``utils.to_dms`` produces (its ``HH:MM:SS`` string sliced to
    ``[:5]``) for every event/period it renders as a string — sunrise, sunset,
    moonrise, moonset, chogadiya, rahu-kala, yamagandam, gulika, abhijit,
    durmuhurtam. Sharing that single convention is what guarantees a period
    BOUNDARY renders identically to the EVENT it is derived from: the 30-muhurta
    night division opens at ``sunset_hours`` and the served ``sunset`` field is
    that same instant, so both must — and now do — read the same HH:MM.

    Register #176: an 18:17:58 sunset used to serve as ``sunset`` "18:17" but
    open its night muhurta at "18:18", because this helper rounded to the nearest
    minute while ``to_dms`` truncates. The underlying float — the BPHS-accurate
    value — is untouched by either convention; only the minute LABEL differs, and
    it is aligned here to the library-native, engine-wide truncation so two
    renderings of one instant cannot disagree. The ``to_dms`` equivalence is
    pinned by tests/test_muhurat_deep.py so the drik-string ``[:5]`` sites and
    this helper can never drift apart. Values >= 24h (night muhurtas after
    midnight) wrap to wall clock, as before.
    """
    fh = fh % 24
    h = int(fh)
    mins = (fh - h) * 60
    mnt = int(mins)                          # the minute the instant falls in
    if round((mins - mnt) * 60) == 60:       # ...but a >= 59.5s residual rounds
        mnt += 1                             #    up a second and carries the
    if mnt == 60:                            #    minute, matching to_dms exactly
        h += 1
        mnt = 0
    return f"{h % 24:02d}:{mnt:02d}"


def get_tithi_name(idx: int) -> str:
    # The lunar phase index ``idx`` runs 1..30. _get_tithi computes
    # ceil(moon_phase / 12), so idx == 30 IS produced at exact new moon and must
    # name Amavasya (TITHIS[29]); the Krishna-half lookup ``TITHIS[idx - 16]``
    # only covers idx 16..29 (Prathama..Chaturdashi), so 30 is special-cased.
    if idx == 30:
        return "Krishna Amavasya"
    if idx <= 15:
        phase = "Shukla"
        name = TITHIS[idx - 1]
    else:
        phase = "Krishna"
        name = TITHIS[idx - 16]
    return f"{phase} {name}"


def get_karana_name(idx: int) -> str:
    if idx in FIXED_KARANAS:
        return FIXED_KARANAS[idx]
    return KARANAS[(idx - 2) % 7]


# 360°/27 = 13°20': the span of one nakshatra (and of one yoga, which buckets
# the Sun+Moon longitude sum on the same 27-fold division).
_NAK_SPAN = 360.0 / 27.0


def _nakshatra_from_moon(jd: float) -> tuple[str, int]:
    """Nakshatra of the Moon at *jd*, computed DIRECTLY from its sidereal
    longitude (13°20' buckets) rather than via the pyjhora index lookup.

    Returns ``(name, index_1_based)``. A valid name is ALWAYS produced — this
    is a deterministic function of the Moon's longitude, so it bypasses the
    pyjhora bug where an out-of-range index would otherwise wrap to a wrong
    entry. (Same precedent as chart.py computing the ascendant directly via
    swisseph. Matches utils.longitude_to_nakshatra.)
    """
    idx = int((utils.graha_sidereal_longitude(jd, "Moon") % 360) / _NAK_SPAN) % 27
    return utils.NAKSHATRAS[idx], idx + 1


def _yoga_from_sun_moon(jd: float) -> tuple[str, int]:
    """Yoga at *jd*, computed DIRECTLY from the sum of the Sun and Moon sidereal
    longitudes (13°20' buckets) rather than via the pyjhora index lookup.

    Returns ``(name, index_1_based)``.
    """
    total = (utils.graha_sidereal_longitude(jd, "Sun")
             + utils.graha_sidereal_longitude(jd, "Moon")) % 360
    idx = int(total / _NAK_SPAN) % 27
    return YOGAS[idx], idx + 1


class InstantPanchanga(NamedTuple):
    """The three Sun-Moon panchanga limbs prevailing at one instant."""
    tithi: str
    karana: str
    yoga: str


def panchanga_from_longitudes(sun_sid: float, moon_sid: float) -> InstantPanchanga:
    """Tithi, karana and yoga for the sidereal longitudes of the Sun and Moon.

    The classical definitions (Surya Siddhanta, ch. II "Spashtadhikara",
    vv. 64-69, Burgess translation 1860), which every printed panchanga
    applies:

    * tithi  -- the Moon-Sun elongation in parts of 12 degrees (720 arc-minutes);
      30 to the lunar month, named here by ``get_tithi_name``.
    * karana -- the elongation in parts of 6 degrees, half a tithi; 60 to the
      month: the fixed Kimstughna, the seven movable karanas Bava .. Vishti
      eight times over, then the fixed Shakuni, Chatushpada and Naga
      (``get_karana_name``).
    * yoga   -- the SUM of the two sidereal longitudes in parts of 13 deg 20 min
      (800 arc-minutes); 27 yogas.

    The elongation is a difference, so the ayanamsa cancels from it; the yoga
    is a sum, so it must be taken over sidereal longitudes. The ``% 30`` and
    ``% 60`` matter: a Moon a hair behind the Sun gives a float elongation that
    ``% 360`` rounds to exactly 360.0, which is the FIRST part of the cycle
    (new moon), not a 31st tithi or a 61st karana. A sum of two longitudes in
    [0, 360) is never negative, so the yoga needs no such guard.
    """
    elongation = (moon_sid - sun_sid) % 360.0
    tithi_idx = int(elongation // 12.0) % 30 + 1
    karana_idx = int(elongation // 6.0) % 60 + 1
    yoga_idx = int(((sun_sid + moon_sid) % 360.0) // _NAK_SPAN)
    return InstantPanchanga(
        get_tithi_name(tithi_idx), get_karana_name(karana_idx), YOGAS[yoga_idx],
    )


@utils.serialized_ephemeris
def panchanga_at_instant(jd_utc: float) -> InstantPanchanga:
    """The tithi, karana and yoga prevailing at the UTC Julian Day *jd_utc*.

    The electional scan evaluates these at EVERY candidate instant rather than
    reading the day's names: a karana lasts about half a day and a tithi or
    yoga about one, so a day-level name is wrong for part of every day on which
    the limb changes -- which is most days. Measured on the code before this
    change, at Colombo over 2026-12: a Vishti karana beginning at 13:30 was not
    vetoed for marriage that evening, and a day whose noon karana was Vishti
    was vetoed from midnight on although its Vishti ended at 15:20.

    No exception guard: a Sun or Moon longitude that cannot be computed at a
    valid instant means the ephemeris layer itself is broken, and the failure
    must surface (the same rule as the lagna-lord limb in the scorer). Both
    reads are taken under one hold of the ephemeris lock.
    """
    return panchanga_from_longitudes(
        utils.graha_sidereal_longitude(jd_utc, "Sun"),
        utils.graha_sidereal_longitude(jd_utc, "Moon"),
    )


def _is_eclipse_day(target_date: date_type, place: drik.Place) -> bool:
    """True if a solar OR lunar eclipse is VISIBLE at *place* on this local day.

    An eclipse not visible at the location carries no grahana dosha, so the
    location-aware drik.next_*_eclipse finders are used — they skip eclipses not
    seen from `place` (verified: India sees 2026-03-03 lunar & 2027-08-02 solar,
    but not the 2026-02-17 / 2026-08-12 solar eclipses). The next-eclipse JD is
    in ``tret[0]``; we accept it when it falls inside this local calendar day.

    RAISES on a finder failure (project decision 2026-08-17). This used to
    return None for 'eclipse status could not be computed', and the scan then
    read that None as a veto (`is_eclipse_day in (True, None)`) — so an
    unverifiable finder silently DELETED candidate days from the recommendation
    while the response stayed well formed. An eclipse veto that cannot be
    verified is a failure, not a result.

    SEARCHES OUTSIDE THE SCANNED DAY, AND RESTORES THE ENGINE AFTERWARDS.
    Answering "is there an eclipse today" means finding the NEXT eclipse, which
    is almost never today: measured from a day scanned at 2400-01-09, the lunar
    finder returns 2400-01-12 and the solar 2403-05-21, both past the end of the
    shipped files (~2400-01-10). Two consequences, and they are different:

    * The VERDICT is unaffected — it is a coarse `day_start <= t_max < day_end`
      comparison, and the two engines agree far too closely to move an eclipse
      across a local midnight (measured: worst drift 2.714 s against a closest
      approach of 185 s, a 68x margin, 0 disagreements over 132 days).
    * The ENGINE STATE was affected, and that was a real defect. swisseph keeps
      the fallback after an out-of-range read, so the scanned day's OWN Sun and
      Moon — well inside the files — then answered from Moshier with nothing
      saying so. ``utils.restore_ephemeris_state()`` in the ``finally`` is what
      closes that; it must cover the ``return True`` and the raising paths too,
      which is why it is a ``try``/``finally`` and not a trailing call.

    Both are pinned by tests/test_muhurat_edge_probe_engine.py.
    """
    tz = place.timezone
    day_start = swe.julday(
        target_date.year, target_date.month, target_date.day, 0.0 - tz
    )
    day_end = day_start + 1.0
    try:
        for finder in (drik.next_solar_eclipse, drik.next_lunar_eclipse):
            with _require(
                "eclipse", target_date, "muhurat_eclipse_check_failed",
                "the grahana (eclipse) veto could not be verified for this day",
            ):
                res = finder(day_start - 2.0, place)
                t_max = res[1][0]
                guard = 0
                # Advance past any eclipse that falls before this day.
                while t_max < day_start and guard < 60:
                    res = finder(t_max + 0.05, place)
                    t_max = res[1][0]
                    guard += 1
                if day_start <= t_max < day_end:
                    return True
        return False
    finally:
        # The searches above deliberately read past the end of the shipped data.
        # Leaving swisseph on the fallback would silently degrade every LATER
        # lookup on this day — and on the next day of a range scan.
        utils.restore_ephemeris_state()


def _is_adhik_maasa(jd: float, place: drik.Place, target_date: date_type) -> bool:
    """True if the lunar month containing *jd* is an Adhika (intercalary) Maasa.

    ``drik.lunar_month`` returns ``[maasa_number, is_leap_month, is_nija_month]``;
    element 1 (``is_leap_month``) is the adhika flag per pyjhora's own docstring —
    an adhika maasa is the amanta month whose bracketing new moons fall in the
    same solar month (no sankranti). The service always runs in LAHIRI ayanamsa
    (set in utils import), under which this is verified against Adhika Shravana
    2023. No auspicious samskara is begun in an Adhika Maasa.

    RAISES on failure, for the same reason as :func:`_is_eclipse_day`: the None
    this used to return is read downstream as a veto, so an unverifiable month
    silently removed candidate days rather than reporting that it failed.
    """
    with _require(
        "adhik_maasa", target_date, "muhurat_adhika_maasa_check_failed",
        "the Adhika Maasa veto could not be verified for this day",
    ):
        return bool(drik.lunar_month(jd, place)[1])


@utils.serialized_ephemeris
def compute_muhurat_for_day(
    place: drik.Place,
    target_date: date_type,
    birth_nakshatra: str | None = None,
    birth_moon_sign: str | None = None
) -> dict:
    # 1. Convert target date to Julian Day.
    #
    # Two separate JDs are needed for correctness:
    #
    # jd      — LOCAL noon as a JD (no timezone subtraction). This is what
    #            pyjhora's sunrise/sunset/tithi/nakshatra-end/karana helpers
    #            expect: they internally subtract Place.timezone to reach UTC.
    #
    # jd_utc  — TRUE UTC noon JD (jd_local - tz/24). This is what
    #            drik.sidereal_longitude() requires — its docstring is explicit:
    #            "JD_UTC = JD - Place.TimeZoneInFloatHours". Calling it with the
    #            local JD introduces a ~tz * 0.55°/hr error (≈3° for IST), enough
    #            to shift the Moon's nakshatra across a 13°20' boundary.
    #
    # Sunrise/sunset must continue using the local jd so pyjhora's internal tz
    # subtraction produces the correct local event times.
    y, m, d = target_date.year, target_date.month, target_date.day
    jd = swe.julday(y, m, d, 12.0)                      # LOCAL noon — for pyjhora event calcs
    jd_utc = swe.julday(y, m, d, 12.0 - place.timezone) # UTC noon   — for drik.sidereal_longitude
    drik.set_ayanamsa_mode('LAHIRI')

    # Limbs that degraded, by served-field name. ``degraded`` is DERIVED from
    # this list at the end, so the summary flag and the per-limb detail cannot
    # disagree — the predecessor tracked only the summary bool, and a consumer
    # seeing degraded=True could not tell what it had lost.
    degraded_limbs: list[str] = []

    # 2. Get Sunrise, Sunset, Moonrise, Moonset.
    #
    # Render the FLOAT hours (drik.*()[0]) through float_hours_to_hhmm — the SAME
    # helper the muhurta/panchanga float boundaries use — rather than slicing
    # drik's own HH:MM:SS string ([1][:5]). Both produce the library's
    # truncate-the-minute clock (byte-identical, pinned in test_muhurat_deep.py),
    # so the value served is unchanged; what changes is that the event and the
    # window derived from it now go through ONE formatter and can never disagree
    # (register #176).
    #
    # Sunrise and sunset RAISE (project decision 2026-08-17): they are the day
    # frame, so a "06:00"/"18:00" stand-in does not degrade the answer, it
    # fabricates one — the chogadiya and muhurta divisions are cut from it and
    # the scan derives every hora lord from the served sunrise string. The
    # moon events are display-only (zero reads in the scan pipeline) and so
    # degrade, naming themselves.
    #
    # _event_hours is what makes the sunrise/sunset raise real: at a polar
    # latitude the library returns a sentinel rather than raising, so the
    # exception handler this replaced was unreachable on exactly the input it
    # was written for.
    with _require("sunrise", target_date, "muhurat_sunrise_failed", _DAY_FRAME_HINT):
        sr_hours = _event_hours(drik.sunrise(jd, place)[0])
        sr = float_hours_to_hhmm(sr_hours)
    with _require("sunset", target_date, "muhurat_sunset_failed", _DAY_FRAME_HINT):
        ss = float_hours_to_hhmm(_event_hours(drik.sunset(jd, place)[0]))

    mr = None
    with _degradable("moonrise", degraded_limbs, "muhurat_moonrise_failed"):
        mr = float_hours_to_hhmm(_event_hours(drik.moonrise(jd, place)[0]))
    ms = None
    with _degradable("moonset", degraded_limbs, "muhurat_moonset_failed"):
        ms = float_hours_to_hhmm(_event_hours(drik.moonset(jd, place)[0]))

    # 3. Panchanga limbs — the panchanga PREVAILING AT SUNRISE.
    #
    # The day's panchanga is the one in force at local sunrise: the udaya-tithi
    # convention every printed panchanga follows, and the start of the vaara
    # (which runs sunrise to sunrise). It used to be evaluated at local NOON —
    # ``jd`` above — which serves a different limb whenever one changes during
    # the morning: measured at Colombo over the 90 days from 2026-10-01, the
    # limb at noon differed from the limb at sunrise on 24 days for the tithi,
    # 23 for the nakshatra, 29 for the yoga and 51 for the karana. Each limb
    # that ends during the day carries its end
    # time; because every call below is made AT sunrise, that end time is the
    # end of the limb actually served, not of the one in force at noon.
    #
    # ``jd_rise`` is a LOCAL-clock JD (pyjhora's transport, which subtracts the
    # timezone itself) and ``jd_rise_utc`` the true UTC one for the direct
    # longitude reads — the same two-JD discipline as ``jd``/``jd_utc`` above.
    jd_rise = swe.julday(y, m, d, sr_hours)
    jd_rise_utc = jd_rise - place.timezone / 24.0
    #
    # The NAME of each single-body limb (nakshatra, yoga) is computed DIRECTLY
    # from the sidereal longitudes (13°20' buckets) — a deterministic, valid name
    # is always produced, bypassing the pyjhora index-lookup bug that could wrap
    # an out-of-range index to a wrong entry (precedent: chart.py computes the
    # ascendant directly via swisseph). The pyjhora calls are kept ONLY for their
    # end-time values.
    #
    # NAME and END TIME are classified SEPARATELY even where one call yields
    # both: the tithi and karana NAMES are the served day panchanga and RAISE,
    # while the four end-times have ZERO reads anywhere in the pipeline and
    # degrade. (The electional scan does not read any of these day names: it
    # evaluates the tithi, karana and yoga at each candidate instant through
    # ``panchanga_at_instant``.)

    # Tithi — NAME from pyjhora at sunrise. It RAISES: a null or wrong tithi is
    # a wrong day panchanga, not a degraded display.
    with _require(
        "tithi", target_date, "muhurat_tithi_failed",
        "the tithi could not be computed (e.g. a ZeroDivisionError at an exact "
        "phase boundary); it is a primary limb of the day panchanga",
    ):
        t_res = drik.tithi(jd_rise, place)
        t_name = get_tithi_name(t_res[0])
    t_end = None
    with _degradable(
        "panchanga.tithi_end", degraded_limbs, "muhurat_tithi_end_unavailable"
    ):
        t_end = float_hours_to_hhmm(t_res[2])

    # Nakshatra: NAME directly from the Moon's longitude at sunrise (always
    # valid); end-time from pyjhora, degradable. The name reads jd_rise_utc so
    # drik.sidereal_longitude gets the true UTC Julian Day (a local JD causes a
    # ~tz * 0.55°/hr error — ~3° for IST).
    n_name, _ = _nakshatra_from_moon(jd_rise_utc)
    n_end = None
    with _degradable(
        "panchanga.nakshatra_end", degraded_limbs, "muhurat_nakshatra_end_unavailable"
    ):
        n_res = drik.nakshatra(jd_rise, place)
        n_idx = n_res[0]
        if not 1 <= n_idx <= len(utils.NAKSHATRAS):
            raise ValueError(f"nakshatra index out of range: {n_idx}")
        n_end = float_hours_to_hhmm(n_res[3])  # index 3 contains the end float hour

    # Yoga: NAME directly from the Sun+Moon longitude sum at sunrise (always
    # valid); end-time from pyjhora, degradable. jd_rise_utc for the same reason
    # as the nakshatra above.
    y_name, _ = _yoga_from_sun_moon(jd_rise_utc)
    y_end = None
    with _degradable(
        "panchanga.yogam_end", degraded_limbs, "muhurat_yoga_end_unavailable"
    ):
        y_res = drik.yogam(jd_rise, place)
        y_idx = y_res[0]
        if not 1 <= y_idx <= len(YOGAS):
            raise ValueError(f"yoga index out of range: {y_idx}")
        y_end = float_hours_to_hhmm(y_res[2])

    # Karana — the sunrise karana. It RAISES, like the tithi: a null karana is a
    # wrong day panchanga, and the karana is the limb that names Bhadra (Vishti)
    # for the caller. The end time degrades. The scan's Bhadra veto does NOT
    # read this name; it reads the karana in force at each candidate instant.
    with _require(
        "karana", target_date, "muhurat_karana_failed",
        "the karana could not be computed; it names Bhadra (Vishti) in the day "
        "panchanga, which cannot be served without it",
    ):
        k_res = drik.karana(jd_rise, place)
        k_name = get_karana_name(k_res[0])
    k_end = None
    with _degradable(
        "panchanga.karana_end", degraded_limbs, "muhurat_karana_end_unavailable"
    ):
        k_end = float_hours_to_hhmm(k_res[2])

    # Derived weekday
    weekday = target_date.strftime("%A")

    panchanga = {
        "tithi": t_name,
        "tithi_end": t_end,
        "nakshatra": n_name,
        "nakshatra_end": n_end,
        "yogam": y_name,
        "yogam_end": y_end,
        "karana": k_name,
        "karana_end": k_end,
        "vaara": weekday
    }

    # 4. Auspicious windows (Abhijit, Brahma, Vijaya, Godhuli, Nishita).
    #
    # These RAISE. They are not decoration: together with the favourable
    # chogadiya windows they ARE the candidate set — lagna_shuddhi's
    # _candidate_minutes scans only the minutes these windows cover. Dropping a
    # failed window quietly removed candidate minutes, so the recommended
    # instant moved to whatever survived; drop them all and the day yields no
    # candidates at all while still serving HTTP 200 with an empty list.
    _AUSPICIOUS_HINT = (
        "an auspicious window failed; these windows define the candidate "
        "minutes a recommendation is chosen from"
    )
    auspicious = []
    with _require("abhijit_muhurta", target_date, "muhurat_abhijit_failed", _AUSPICIOUS_HINT):
        ab = drik.abhijit_muhurta(jd, place)
        auspicious.append({"start": ab[0][:5], "end": ab[1][:5], "label": "Abhijit Muhurta"})

    with _require("brahma_muhurtha", target_date, "muhurat_brahma_failed", _AUSPICIOUS_HINT):
        bm = drik.brahma_muhurtha(jd, place)
        auspicious.append({"start": float_hours_to_hhmm(bm[0]), "end": float_hours_to_hhmm(bm[1]), "label": "Brahma Muhurtha"})

    with _require("vijaya_muhurtha", target_date, "muhurat_vijaya_failed", _AUSPICIOUS_HINT):
        vm = drik.vijaya_muhurtha(jd, place)
        # vm is double tuple: ((day_start, day_end), (night_start, night_end))
        auspicious.append({"start": float_hours_to_hhmm(vm[0][0]), "end": float_hours_to_hhmm(vm[0][1]), "label": "Vijaya Muhurtha (Day)"})
        auspicious.append({"start": float_hours_to_hhmm(vm[1][0]), "end": float_hours_to_hhmm(vm[1][1]), "label": "Vijaya Muhurtha (Night)"})

    with _require("godhuli_muhurtha", target_date, "muhurat_godhuli_failed", _AUSPICIOUS_HINT):
        gm = drik.godhuli_muhurtha(jd, place)
        auspicious.append({"start": float_hours_to_hhmm(gm[0]), "end": float_hours_to_hhmm(gm[1]), "label": "Godhuli Muhurtha"})

    with _require("nishita_muhurtha", target_date, "muhurat_nishita_failed", _AUSPICIOUS_HINT):
        nm = drik.nishita_muhurtha(jd, place)
        auspicious.append({"start": float_hours_to_hhmm(nm[0]), "end": float_hours_to_hhmm(nm[1]), "label": "Nishita Muhurtha"})

    # 5. Chogadiya windows — the other half of the candidate set (the favourable
    # labels are scanned directly) and a scored factor in its own right, so a
    # failure RAISES rather than serving an empty division of the day.
    chogadiya_list = []
    with _require(
        "chogadiya", target_date, "muhurat_chogadiya_failed",
        "the chogadiya division failed; its favourable windows are half the "
        "candidate minutes a recommendation is chosen from",
    ):
        gc = drik.gauri_choghadiya(jd, place)
        for g_type, g_start, g_end in gc:
            label = _CHOGHADIYA_TYPES.get(g_type, "Unknown")
            chogadiya_list.append({"start": g_start[:5], "end": g_end[:5], "label": label})

    # 6. Inauspicious periods (Rahu Kala, Yamagandam, Gulikai, Durmuhurtam, Varjyam).
    #
    # ALL FIVE RAISE. Rahu Kala / Yamaganda / Gulika are ABSOLUTE classical
    # vetoes; Durmuhurtam and Varjyam are per-activity hard vetoes the scorer
    # applies through ``rule.hard_excludes``. Every one of them reaches the
    # scorer as a WINDOW LIST it matches labels against, so a dropped window is
    # not a missing signal the consumer can see — it is a veto that silently
    # does not fire, which recommends an instant the classical rule forbids.
    #
    # The three absolute vetoes previously set ``hard_gate_failed``, a flag that
    # made the whole day unrecommendable. Raising is the same fail-closed
    # intent, stated where it cannot be misread as a computed result.
    _VETO_HINT = (
        "a classical veto window could not be computed; an unverifiable veto "
        "must not be served as an absent one"
    )
    inauspicious = []
    with _require("rahu_kaalam", target_date, "muhurat_rahu_kaalam_failed", _VETO_HINT):
        rk = drik.raahu_kaalam(jd, place)
        inauspicious.append({"start": rk[0][:5], "end": rk[1][:5], "label": "Rahu Kala"})

    with _require("yamaganda_kaalam", target_date, "muhurat_yamaganda_failed", _VETO_HINT):
        yg = drik.yamaganda_kaalam(jd, place)
        inauspicious.append({"start": yg[0][:5], "end": yg[1][:5], "label": "Yamagandam"})

    with _require("gulikai_kaalam", target_date, "muhurat_gulikai_failed", _VETO_HINT):
        gk = drik.gulikai_kaalam(jd, place)
        inauspicious.append({"start": gk[0][:5], "end": gk[1][:5], "label": "Gulika"})

    with _require("durmuhurtam", target_date, "muhurat_durmuhurtam_failed", _VETO_HINT):
        dm = drik.durmuhurtam(jd, place)
        # dm list of strings in pairs
        if len(dm) >= 2:
            inauspicious.append({"start": dm[0][:5], "end": dm[1][:5], "label": "Durmuhurtam Period 1"})
        if len(dm) >= 4:
            inauspicious.append({"start": dm[2][:5], "end": dm[3][:5], "label": "Durmuhurtam Period 2"})

    with _require("varjyam", target_date, "muhurat_varjyam_failed", _VETO_HINT):
        vj = drik.varjyam(jd, place)
        # Float hours from this date's local midnight. Varjyam is a slice of
        # the nakshatra in force at noon, so it can lie on the PREVIOUS evening
        # (negative hours) or after the coming midnight (24 or more) — measured
        # at four cities over 2026, 126 of 292 sampled days started before
        # midnight and 5 after the next one. The served HH:MM cannot say which
        # date it is on, so the unrendered pair is kept for the scan below.
        varjyam_hours = (float(vj[0]), float(vj[1]))
        inauspicious.append({"start": float_hours_to_hhmm(vj[0]), "end": float_hours_to_hhmm(vj[1]), "label": "Varjyam"})

    # 7. Amrita periods — served for display only (zero reads in the scan
    # pipeline: they are neither a veto nor a candidate-window source), so this
    # is one of the limbs that may degrade. It names itself when it does.
    amrita = []
    with _degradable("amrita_periods", degraded_limbs, "muhurat_amrita_failed"):
        ag = drik.amrita_gadiya(jd, place)
        amrita.append({"start": float_hours_to_hhmm(ag[0]), "end": float_hours_to_hhmm(ag[1]), "label": "Amrita Gadiya"})

    # 8. Panchaka free periods.
    #
    # RAISES. This used to stay None for 'panchaka status could not be computed'
    # and rely on the consumer to fail closed on the null — but a veto flag that
    # asks its reader to guess is the same silent-drop shape as an omitted
    # window, and nothing in this service could tell whether the reader did.
    # panchaka_free is now always an answered bool or an error.
    with _require(
        "panchaka", target_date, "muhurat_panchaka_failed",
        "the panchaka-rahita veto could not be computed",
    ):
        pk = drik.panchaka_rahitha(jd, place)
        # pk is list of tuples: (dosha_idx, start_h, end_h)
        # if there are any non-zero doshas spanning noon, we can mark as not panchaka free
        panchaka_free = True
        for dosha, s_h, e_h in pk:
            if s_h <= 12.0 <= e_h and dosha != 0:
                panchaka_free = False
                break

    # 9. Personalized Balam
    personal = None
    if birth_nakshatra and birth_moon_sign:
        # Tara / Chandra Bala keep DEGRADING rather than raising, because
        # 'Unknown' is already a visible degradation downstream: the scorer
        # penalises it exactly as it penalises a classically-bad Tara and caps
        # the band at Fair, so the recommendation cannot silently improve on a
        # failed limb. What they lacked — and now have — is a log line and a
        # named entry in degraded_limbs; before this they were the only limbs in
        # the module that failed with no record at all.
        #
        # 'Unknown' (NOT 'Neutral') uniformly means 'could not be computed',
        # matching compute_balam_at_jd.

        # Tara Bala — the transit star comes from the DIRECT Moon-longitude
        # computation (1-based index), never the pyjhora index that may be
        # corrupt.
        tara_str = "Unknown"
        with _degradable(
            "personal_balam.tara_bala", degraded_limbs, "muhurat_tara_bala_unavailable"
        ):
            _, transit_star = _nakshatra_from_moon(jd_utc)  # 1-27, from UTC-corrected longitude
            birth_star_idx = utils.NAKSHATRAS.index(birth_nakshatra) + 1
            tb_div = (((transit_star - birth_star_idx + 27) % 27) + 1) % 9
            tb_label, tb_desc = _TARA_BALA_LEVELS.get(tb_div, ("Unknown", "Neutral"))
            tara_str = f"{tb_label} ({tb_desc})"

        # Chandra Bala — same convention.
        # Use jd_utc: utils.graha_sidereal_longitude expects a UTC Julian Day.
        chandra_str = "Unknown"
        with _degradable(
            "personal_balam.chandra_bala", degraded_limbs,
            "muhurat_chandra_bala_unavailable",
        ):
            transit_moon_lon = utils.graha_sidereal_longitude(jd_utc, "Moon")
            transit_moon_sign_idx = int(transit_moon_lon // 30) % 12
            birth_moon_sign_idx = utils.SIGNS.index(birth_moon_sign)
            diff = (transit_moon_sign_idx - birth_moon_sign_idx) % 12 + 1
            if diff in [1, 3, 6, 7, 10, 11]:
                chandra_str = "Good"
            elif diff in [2, 5, 9]:
                chandra_str = "Neutral"
            else:
                chandra_str = "Inauspicious (Avoid)"

        personal = {
            "tara_bala": tara_str,
            "chandra_bala": chandra_str
        }

    # 10. All 30 muhurtas.
    #
    # This limb DEGRADES rather than raising, and the line is drawn on what the
    # limb decides, not on how classical it is: the 30-fold division is a named
    # display table with zero reads anywhere in the scan pipeline (the candidate
    # minutes come from auspicious_muhurtas + chogadiya, not from here), so its
    # loss cannot move the recommended instant. Contrast the panchaka / eclipse /
    # adhika-maasa flags above, which are VETOES and therefore raise. The
    # degradation is explicit: the limb names itself in degraded_limbs.
    #
    # The guard covers ONLY the library call, which had a legitimate
    # environmental failure mode: the division is derived from sunrise/sunset.
    # That mode is now largely unreachable from here — the sunrise/sunset limbs
    # raise before this point on exactly those inputs — but the guard stays,
    # because a library failure that is not the day frame must still not be
    # served as an empty table a consumer cannot tell apart from "this day has
    # no muhurtas".
    #
    # Parsing sits in the `else` block, OUTSIDE the guard, and is strict: an
    # entry that does not match the contracted shape, or a count other than the
    # 30-fold classical division, is a library-contract break rather than
    # weather, and must surface. The predecessor sniffed
    # `isinstance(entry, tuple) and len(entry) >= 2` and read `entry[0]` as a
    # float hour; the real entry is a 3-tuple whose element 0 is the name, so
    # every iteration raised TypeError inside float_hours_to_hhmm, the bare
    # `except Exception` logged it, and the endpoint served `[]` behind HTTP 200
    # with `degraded` still False.
    all_muhur = []
    m30 = None
    with _degradable("all_muhurtas", degraded_limbs, "muhurat_muhurthas_failed"):
        m30 = drik.muhurthas(jd, place)
    if m30 is not None:
        if len(m30) != len(_MUHURTA_NAMES):
            raise ValueError(
                f"muhurthas returned {len(m30)} entries, expected "
                f"{len(_MUHURTA_NAMES)} (the 15 day + 15 night division)"
            )
        # Labels are positional: the library's own key order is the classical
        # sequence, so entry i IS _MUHURTA_NAMES[i] (its transliteration differs,
        # e.g. 'aahi' for 'Ahi', which is why the repo's spelling is kept).
        #
        # entry[0] -- the library's own name for this window -- is therefore
        # DISCARDED here rather than compared, and that is a decision, not an
        # oversight. Comparing it in the served path would need a pinned table of
        # the library's transliterations, and a benign upstream RESPELLING
        # ('kanda' -> 'chanda') would then 500 every request even though a
        # respelling cannot move a single window. What DOES move windows is a
        # REORDER, and the served path cannot tell the two apart without exactly
        # that table. So the order is held where a break is cheap and legible
        # instead: tests/test_muhurat_deep.py pins the library's (name, flag)
        # sequence index by index against _MUHURTA_POSITIONAL_SIGNATURE, together
        # with the label each slot must serve under. That gate is sufficient
        # because the dependency is an exact pin (pyjhora==4.8.7, installed
        # --frozen), so a reorder can only ever arrive through a deliberate,
        # reviewed bump -- and the pin turns that bump red before it ships.
        #
        # Measured 2026-08-05, with nothing pinning the order: transposing two
        # adjacent keys upstream served two windows under each other's names with
        # degraded=False, every entry still matching the contracted shape and the
        # count still 30. Neither check above can see a reorder.
        for name, entry in zip(_MUHURTA_NAMES, m30):
            start_h, end_h = _muhurtha_bounds(entry)
            all_muhur.append({
                "start": float_hours_to_hhmm(start_h),
                "end": float_hours_to_hhmm(end_h),
                "label": name,
            })

    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "sunrise": sr,
        "sunset": ss,
        "moonrise": mr,
        "moonset": ms,
        "panchanga": panchanga,
        "auspicious_muhurtas": auspicious,
        "chogadiya": chogadiya_list,
        "inauspicious_periods": inauspicious,
        "amrita_periods": amrita,
        # bool | None: None == 'panchaka status could not be computed' (fail closed).
        "panchaka_free": panchaka_free,
        "personal_balam": personal,
        "all_muhurtas": all_muhur,
        # Day-level electional gates referenced by per-activity rule tables
        # (lagna_shuddhi._ACTIVITY_RULES.hard_excludes). Always an answered bool
        # from this producer: an unverifiable veto raises rather than resolving
        # to the None that the consumer-side gate reads as 'veto'.
        "is_eclipse_day": _is_eclipse_day(target_date, place),
        "is_adhik_maasa": _is_adhik_maasa(jd, place, target_date),
        # Retained on the wire, and always False from this producer: the three
        # absolute-veto limbs (Rahu/Yama/Gulika) now raise instead of setting
        # it. The field and the consumer-side fail-closed gate that reads it
        # (lagna_shuddhi._score_instant) both stay — removing a served field is
        # a breaking change to /v1, and the gate remains correct for any day
        # payload that carries the flag set.
        "hard_gate_failed": False,
        # DERIVED from degraded_limbs, so the summary flag and the per-limb
        # detail cannot disagree.
        "degraded": bool(degraded_limbs),
        # Which supplementary limbs degraded, by served-field name — a consumer
        # seeing degraded=True can now tell WHAT it lost. Recommendation-
        # affecting limbs are absent from this list by construction: they raise.
        "degraded_limbs": degraded_limbs,
        # NOT on the wire: DayMuhurat declares no such field, so the response
        # model drops it. It is how the electional scan places the Varjyam
        # window on the civil date it actually falls on (see VARJYAM_HOURS_KEY).
        VARJYAM_HOURS_KEY: varjyam_hours,
    }
