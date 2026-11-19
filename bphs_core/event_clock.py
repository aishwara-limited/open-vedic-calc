"""The wall clock a muhurat scan reads its local times on.

A UTC offset is a property of a DATE in a place, not of a person: London is
UTC+1 in July and UTC+0 in December, and Colombo was UTC+6:00 from 1996 to 2006
and is UTC+5:30 now. A scan that spans dates therefore needs the offset in
force on each date it scans, and on the day a clock changes it must not offer a
local time that does not exist, that names two different instants, or that
sits on the other side of the change from the rest of the day.

Two strategies behind one interface:

* ``ZoneClock`` -- an IANA zone, resolved from the tz database per date. The
  day's offset is the one in force at local noon (clock changes happen at
  night, so noon is on the side of the change that holds for the daylight
  hours the scan is about); a wall time is usable only when it maps to exactly
  one instant AND that instant carries the day's offset. A day whose noon
  itself maps to no instant or to two (a zone that skipped a whole date, or
  left local mean time at noon) has no offset to choose, and raises
  ``MuhurtaLimbError`` for the ``utc_offset`` limb rather than guessing.
* ``FixedOffsetClock`` -- one fixed offset for every date, every wall time
  usable. This is what a request without an IANA zone has always meant.

The tz database is read through the standard library's ``zoneinfo`` from the
``tzdata`` package and from nowhere else, never the host's own zoneinfo
directory, so every environment answers from the one locked copy.
``zoneinfo`` reads a zone's full history and applies its continuing rule after
the last transition the data lists, so a scanned date in 1850 or in 2399 is on
the clock the zone's rules give it -- a reader that holds only a fixed table of
transitions answers every date past the table's end with the last entry's
offset.
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib import resources
from typing import Protocol
from zoneinfo import ZoneInfo

from .muhurat import MuhurtaLimbError

logger = logging.getLogger(__name__)

# The limb a MuhurtaLimbError names when a day's offset cannot be chosen.
UTC_OFFSET_LIMB = "utc_offset"

_NOON_HINT = (
    "local noon does not name exactly one instant in the event zone on this "
    "date (the zone skipped or repeated it), so the day's UTC offset cannot "
    "be chosen"
)

# Listed by the tz database but not the zone of any place: it means "local time
# unknown" and carries offset 0, so accepting it would serve UTC as though it
# were the event's clock.
_NOT_A_PLACE = frozenset({"Factory"})


class EventClock(Protocol):
    def offset_for(self, day: date) -> float:
        """UTC offset in hours in force on ``day``."""

    def usable(self, day: date, minute_of_day: int) -> bool:
        """True when the local wall time ``day`` + ``minute_of_day`` names
        exactly one instant and that instant carries ``offset_for(day)``."""


@dataclass(frozen=True)
class FixedOffsetClock:
    tz_offset: float

    def offset_for(self, day: date) -> float:
        return self.tz_offset

    def usable(self, day: date, minute_of_day: int) -> bool:
        return True


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600.0


@functools.cache
def _zone_keys() -> dict[str, str]:
    """Every zone key the tzdata package holds, by its case-folded name."""
    listing = resources.files("tzdata").joinpath("zones").read_text(encoding="utf-8")
    keys = (line.strip() for line in listing.splitlines())
    return {key.casefold(): key for key in keys if key and key not in _NOT_A_PLACE}


def _canonical_zone(tz_name: str) -> str | None:
    """The tzdata key ``tz_name`` names, matched without regard to case."""
    return _zone_keys().get(tz_name.casefold())


@functools.cache
def _load_zone(key: str) -> ZoneInfo:
    """Load ``key`` from the tzdata package's own files. ``key`` is always one
    the package lists (``_canonical_zone``), so no submitted text ever becomes
    a path."""
    *package, name = key.split("/")
    resource = resources.files(".".join(["tzdata.zoneinfo", *package])).joinpath(name)
    with resource.open("rb") as tzif:
        return ZoneInfo.from_file(tzif, key=key)


class ZoneClock:
    def __init__(self, tz_name: str):
        key = _canonical_zone(tz_name)
        if key is None:
            # Request validation calls is_known_zone first; never echoes the name.
            raise ValueError("not an IANA time zone name")
        self._tz = _load_zone(key)
        self._noon_cache: dict[date, float] = {}

    def _offsets(self, wall: datetime) -> tuple[timedelta, timedelta]:
        """The offsets of the earlier and the later reading of ``wall``. They
        differ exactly when ``wall`` is skipped or repeated (PEP 495 ``fold``)."""
        return (
            wall.replace(tzinfo=self._tz, fold=0).utcoffset(),
            wall.replace(tzinfo=self._tz, fold=1).utcoffset(),
        )

    def offset_for(self, day: date) -> float:
        cached = self._noon_cache.get(day)
        if cached is None:
            earlier, later = self._offsets(datetime(day.year, day.month, day.day, 12, 0))
            if earlier != later:
                logger.error("muhurat_utc_offset_failed")
                raise MuhurtaLimbError(UTC_OFFSET_LIMB, day, _NOON_HINT)
            cached = _hours(earlier)
            self._noon_cache[day] = cached
        return cached

    def usable(self, day: date, minute_of_day: int) -> bool:
        wall = datetime(day.year, day.month, day.day) + timedelta(minutes=minute_of_day)
        earlier, later = self._offsets(wall)
        return earlier == later and _hours(earlier) == self.offset_for(day)


def is_known_zone(tz_name: str) -> bool:
    return _canonical_zone(tz_name) is not None


def make_clock(tz_offset: float, tz_name: str | None) -> EventClock:
    """The clock for a scan: the IANA zone when one is given, else the fixed
    offset a request without a zone has always carried."""
    if tz_name:
        return ZoneClock(tz_name)
    return FixedOffsetClock(tz_offset)
