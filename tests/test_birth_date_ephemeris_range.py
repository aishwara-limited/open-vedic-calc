"""FR-LOW-2 — birth_date must fall within the supported ephemeris range.

PersonalDataIn.birth_date / FamilyMember.birth_date previously accepted any
year 1-9999 and reached swe.julday() unguarded. An extreme year outside the
loaded ephemeris data's range is at best a 500 and possibly a native-level
fault -- confirmed locally: birth_date=9999-01-01 raises an uncaught
swisseph.Error deep in the pyjhora call chain rather than a clean validation
error.

Both PersonalDataIn (exercised via /v1/chart) and FamilyMember (exercised
via /v1/muhurat/family-lagna-shuddhi) share the same BoundedBirthDate
constraint (app/schemas.py), so an out-of-range date is rejected as a 422 at
the schema boundary before it ever reaches the ephemeris.

THE BOUND IS THE MEASURED ONE, NOT THE ADVERTISED ONE
-----------------------------------------------------
Upstream describes the shipped files as covering "AD 1800-2400", and this
guard used to take that literally: a YEAR bound of 1800..2400, which accepts
every date through 2400-12-31. The files do not go that far. Measured with
``bphs_core.utils.probe_ephemeris_source`` (the engine's own canonical
Swiss-vs-Moshier detector) at one-day steps, the last day the seven visible
grahas answer from ``sepl_18.se1``/``semo_18.se1`` is **2400-01-10**; on
2400-01-11 every one of them silently becomes Moshier.

Silently is the whole problem. swisseph substitutes its built-in analytical
ephemeris when the data runs out and still returns a full, plausible result,
so the tail did not error — it answered. Measured end-to-end on /v1/chart
before this bound was tightened, spying on every ``swe.calc_ut`` a served
request makes:

    2400-01-10  ->  HTTP 200, 15/15 calls on Swiss data
    2400-01-11  ->  HTTP 200, 12/15 calls on MOSHIER
    2400-06-01  ->  HTTP 200, 15/15 calls on MOSHIER
    2400-12-31  ->  HTTP 200, 15/15 calls on MOSHIER

355 days of advertised range answering on the fallback engine, at 200, with
nothing in the response saying so.

WHY THE BOUND KEEPS A DAY OF MARGIN AT EACH END
-----------------------------------------------
``timezone_offset_hours`` is bounded [-12, +14], so the UTC instant for a
given local DATE ranges from (D-1 10:00 UTC, at tz=+14 local 00:00) to
(D+1 11:59:59 UTC, at tz=-12 local 23:59:59). A date-only bound set exactly
at the file boundary therefore still admits legal requests that land past it
-- measured, 2400-01-10 23:59:59 at tz=-12 was 12/15 Moshier, and the OLD
lower bound was already leaking the same way (1800-01-01 00:00:00 at tz=+14
was 12/15 Moshier before this change). The bound is pulled in one day at each
end so that EVERY admissible (birth_time, timezone_offset_hours) combination
inside it is Swiss-backed. ``test_every_admissible_instant_at_the_bounds_is_
swiss_backed`` re-measures that property rather than restating the constants.
"""
import datetime
import os
import threading

import pytest
import swisseph as swe
from fastapi.testclient import TestClient

os.environ.setdefault("CALC_SERVICE_TOKEN", "test")
os.environ.setdefault("PUBLIC_SOURCE_URL", "https://example.com")

from app.main import app
from app.schemas import MAX_EPHEMERIS_DATE, MIN_EPHEMERIS_DATE
from bphs_core import utils
from tests.conftest import SAMPLE_A, SAMPLE_B

_ONE_DAY = datetime.timedelta(days=1)

# Every corner of the admissible (birth_time, timezone_offset_hours) box, plus
# an interior point. The first and fourth entries are the extremes: they push
# the UTC instant a full day earlier and later than the local date.
_INSTANT_CORNERS = (
    ("00:00:00", 14.0),    # earliest UTC instant for the date
    ("00:00:00", -12.0),
    ("23:59:59", 14.0),
    ("23:59:59", -12.0),   # latest UTC instant for the date
    ("12:00:00", 5.5),
)

client = TestClient(app, headers={"X-Calc-Service-Token": "test"})

_FAMILY_BASE = {
    "start_date": "2026-05-26",
    "end_date": "2026-05-27",
    "activity_category": "generic",
    "step_seconds": 60,
}


class TestPersonalDataInBirthYearRange:
    def test_year_9999_is_422(self):
        r = client.post("/v1/chart", json={**SAMPLE_A, "birth_date": "9999-01-01"})
        assert r.status_code == 422

    def test_year_1_is_422(self):
        r = client.post("/v1/chart", json={**SAMPLE_A, "birth_date": "0001-01-01"})
        assert r.status_code == 422

    def test_day_just_below_min_is_422(self):
        r = client.post(
            "/v1/chart",
            json={**SAMPLE_A, "birth_date": (MIN_EPHEMERIS_DATE - _ONE_DAY).isoformat()},
        )
        assert r.status_code == 422

    def test_day_just_above_max_is_422(self):
        r = client.post(
            "/v1/chart",
            json={**SAMPLE_A, "birth_date": (MAX_EPHEMERIS_DATE + _ONE_DAY).isoformat()},
        )
        assert r.status_code == 422

    def test_day_at_min_boundary_is_accepted(self):
        r = client.post(
            "/v1/chart", json={**SAMPLE_A, "birth_date": MIN_EPHEMERIS_DATE.isoformat()}
        )
        assert r.status_code != 422, r.text

    def test_day_at_max_boundary_is_accepted(self):
        r = client.post(
            "/v1/chart", json={**SAMPLE_A, "birth_date": MAX_EPHEMERIS_DATE.isoformat()}
        )
        assert r.status_code != 422, r.text

    @pytest.mark.parametrize(
        "birth_date", ["2400-01-11", "2400-02-01", "2400-06-01", "2400-12-31"]
    )
    def test_the_silently_moshier_tail_is_rejected(self, birth_date):
        """The regression this bound exists for.

        Every one of these dates was inside the advertised range and returned
        HTTP 200 computed wholly or mostly on the Moshier fallback. They are
        not errors to the caller and never were — which is exactly why the
        schema, not the engine, has to refuse them.
        """
        r = client.post("/v1/chart", json={**SAMPLE_A, "birth_date": birth_date})
        assert r.status_code == 422, (
            f"birth_date={birth_date} was accepted. It is past the last day the "
            f"shipped Swiss files answer ({MAX_EPHEMERIS_DATE.isoformat()} + the "
            "timezone margin), so the answer would come from the Moshier fallback "
            f"with nothing telling the caller. Got {r.status_code}: {r.text[:200]}"
        )

    def test_the_advertised_bound_names_dates_not_years(self):
        """The 422 body must tell the caller the real range.

        A year-granular message ("between 1800 and 2400") is what sent callers
        into the tail in the first place: it advertises 2400-12-31.
        """
        r = client.post("/v1/chart", json={**SAMPLE_A, "birth_date": "2400-06-01"})
        assert r.status_code == 422
        assert MAX_EPHEMERIS_DATE.isoformat() in r.text, (
            f"the validation error does not name the real upper bound. Got: {r.text[:400]}"
        )
        assert MIN_EPHEMERIS_DATE.isoformat() in r.text

    def test_ordinary_year_within_range_returns_200(self):
        # Positive control: the existing golden-value sample must be unaffected.
        r = client.post("/v1/chart", json=SAMPLE_A)
        assert r.status_code == 200


class TestFamilyMemberBirthYearRange:
    def _family_req(self, member_overrides: dict) -> dict:
        return {
            **_FAMILY_BASE,
            "members": [{**SAMPLE_A, **member_overrides}, SAMPLE_B],
        }

    def test_year_9999_is_422(self):
        r = client.post(
            "/v1/muhurat/family-lagna-shuddhi",
            json=self._family_req({"birth_date": "9999-01-01"}),
        )
        assert r.status_code == 422

    def test_year_1_is_422(self):
        r = client.post(
            "/v1/muhurat/family-lagna-shuddhi",
            json=self._family_req({"birth_date": "0001-01-01"}),
        )
        assert r.status_code == 422

    def test_ordinary_year_within_range_returns_200(self):
        r = client.post(
            "/v1/muhurat/family-lagna-shuddhi",
            json={**_FAMILY_BASE, "members": [SAMPLE_A, SAMPLE_B]},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# The bound, RE-MEASURED — not restated
# ---------------------------------------------------------------------------
#
# Asserting `MAX_EPHEMERIS_DATE == date(2400, 1, 9)` would pin the constant to
# itself and pass for any value someone typed. These two tests ask the ephemeris
# instead: the first that everything inside the bound really is Swiss-backed, the
# second that the bound is TIGHT — that the data genuinely stops just past it,
# so a future "fix" that simply narrows the range to 1900 does not pass.
#
# Both need the real data files, so both take the `swiss_ephemeris` fixture and
# skip on the Moshier CI job (where every answer is Moshier by construction and
# the question is meaningless). The schema-behaviour tests above run on both.


def _moshier_calls_during(request_body: dict, route: str = "/v1/chart") -> tuple[int, int]:
    """(moshier_calls, total_calls) for every swe.calc_ut a served request makes.

    Spies on the module attribute, which is what `bphs_core.utils` and pyjhora
    both resolve at call time, so this observes the real served path rather than
    re-deriving what it ought to have asked for. Counting is thread-safe because
    TestClient dispatches through a threadpool.
    """
    records: list[int] = []
    lock = threading.Lock()
    real_calc_ut = swe.calc_ut

    def spy(jd, body, flags, *args, **kwargs):
        values, retflag = real_calc_ut(jd, body, flags, *args, **kwargs)
        with lock:
            records.append(retflag)
        return values, retflag

    swe.calc_ut = spy
    try:
        response = client.post(route, json=request_body)
    finally:
        swe.calc_ut = real_calc_ut

    assert response.status_code == 200, (
        f"the probe request itself failed: {response.status_code} {response.text[:300]}"
    )
    with lock:
        flags = list(records)
    assert flags, "no swe.calc_ut calls were observed — the spy did not take effect"
    return sum(1 for f in flags if f & swe.FLG_MOSEPH), len(flags)


def test_every_admissible_instant_at_the_bounds_is_swiss_backed(swiss_ephemeris: int) -> None:
    """No legal request inside the advertised range may answer on the fallback.

    This is the property the old year bound violated: it advertised through
    2400-12-31 while the files stop on 2400-01-10, so a caller in the tail got a
    200 computed on Moshier. Sweeping both bounds across every corner of the
    (birth_time, timezone_offset_hours) box is what makes the one-day margin
    load-bearing rather than superstition — the tz=-12 late-evening corner at the
    upper bound and the tz=+14 midnight corner at the lower bound are precisely
    the two that leaked before.
    """
    failures: list[str] = []
    for bound in (MIN_EPHEMERIS_DATE, MAX_EPHEMERIS_DATE):
        for birth_time, offset in _INSTANT_CORNERS:
            moshier, total = _moshier_calls_during({
                **SAMPLE_A,
                "birth_date": bound.isoformat(),
                "birth_time": birth_time,
                "timezone_offset_hours": offset,
            })
            if moshier:
                failures.append(
                    f"{bound.isoformat()} {birth_time} tz={offset:+g}: "
                    f"{moshier}/{total} swe.calc_ut calls answered on MOSHIER"
                )

    assert not failures, (
        "an admissible request inside the advertised birth-date range was computed "
        "on the Moshier fallback:\n"
        + "\n".join(f"  - {failure}" for failure in failures)
        + "\n\nEither the bound is too wide for the shipped data files, or the "
        "timezone margin is too thin. Re-measure before widening anything."
    )


@pytest.mark.parametrize("route", ["/v1/strength", "/v1/compat"])
def test_every_admissible_instant_at_the_bounds_is_swiss_backed_on_the_strength_routes(
    swiss_ephemeris: int, route: str
) -> None:
    """The strength limb reads past the instant it names, and still answers on Swiss data.

    ``/v1/strength``, and the Bhavabala note of ``/v1/compat``, read the
    sunrises and the sunset around the birth (``bphs_core/strength.py``): from
    two days before it to the first sunrise after it. At the last admissible
    instant, 2400-01-09 23:59:59 at tz -12 (2400-01-10 11:59:59 UT), that
    sunrise lies past the shipped files, so that one search answers from the
    fallback, and swisseph KEEPS the fallback (``utils.restore_ephemeris_state``).
    Before each search re-applied the ephemeris state, /v1/strength answered
    that request 200 with 40 of its 55 ``swe.calc_ut`` calls on Moshier, all at
    a Julian Day the files cover (the five war latitudes, eight times), and
    /v1/compat 5 of 40.
    """
    failures: list[str] = []
    for bound in (MIN_EPHEMERIS_DATE, MAX_EPHEMERIS_DATE):
        for birth_time, offset in _INSTANT_CORNERS:
            person = {
                **SAMPLE_A,
                "birth_date": bound.isoformat(),
                "birth_time": birth_time,
                "timezone_offset_hours": offset,
            }
            body = person if route == "/v1/strength" else {
                "person_a": person, "person_b": SAMPLE_B,
            }
            moshier, total = _moshier_calls_during(body, route)
            if moshier:
                failures.append(
                    f"{bound.isoformat()} {birth_time} tz={offset:+g}: "
                    f"{moshier}/{total} swe.calc_ut calls answered on MOSHIER"
                )

    assert not failures, (
        f"an admissible {route} request was computed on the Moshier fallback:\n"
        + "\n".join(f"  - {failure}" for failure in failures)
        + "\n\nA search outside the birth instant left swisseph on its fallback."
    )


def test_the_strength_day_frame_leaves_the_thread_on_swiss_data(swiss_ephemeris: int) -> None:
    """After the strength inputs of the last admissible instant, the next
    lookup on the same thread still reads the files.

    The search for the sunrise after a birth at 2400-01-10 11:59:59 UT reads
    past the shipped data. Without the state re-applied, the thread stayed on
    the fallback: the next chart computed on it, for 2400-01-07, took 12 of its
    15 reads from Moshier.
    """
    from bphs_core import strength
    from bphs_core.chart import Chart, PersonalData

    snapshot = Chart(PersonalData(
        "corner", datetime.datetime(2400, 1, 9), datetime.time(23, 59, 59),
        "Sample City", 7.0, 80.0, -12.0,
    )).snapshot()
    try:
        strength.strength_inputs(snapshot)
        swiss_active, retflag = utils.probe_ephemeris_source(
            swe.julday(2400, 1, 7, 12.0), swe.MOON
        )
    finally:
        # Hygiene for the tests after this one when the property does NOT hold;
        # the probe above has already been read.
        utils.restore_ephemeris_state()
    assert swiss_active, (
        f"after strength_inputs, a Moon lookup at 2400-01-07 answered from "
        f"MOSHIER (retflag {retflag}): the day-frame search left the thread on "
        "the fallback"
    )


def test_the_shipped_data_really_stops_just_past_the_bound(swiss_ephemeris: int) -> None:
    """The bound is TIGHT, not merely safe.

    Without this, narrowing the range to any small interval would satisfy the
    test above, and the service would refuse dates it can actually serve. Asks
    `utils.probe_ephemeris_source` — the same detector /healthz and the accuracy
    gate use — for the Sun, one of the seven grahas that share sepl_18.se1.

    The two days named here bracket the measured file boundary: 2400-01-10 is the
    last day Swiss data answers and 2400-01-11 is the first day it does not. The
    bound above sits one day earlier to absorb the timezone span.
    """
    last_swiss = datetime.date(2400, 1, 10)
    assert MAX_EPHEMERIS_DATE < last_swiss, (
        f"MAX_EPHEMERIS_DATE ({MAX_EPHEMERIS_DATE}) must leave at least a day of "
        f"margin below the measured file boundary ({last_swiss}), because a legal "
        "tz=-12 request lands a day later in UTC than its local date"
    )

    active_on_boundary, _ = utils.probe_ephemeris_source(
        swe.julday(last_swiss.year, last_swiss.month, last_swiss.day, 12.0), swe.SUN
    )
    assert active_on_boundary, (
        f"{last_swiss} no longer answers from Swiss data. The shipped files "
        "changed; re-measure the boundary and move MAX_EPHEMERIS_DATE with it."
    )

    first_moshier = last_swiss + _ONE_DAY
    active_past_boundary, _ = utils.probe_ephemeris_source(
        swe.julday(first_moshier.year, first_moshier.month, first_moshier.day, 12.0),
        swe.SUN,
    )
    assert not active_past_boundary, (
        f"{first_moshier} now answers from Swiss data, so the shipped files reach "
        "further than when this bound was measured. MAX_EPHEMERIS_DATE is now "
        "needlessly narrow — re-measure and widen it deliberately."
    )
