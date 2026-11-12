from dataclasses import dataclass
from datetime import datetime, timedelta

from . import utils
from .chart import ChartSnapshot

# Vimshottari dasha years per lord (total cycle = 120 years)
VIMSHOTTARI_YEARS: dict[str, float] = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}
VIMSHOTTARI_ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars",
                     "Rahu", "Jupiter", "Saturn", "Mercury"]

# Nakshatra → dasha lord (every 3 nakshatras per planet, repeating)
NAKSHATRA_LORDS = {
    "Ashwini": "Ketu", "Bharani": "Venus", "Krittika": "Sun",
    "Rohini": "Moon", "Mrigashira": "Mars", "Ardra": "Rahu",
    "Punarvasu": "Jupiter", "Pushya": "Saturn", "Ashlesha": "Mercury",
    "Magha": "Ketu", "Purva Phalguni": "Venus", "Uttara Phalguni": "Sun",
    "Hasta": "Moon", "Chitra": "Mars", "Swati": "Rahu",
    "Vishakha": "Jupiter", "Anuradha": "Saturn", "Jyeshtha": "Mercury",
    "Mula": "Ketu", "Purva Ashadha": "Venus", "Uttara Ashadha": "Sun",
    "Shravana": "Moon", "Dhanishta": "Mars", "Shatabhisha": "Rahu",
    "Purva Bhadrapada": "Jupiter", "Uttara Bhadrapada": "Saturn", "Revati": "Mercury",
}

# Yogini dasha lords (8-year cycle)
YOGINI_ORDER = ["Mangala", "Pingala", "Dhanya", "Bhramari",
                "Bhadrika", "Ulka", "Siddha", "Sankata"]
YOGINI_YEARS: dict[str, float] = {
    "Mangala": 1, "Pingala": 2, "Dhanya": 3, "Bhramari": 4,
    "Bhadrika": 5, "Ulka": 6, "Siddha": 7, "Sankata": 8,
}
YOGINI_PLANET_MAP: dict[str, str] = {
    "Mangala": "Moon", "Pingala": "Sun", "Dhanya": "Jupiter",
    "Bhramari": "Mars", "Bhadrika": "Mercury", "Ulka": "Saturn",
    "Siddha": "Venus", "Sankata": "Rahu",
}


@dataclass
class DashaPeriod:
    lord: str
    level: str
    system: str
    start_date: datetime
    end_date: datetime
    duration_years: float


def _moon_nakshatra_and_fraction(snapshot: ChartSnapshot) -> tuple[str, float]:
    moon = snapshot.rasi_chart.get("Moon")
    if moon is None:
        return "Ashwini", 0.0
    # Prefer the unrounded absolute longitude (carried on the rasi chart). The
    # dasha balance is a fraction of the Moon's position within its nakshatra, so
    # reconstructing from sign + degrees rounded to 4dp can shift the first
    # mahadasha start by ~an hour. Fall back to reconstruction for mocks/snapshots
    # that do not carry longitude_abs.
    if moon.longitude_abs is not None:
        total_lon = moon.longitude_abs % 360
    else:
        total_lon = (utils.SIGNS.index(moon.sign) * 30 + moon.degrees) % 360
    nak_size = 360 / 27
    nak_idx = int(total_lon / nak_size)
    fraction_elapsed = (total_lon % nak_size) / nak_size
    return utils.NAKSHATRAS[nak_idx], fraction_elapsed


def vimshottari_mahadashas(snapshot: ChartSnapshot,
                             birth_date: datetime,
                             end_date: datetime | None = None) -> list[DashaPeriod]:
    nak, fraction = _moon_nakshatra_and_fraction(snapshot)
    start_lord = NAKSHATRA_LORDS[nak]
    start_idx = VIMSHOTTARI_ORDER.index(start_lord)

    total_years_first = VIMSHOTTARI_YEARS[start_lord]
    elapsed = fraction * total_years_first

    periods: list[DashaPeriod] = []
    current = birth_date - timedelta(days=elapsed * 365.25)

    cycle_count = 1
    if end_date:
        cycle_count = max(2, int((end_date - birth_date).days / (120 * 365.25)) + 2)

    for i in range(9 * cycle_count):
        lord = VIMSHOTTARI_ORDER[(start_idx + i) % 9]
        yrs = VIMSHOTTARI_YEARS[lord]
        end = current + timedelta(days=yrs * 365.25)
        periods.append(DashaPeriod(
            lord=lord, level="mahadasha", system="vimshottari",
            start_date=current, end_date=end, duration_years=round(yrs, 4),
        ))
        current = end

    return periods


def _vimshottari_antardashas(mahadasha: DashaPeriod) -> list[DashaPeriod]:
    md_lord = mahadasha.lord
    md_years = VIMSHOTTARI_YEARS[md_lord]
    start_idx = VIMSHOTTARI_ORDER.index(md_lord)

    periods: list[DashaPeriod] = []
    current = mahadasha.start_date

    for i in range(9):
        ad_lord = VIMSHOTTARI_ORDER[(start_idx + i) % 9]
        ad_years = (VIMSHOTTARI_YEARS[ad_lord] * md_years) / 120.0
        end = current + timedelta(days=ad_years * 365.25)
        periods.append(DashaPeriod(
            lord=ad_lord, level="antardasha", system="vimshottari",
            start_date=current, end_date=end, duration_years=round(ad_years, 4),
        ))
        current = end

    return periods


def _yogini_dashas(snapshot: ChartSnapshot,
                   birth_date: datetime,
                   end_date: datetime | None = None) -> list[DashaPeriod]:
    nak, fraction = _moon_nakshatra_and_fraction(snapshot)
    # BPHS ch. 46 sloka 199 (standard Sanskrit numbering): add three to the birth
    # nakshatra's number (Ashwini = 1) and divide by eight; the remainder, counted
    # from one, is the starting yogini in YOGINI_ORDER, a remainder of 0 being the
    # eighth (Sankata). With the zero-based index n that is (n + 1 + 3 - 1) mod 8,
    # so Ashwini starts Bhramari (Mars) and Uttara Ashadha Sankata (Rahu).
    nak_idx = utils.NAKSHATRAS.index(nak)
    yogini_idx = (nak_idx + 3) % 8
    start_yogini = YOGINI_ORDER[yogini_idx]
    total_first = YOGINI_YEARS[start_yogini]
    elapsed = fraction * total_first

    periods: list[DashaPeriod] = []
    current = birth_date - timedelta(days=elapsed * 365.25)

    cycle_count = 1
    if end_date:
        cycle_count = max(2, int((end_date - birth_date).days / (36 * 365.25)) + 2)

    for i in range(8 * cycle_count):
        yogini = YOGINI_ORDER[(yogini_idx + i) % 8]
        yrs = YOGINI_YEARS[yogini]
        end = current + timedelta(days=yrs * 365.25)
        periods.append(DashaPeriod(
            lord=YOGINI_PLANET_MAP[yogini], level="mahadasha", system="yogini",
            start_date=current, end_date=end, duration_years=round(yrs, 4),
        ))
        current = end

    return periods


def get_dasha_timeline(snapshot: ChartSnapshot,
                       start: datetime, end: datetime,
                       systems: list[str]) -> list[DashaPeriod]:
    birth = datetime.combine(snapshot.person.birth_date, snapshot.person.birth_time)
    result: list[DashaPeriod] = []

    if "vimshottari" in systems:
        mahadashas = vimshottari_mahadashas(snapshot, birth, end)
        for md in mahadashas:
            if md.end_date < start or md.start_date > end:
                continue
            result.append(md)
            for ad in _vimshottari_antardashas(md):
                if ad.end_date < start or ad.start_date > end:
                    continue
                result.append(ad)

    if "yogini" in systems:
        for yd in _yogini_dashas(snapshot, birth, end):
            if yd.end_date < start or yd.start_date > end:
                continue
            result.append(yd)

    result.sort(key=lambda d: (d.start_date, d.level))
    return result


def get_active_dasha(snapshot: ChartSnapshot, at: datetime,
                     system: str = "vimshottari") -> DashaPeriod | None:
    birth = datetime.combine(snapshot.person.birth_date, snapshot.person.birth_time)
    if system == "vimshottari":
        mahadashas = vimshottari_mahadashas(snapshot, birth)
        for md in mahadashas:
            if md.start_date <= at < md.end_date:
                return md
    elif system == "yogini":
        for yd in _yogini_dashas(snapshot, birth):
            if yd.start_date <= at < yd.end_date:
                return yd
    return None
