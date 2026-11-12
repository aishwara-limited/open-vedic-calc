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
  one instant AND that instant carries the day's offset.
* ``FixedOffsetClock`` -- one fixed offset for every date, every wall time
  usable. This is what a request without an IANA zone has always meant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

import pytz


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


class ZoneClock:
    def __init__(self, tz_name: str):
        # Raises pytz.UnknownTimeZoneError for a name the tz database does not
        # hold; request validation calls is_known_zone first.
        self._tz = pytz.timezone(tz_name)
        self._noon_cache: dict[date, float] = {}

    def offset_for(self, day: date) -> float:
        cached = self._noon_cache.get(day)
        if cached is None:
            noon = datetime(day.year, day.month, day.day, 12, 0)
            cached = _hours(self._tz.localize(noon, is_dst=None).utcoffset())
            self._noon_cache[day] = cached
        return cached

    def usable(self, day: date, minute_of_day: int) -> bool:
        wall = datetime(day.year, day.month, day.day) + timedelta(minutes=minute_of_day)
        try:
            aware = self._tz.localize(wall, is_dst=None)
        except (pytz.NonExistentTimeError, pytz.AmbiguousTimeError):
            return False
        return _hours(aware.utcoffset()) == self.offset_for(day)


def is_known_zone(tz_name: str) -> bool:
    try:
        pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        return False
    return True


def make_clock(tz_offset: float, tz_name: str | None) -> EventClock:
    """The clock for a scan: the IANA zone when one is given, else the fixed
    offset a request without a zone has always carried."""
    if tz_name:
        return ZoneClock(tz_name)
    return FixedOffsetClock(tz_offset)
