"""Contract: retrogression belongs to the INSTANT, and it reaches every varga.

A graha's vakri state is decided by the direction it is moving at the moment the
chart is cast. A divisional chart re-maps longitude onto a finer grid; it does
not change the direction anything is moving. So the flag a varga serves must be
the flag the rasi chart serves -- for every graha, in every varga -- and it must
be the astronomically correct one. Extend this file, never weaken it.

WHY THIS FILE EXISTS -- the coverage gap it closes, measured 2026-08-09 on the
then-frozen resolve (pyjhora 4.8.6 / pyswisseph 2.10.3.2; re-run unchanged on the
now-pinned 4.8.7) against the real Swiss data
files. Before this file, nothing in this suite observed a CLASSICAL graha's
``is_retrograde`` in ANY divisional chart. Sever the propagation at the varga
construction site -- replace ``computed=pid in retro_planets`` with
``computed=False`` in ``chart.py::_build_varga_chart``, so that every classical
graha is reported DIRECT in all ten vargas on every date -- and the whole suite
still passed, 741 tests, zero failures. The shadow grahas were already pinned in
every varga by tests/test_shadow_graha_retrogression.py, but
``utils.graha_is_retrograde`` returns True for Rahu and Ketu whatever
``computed`` says, so those assertions are blind to exactly that mutation. A
wrong vakri flag in a divisional chart moves the dignity reading and the karaka
interpretation, and it was invisible. (It no longer moves cheshta bala, which
comes from the cheshta kendra, BPHS 27.24-25, and reads no flag.)

WHAT WAS MEASURED ABOUT THE MECHANISM: the gap is PROPAGATION, not an
independent per-varga computation. ``chart.py`` calls
``drik.planets_in_retrograde`` exactly once and hands the same result to all ten
``_build_varga_chart`` calls, so a varga's flag is the rasi flag by construction
and there is exactly one link where it can be severed. Measured across eight
charts x eleven charts x seven classical grahas: zero varga/rasi disagreements.
Nothing about the served values was wrong; what was missing was anything that
would notice if they became wrong.

BOTH DIRECTIONS ARE PINNED, because only one of them can fail on its own:

* the POSITIVE control -- a graha genuinely retrograde at the instant reports
  retrograde in every varga;
* the NEGATIVE control -- the SAME graha, at a different instant where it is
  genuinely direct, reports NOT retrograde in every varga.

Every one of the five tara grahas appears retrograde in at least one fixture and
direct in at least one other, and ``test_the_fixture_table_observes_both_states``
asserts that property of the table itself -- a table that quietly degenerated
into all-direct would satisfy every other assertion here while proving nothing,
which is the precise defect being closed.

FIXTURE CHOICE -- margin from station. A graha within hours of stationing flips
on a hair's-breadth ephemeris difference, so every fixture below is far from
every station. Margins measured at hourly resolution at the fixture's own UT
instant (station = the nearest sign change of sidereal longitude speed):

    fixture       worst margin   graha         Sun/Moon
    1982-04-03    38.08 d        Jupiter       never station
    1948-06-23    11.83 d        Mercury       never station
    1977-07-03    50.33 d        Mercury       never station

11.83 d is close to the arithmetic maximum for Mercury, whose retrograde spell
lasts about 24 days. Margin in days understates the real safety factor; the
number that matters is how far the motion is from zero compared with how much
the two ephemeris runtimes disagree about it. Measured across all three
fixtures, the slowest graha of all (Saturn on 1982-04-03, 0.0765 deg/day) sits
3.2e5 times its own Swiss-vs-Moshier speed disagreement away from zero, and no
graha at any fixture is closer than 1.2e5 -- the sign cannot flip.

BOTH EPHEMERIS RUNTIMES. Every assertion here holds under the real Swiss data
files and under swisseph's built-in Moshier fallback -- verified 2026-08-09 by
running the served retrograde set of all eleven charts at all three fixtures
under each runtime and diffing: identical, every chart, every graha. That is a
requirement for anything in ``tests/`` (see CLAUDE.md); an instant whose answer
depends on the ephemeris source is a bad fixture, not a finding.

THE LUNAR NODES ARE NOT RE-DERIVED HERE. Rahu and Ketu are served retrograde by
DECLARATION (``utils.PERPETUALLY_RETROGRADE_GRAHAS``) because the true node's own
speed is positive about a quarter of the time and its sign near the turning
points differs between the two runtimes. This file takes that declaration as
given -- the expected sets below are built from it rather than restating it, so
there is one place the node reading lives, and tests/test_shadow_graha_retrogression.py
remains its tripwire.
"""
import datetime as dt
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bphs_core import utils
from bphs_core.chart import Chart, PersonalData

# The seven grahas whose retrogression is COMPUTED from the ephemeris. The two
# shadow grahas are declared, not computed, and are handled separately below.
CLASSICAL_GRAHAS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")

# The five tara grahas -- the only grahas that genuinely reverse. Sun and Moon
# never do, so they are permanent negative controls and can never supply a
# positive one.
TARA_GRAHAS = ("Mars", "Mercury", "Jupiter", "Venus", "Saturn")

# Synthetic, non-personal instants. Location is irrelevant to retrogression
# (it is geocentric) and is held fixed; only the instant varies.
_LATITUDE = 7.0
_LONGITUDE = 80.0
_TZ_OFFSET_HOURS = 5.5
_BIRTH_TIME = dt.time(12, 0, 0)

# date -> (grahas measured RETROGRADE, grahas measured DIRECT). Recorded from
# the served chart and independently cross-checked, per fixture per graha, by
# ``test_the_fixture_table_matches_an_independent_computation`` below, so these
# are verified goldens rather than a snapshot of whatever the engine said.
FIXTURES = {
    # Three slow grahas retrograde at once; worst station margin 38.08 d.
    dt.date(1982, 4, 3): (
        frozenset({"Mars", "Jupiter", "Saturn"}),
        frozenset({"Sun", "Moon", "Mercury", "Venus"}),
    ),
    # The two fast tara grahas retrograde; worst station margin 11.83 d
    # (Mercury, near the arithmetic maximum for a ~24-day retrograde spell).
    dt.date(1948, 6, 23): (
        frozenset({"Mercury", "Venus", "Jupiter"}),
        frozenset({"Sun", "Moon", "Mars", "Saturn"}),
    ),
    # Every classical graha direct; worst station margin 50.33 d. This is the
    # matched negative control for Jupiter, which is retrograde in both of the
    # fixtures above.
    dt.date(1977, 7, 3): (
        frozenset(),
        frozenset(CLASSICAL_GRAHAS),
    ),
}

# Half-width of the central difference used for the independent motion
# reference. 0.5 d is short enough that no fixture's graha reverses inside the
# window (the smallest margin is 11.83 d) and long enough that the smallest
# genuine motion at any fixture, 0.0765 deg/day, is five orders of magnitude
# above the runtimes' disagreement.
_MOTION_HALF_WIDTH_DAYS = 0.5


def _person(date: dt.date) -> PersonalData:
    return PersonalData(
        name="sample_varga_retro",
        birth_date=dt.datetime(date.year, date.month, date.day),
        birth_time=_BIRTH_TIME,
        birth_place="Sample City",
        latitude=_LATITUDE,
        longitude=_LONGITUDE,
        timezone_offset_hours=_TZ_OFFSET_HOURS,
    )


@lru_cache(maxsize=None)
def _snapshot(date: dt.date):
    return Chart(_person(date)).snapshot()


def _charts(snapshot) -> dict[str, dict]:
    """The rasi chart plus every divisional chart, keyed by attribute name.

    Collected by introspection rather than a hand-written list, so a varga added
    later is covered without editing this file -- and so a varga that silently
    stops being exposed shrinks the sweep visibly instead of quietly.
    """
    found = {
        name: getattr(snapshot, name)
        for name in dir(snapshot)
        if name.endswith("_chart") and isinstance(getattr(snapshot, name), dict)
    }
    # 11 = the rasi chart plus the ten vargas the snapshot exposed when this was
    # counted from the snapshot itself, 2026-08-09. A floor, not an equality, so
    # a new varga is swept too -- but a sweep that collapsed to nothing cannot
    # pass vacuously.
    assert len(found) >= 11, (
        f"expected the rasi chart plus the divisional charts, found {sorted(found)}"
    )
    return found


def _vargas(snapshot) -> dict[str, dict]:
    """The divisional charts only -- the rasi chart is the reference, not a varga."""
    return {n: c for n, c in _charts(snapshot).items() if n != "rasi_chart"}


def _expected_retrograde(date: dt.date) -> frozenset[str]:
    """Everything served as retrograde at *date*: the measured classical set
    plus the DECLARED perpetually-retrograde shadow grahas, taken from the
    declaration rather than restated here."""
    return FIXTURES[date][0] | utils.PERPETUALLY_RETROGRADE_GRAHAS


def _served_retrograde(chart: dict) -> frozenset[str]:
    return frozenset(g for g, placement in chart.items() if placement.is_retrograde)


def _daily_motion(jd_utc: float, graha: str) -> float:
    """Sidereal longitude motion in deg/day, by central difference.

    Independent of ``chart.py`` and of ``drik.planets_in_retrograde``: that path
    reads the speed swisseph reports alongside a position, this one differences
    two positions taken through the sanctioned name-keyed boundary
    (``utils.graha_sidereal_longitude``). Agreement between the two is evidence
    the served flag is astronomically right, not merely self-consistent.
    """
    before = utils.graha_sidereal_longitude(jd_utc - _MOTION_HALF_WIDTH_DAYS, graha)
    after = utils.graha_sidereal_longitude(jd_utc + _MOTION_HALF_WIDTH_DAYS, graha)
    # Shortest signed arc, so a graha crossing 0 deg inside the window does not
    # read as a 360 deg leap.
    return ((after - before + 180.0) % 360.0) - 180.0


class TestTheFixtureTable:
    """The table is data, so it needs its own guards: an expectation set that
    quietly lost a graha, or that only ever said "direct", would leave every
    assertion in this file passing while it observed nothing."""

    @pytest.mark.parametrize("date", sorted(FIXTURES))
    def test_each_fixture_classifies_every_classical_graha(self, date):
        retro, direct = FIXTURES[date]
        assert retro.isdisjoint(direct), (
            f"{date} lists {sorted(retro & direct)} as both retrograde and direct"
        )
        assert retro | direct == frozenset(CLASSICAL_GRAHAS), (
            f"{date} does not classify every classical graha: "
            f"missing {sorted(frozenset(CLASSICAL_GRAHAS) - (retro | direct))}"
        )

    def test_the_fixture_table_observes_both_states(self):
        """Every tara graha must appear retrograde somewhere AND direct
        somewhere.

        Without this, the table could drift to all-direct -- and a suite that
        only ever asserts False passes against an engine that hardcodes False,
        which is the exact degradation this file was written to catch.
        """
        seen_retrograde = frozenset().union(*(r for r, _ in FIXTURES.values()))
        seen_direct = frozenset().union(*(d for _, d in FIXTURES.values()))
        assert frozenset(TARA_GRAHAS) <= seen_retrograde, (
            "no fixture observes "
            f"{sorted(frozenset(TARA_GRAHAS) - seen_retrograde)} retrograde -- "
            "those grahas have no positive control"
        )
        assert frozenset(TARA_GRAHAS) <= seen_direct, (
            "no fixture observes "
            f"{sorted(frozenset(TARA_GRAHAS) - seen_direct)} direct -- "
            "those grahas have no negative control"
        )

    def test_sun_and_moon_are_never_claimed_retrograde(self):
        """They cannot be. A table claiming otherwise is wrong before anything
        is computed."""
        for date, (retro, _) in FIXTURES.items():
            assert not retro & {"Sun", "Moon"}, (
                f"{date} claims {sorted(retro & {'Sun', 'Moon'})} retrograde"
            )

    @pytest.mark.parametrize("date", sorted(FIXTURES))
    def test_the_fixture_table_matches_an_independent_computation(self, date):
        """The goldens are verified, not merely recorded.

        A retrograde set read off the engine and pinned back against the engine
        proves only that the engine is consistent with itself. This differences
        two sidereal longitudes taken through the name-keyed boundary and checks
        the sign, so a fixture that pinned the wrong astronomy fails here.
        """
        snapshot = _snapshot(date)
        retro, _ = FIXTURES[date]
        for graha in CLASSICAL_GRAHAS:
            motion = _daily_motion(snapshot.jd, graha)
            assert (motion < 0.0) is (graha in retro), (
                f"{graha} on {date}: the fixture table says "
                f"{'retrograde' if graha in retro else 'direct'} but its "
                f"independently computed motion is {motion:+.6f} deg/day"
            )


class TestServedInEveryVarga:
    @pytest.mark.parametrize("date", sorted(FIXTURES))
    def test_every_varga_serves_the_measured_retrograde_set(self, date):
        """The whole set, per varga -- not merely "the retrograde ones are
        retrograde".

        Asserting the SET is what makes the negative direction load-bearing: a
        blanket True is as much a failure as a blanket False, and only an
        equality catches both.
        """
        snapshot = _snapshot(date)
        expected = _expected_retrograde(date)
        for varga_name, varga in sorted(_vargas(snapshot).items()):
            served = _served_retrograde(varga)
            assert served == expected, (
                f"{varga_name} on {date} serves retrograde={sorted(served)}, "
                f"expected {sorted(expected)}; "
                f"wrongly direct={sorted(expected - served)}, "
                f"wrongly retrograde={sorted(served - expected)}"
            )

    @pytest.mark.parametrize("date", sorted(FIXTURES))
    def test_every_varga_agrees_with_the_rasi_chart(self, date):
        """Retrogression is a property of the instant, so a divisional mapping
        cannot change it. This is the propagation invariant itself, independent
        of what the recorded sets happen to say."""
        snapshot = _snapshot(date)
        rasi = snapshot.rasi_chart
        for varga_name, varga in sorted(_vargas(snapshot).items()):
            disagreements = {
                g: (rasi[g].is_retrograde, varga[g].is_retrograde)
                for g in rasi
                if varga[g].is_retrograde != rasi[g].is_retrograde
            }
            assert not disagreements, (
                f"{varga_name} on {date} disagrees with the rasi chart "
                f"(graha: rasi, varga) {disagreements} -- a divisional chart "
                "cannot change the direction a graha is moving"
            )

    @pytest.mark.parametrize("graha", CLASSICAL_GRAHAS)
    @pytest.mark.parametrize("date", sorted(FIXTURES))
    def test_navamsa_pins_each_classical_graha_individually(self, date, graha):
        """D9 called out on its own, per graha.

        Navamsa is the divisional chart that carries the most interpretive
        weight, and a per-graha parametrisation names the offender in the
        failure rather than reporting a set difference.
        """
        expected = graha in FIXTURES[date][0]
        served = _snapshot(date).navamsa_chart[graha].is_retrograde
        assert served is expected, (
            f"navamsa on {date} serves {graha} as "
            f"{'retrograde' if served else 'direct'}; it is measured "
            f"{'retrograde' if expected else 'direct'} at that instant"
        )

    @pytest.mark.parametrize("date", sorted(FIXTURES))
    def test_shashtyamsa_pins_the_same_set(self, date):
        """D60 -- the finest division, and the one furthest from the rasi grid.

        Named explicitly alongside D9 so the coverage does not rest solely on
        the introspecting sweep: if the sweep ever stopped finding the vargas,
        two hand-named charts still fail.
        """
        served = _served_retrograde(_snapshot(date).shashtyamsa_chart)
        assert served == _expected_retrograde(date)


class TestServedOverTheWire:
    """The flag has to reach the caller, not merely exist on the dataclass."""

    @pytest.mark.parametrize("date", sorted(FIXTURES))
    def test_every_varga_in_the_response_carries_the_retrograde_flag(self, date):
        client = TestClient(app, headers={"X-Calc-Service-Token": "test"})
        response = client.post("/v1/chart", json={
            "name": "sample_varga_retro",
            "birth_date": date.isoformat(),
            "birth_time": _BIRTH_TIME.isoformat(),
            "birth_place": "Sample City",
            "latitude": _LATITUDE,
            "longitude": _LONGITUDE,
            "timezone_offset_hours": _TZ_OFFSET_HOURS,
        })
        assert response.status_code == 200, response.text
        body = response.json()

        varga_keys = [
            "hora", "drekkana", "saptamsa", "navamsa", "decamsa", "dwadasamsa",
            "shodasamsa", "chaturvimsa", "trimshamsa", "shashtyamsa",
        ]
        expected = _expected_retrograde(date)
        for key in ["rasi", *varga_keys]:
            placements = body[key]
            assert len(placements) == 9, (
                f"{key} carries {len(placements)} placements, expected 9 grahas"
            )
            served = frozenset(p["planet"] for p in placements if p["is_retrograde"])
            assert served == expected, (
                f"the {key} payload on {date} serves retrograde={sorted(served)}, "
                f"expected {sorted(expected)}"
            )
