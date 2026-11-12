"""Divisional charts follow Parashara's rules, and no library default is inherited.

THE DEFECT THIS CLOSED
----------------------
The D24 (chaturvimsamsa / siddhamsa) call passed no method, and the astronomy
library's default for that one function is NOT Parashara's rule: it counts even
signs from Leo, where BPHS ch. 6 sloka 22 counts odd signs from Leo and even
signs from Cancer. Every graha in an even sign was served one sign too far
forward -- about half of all D24 placements. The other nine vargas happened to
be right only because their library defaults happened to be Parashara's.

WHAT IS PINNED HERE
-------------------
1. ``_bphs_sign`` is an independent implementation of the ten rules, written from
   BPHS ch. 6 (sloka numbers in the standard Sanskrit numbering), never from the
   library:

     D2  6.5-6   odd: 1st half Leo, 2nd Cancer; even: reversed
     D3  6.7-8   the sign, its 5th, its 9th
     D7  6.10    odd: from the sign; even: from its 7th
     D9  6.12    movable: from the sign; fixed: from its 9th; dual: from its 5th
     D10 6.13    odd: from the sign; even: from its 9th
     D12 6.15    from the sign
     D16 6.16    movable: from Aries; fixed: from Leo; dual: from Sagittarius
     D24 6.22    odd: from Leo; even: from Cancer (counted forward)
     D30 6.27    odd: Mars 5, Saturn 5, Jupiter 8, Mercury 7, Venus 5 degrees
                 (Aries, Aquarius, Sagittarius, Gemini, Libra); even: the reverse
                 order Venus 5, Mercury 7, Jupiter 8, Saturn 5, Mars 5 (Taurus,
                 Virgo, Pisces, Capricorn, Scorpio)
     D60 6.33    twice the degrees, divided by 12; remainder + 1, counted from
                 the sign itself

2. An EXHAUSTIVE table test: every one of the 12 signs, at 120 points across each
   sign (0.1 deg + k * 0.25 deg, which never lands on a part boundary of any of
   the ten vargas and hits every part of every one), through the chart module's
   own divisional builder.
3. The serving path: real charts, through ``Chart`` and through POST /v1/chart.
4. The pin itself: the library's varga functions are replaced with ones that
   REFUSE to run on their own default, so a call that inherits a default -- the
   way D24 did -- fails here even if today's default happens to be right.
"""
from __future__ import annotations

import datetime
import random

import pytest
from fastapi.testclient import TestClient
from jhora.horoscope.chart import charts

from app.main import app
from bphs_core import chart as chart_mod
from bphs_core import utils
from bphs_core.chart import Chart, PersonalData

ARIES, TAURUS, GEMINI, CANCER, LEO, VIRGO = 0, 1, 2, 3, 4, 5
LIBRA, SCORPIO, SAGITTARIUS, CAPRICORN, AQUARIUS, PISCES = 6, 7, 8, 9, 10, 11

# snapshot field -> division
_DIVISIONS = {
    "hora_chart": 2, "drekkana_chart": 3, "saptamsa_chart": 7, "navamsa_chart": 9,
    "decamsa_chart": 10, "dwadasamsa_chart": 12, "shodasamsa_chart": 16,
    "chaturvimsa_chart": 24, "trimshamsa_chart": 30, "shashtyamsa_chart": 60,
}
# response field -> snapshot field
_RESPONSE_FIELDS = {
    "hora": "hora_chart", "drekkana": "drekkana_chart", "saptamsa": "saptamsa_chart",
    "navamsa": "navamsa_chart", "decamsa": "decamsa_chart",
    "dwadasamsa": "dwadasamsa_chart", "shodasamsa": "shodasamsa_chart",
    "chaturvimsa": "chaturvimsa_chart", "trimshamsa": "trimshamsa_chart",
    "shashtyamsa": "shashtyamsa_chart",
}


def _bphs_sign(division: int, sign: int, deg: float) -> int:
    """Independent BPHS ch. 6 rule: the divisional sign of a point ``deg`` degrees
    into rasi ``sign`` (0 = Aries). Odd signs are Aries, Gemini, ... (index even)."""
    odd = sign % 2 == 0
    part = int(deg * division / 30.0)
    if division == 2:
        first, second = (LEO, CANCER) if odd else (CANCER, LEO)
        return first if part == 0 else second
    if division == 3:
        return (sign + 4 * part) % 12
    if division == 7:
        return ((sign if odd else sign + 6) + part) % 12
    if division == 9:
        start = {0: sign, 1: sign + 8, 2: sign + 4}[sign % 3]   # movable, fixed, dual
        return (start + part) % 12
    if division == 10:
        return ((sign if odd else sign + 8) + part) % 12
    if division == 12:
        return (sign + part) % 12
    if division == 16:
        return ({0: ARIES, 1: LEO, 2: SAGITTARIUS}[sign % 3] + part) % 12
    if division == 24:
        return ((LEO if odd else CANCER) + part) % 12
    if division == 30:
        spans = ([(5, ARIES), (10, AQUARIUS), (18, SAGITTARIUS), (25, GEMINI), (30, LIBRA)]
                 if odd else
                 [(5, TAURUS), (12, VIRGO), (20, PISCES), (25, CAPRICORN), (30, SCORPIO)])
        return next(s for limit, s in spans if deg < limit)
    if division == 60:
        return (sign + int(deg * 2)) % 12
    raise AssertionError(division)


_GRID = [0.1 + 0.25 * k for k in range(120)]


def test_worked_example_d24_even_sign_counts_from_cancer():
    """Mars at 172.763 deg = Virgo 22.763 deg. By hand: 22.763 / 1.25 = 18.2, so
    part 18; Virgo is even, so count from Cancer: Cancer + 18 = Capricorn.
    (The inherited library default counted from Leo and served Aquarius.)"""
    positions = chart_mod._varga_positions([["L", (VIRGO, 22.763)], [2, (VIRGO, 22.763)]])
    assert positions["chaturvimsa_chart"][1][1][0] == CAPRICORN


def test_worked_example_d24_odd_and_even_first_parts():
    """By hand: Leo 29.9 deg is part 23 of an odd sign -> Leo + 23 = Cancer;
    Taurus 0.5 deg is part 0 of an even sign -> Cancer; Pisces 29.9 deg is part 23
    of an even sign -> Cancer + 23 = Gemini."""
    positions = chart_mod._varga_positions(
        [["L", (LEO, 29.9)], [0, (TAURUS, 0.5)], [1, (PISCES, 29.9)]])["chaturvimsa_chart"]
    assert [p[1][0] for p in positions] == [CANCER, CANCER, GEMINI]


@pytest.mark.parametrize("field", list(_DIVISIONS))
def test_every_sign_and_part_follows_bphs(field):
    """Exhaustive: 12 signs x 120 points, through the chart module's builder."""
    division = _DIVISIONS[field]
    rasi = [["L", (ARIES, 0.1)]] + [[0, (s, d)] for s in range(12) for d in _GRID]
    served = chart_mod._varga_positions(rasi)[field][1:]
    wrong = [
        (utils.SIGNS[s], round(d, 3), utils.SIGNS[got[1][0]], utils.SIGNS[_bphs_sign(division, s, d)])
        for (_pid, (s, d)), got in zip(rasi[1:], served)
        if got[1][0] != _bphs_sign(division, s, d)
    ]
    assert not wrong, f"D{division}: {len(wrong)} of {len(served)} wrong, e.g. {wrong[:4]}"


def _random_people(n: int, seed: int) -> list[PersonalData]:
    rng = random.Random(seed)
    people = []
    for _ in range(n):
        day = datetime.date(1940, 1, 1) + datetime.timedelta(days=rng.randrange(0, 365 * 80))
        people.append(PersonalData(
            name="sample", birth_date=day,
            birth_time=datetime.time(rng.randrange(24), rng.randrange(60)),
            birth_place="Sample City", latitude=round(rng.uniform(-60, 60), 2),
            longitude=round(rng.uniform(-180, 180), 2),
            timezone_offset_hours=rng.choice([-8.0, -5.0, 0.0, 1.0, 5.5, 9.0]),
        ))
    return people


def _near_boundary(division: int, deg: float, tol: float = 1e-6) -> bool:
    edges = [5, 10, 12, 18, 20, 25] if division == 30 else []
    width = 30.0 / division
    to_part_edge = min(deg % width, width - deg % width)
    return to_part_edge < tol or any(abs(deg - e) < tol for e in edges)


def test_served_vargas_follow_bphs_on_real_charts():
    """Through ``Chart``: 40 fictitious births, every graha, every varga, the
    expected sign derived independently from the served unrounded rasi longitude."""
    wrong = []
    for person in _random_people(40, seed=24):
        snap = Chart(person).snapshot()
        for field, division in _DIVISIONS.items():
            varga = getattr(snap, field)
            for name, rasi_pd in snap.rasi_chart.items():
                lon = rasi_pd.longitude_abs
                sign, deg = int(lon // 30), lon % 30
                if _near_boundary(division, deg):
                    continue
                want = utils.SIGNS[_bphs_sign(division, sign, deg)]
                if varga[name].sign != want:
                    wrong.append((field, name, rasi_pd.sign, round(deg, 3), varga[name].sign, want))
    assert not wrong, f"{len(wrong)} wrong placements, e.g. {wrong[:4]}"


def test_route_serves_bphs_d24():
    """Through POST /v1/chart: every graha's served D24 sign is the BPHS one,
    derived from the served rasi sign and degrees."""
    births = ("1950-06-15", "1975-12-01", "1990-05-15", "2000-03-21", "2012-09-09")
    # One context-managed client: requests reuse one event loop's worker threads.
    with TestClient(app, headers={"X-Calc-Service-Token": "test"}) as client:
        responses = [(birth, client.post("/v1/chart", json={
            "name": "sample", "birth_date": birth, "birth_time": "10:30:00",
            "birth_place": "Sample City", "latitude": 6.93, "longitude": 79.86,
            "timezone_offset_hours": 5.5,
        })) for birth in births]
    for birth, r in responses:
        assert r.status_code == 200, r.text
        body = r.json()
        d24 = {p["planet"]: p["sign"] for p in body["chaturvimsa"]}
        for p in body["rasi"]:
            if _near_boundary(24, p["degrees"], tol=1e-4):  # served degrees are 4 dp
                continue
            want = utils.SIGNS[_bphs_sign(24, utils.SIGNS.index(p["sign"]), p["degrees"])]
            assert d24[p["planet"]] == want, (birth, p["planet"], p["sign"], p["degrees"])


_MISSING = object()


def test_no_varga_call_inherits_a_library_default(monkeypatch):
    """Every varga function the engine calls is replaced with one that refuses to
    run without an explicit ``chart_method``. A future library release that moves
    a default therefore cannot move a served chart: the engine never reads one."""
    library_functions = sorted({
        "hora_chart", "drekkana_chart", "saptamsa_chart", "navamsa_chart",
        "dasamsa_chart", "dwadasamsa_chart", "shodasamsa_chart",
        "chaturvimsamsa_chart", "trimsamsa_chart", "shashtyamsa_chart",
    })
    called = []

    def refusing(name, real):
        def wrapper(positions, chart_method=_MISSING):
            assert chart_method is not _MISSING, f"charts.{name} called on its library default"
            called.append(name)
            return real(positions, chart_method=chart_method)
        return wrapper

    for name in library_functions:
        monkeypatch.setattr(charts, name, refusing(name, getattr(charts, name)))
    Chart(_random_people(1, seed=1)[0])
    assert sorted(called) == library_functions


def test_a_moved_library_default_does_not_move_a_served_chart(monkeypatch):
    """Simulates the dependency bump directly: every varga function's default is
    changed to a different method, and the served chart must not change."""
    person = _random_people(1, seed=7)[0]
    before = Chart(person).snapshot()
    for name in ("hora_chart", "drekkana_chart", "saptamsa_chart", "navamsa_chart",
                 "dasamsa_chart", "dwadasamsa_chart", "shodasamsa_chart",
                 "chaturvimsamsa_chart", "trimsamsa_chart", "shashtyamsa_chart"):
        fn = getattr(charts, name)
        monkeypatch.setattr(fn, "__defaults__", (3 if fn.__defaults__ != (3,) else 2,))
    after = Chart(person).snapshot()
    for field in _DIVISIONS:
        assert ({n: p.sign for n, p in getattr(after, field).items()}
                == {n: p.sign for n, p in getattr(before, field).items()}), field
