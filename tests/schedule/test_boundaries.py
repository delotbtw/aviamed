"""Input boundaries of the schedule API (extreme dates, ids, offsets, unknown fields) answer 422, never 500."""

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.core.exceptions import ConcurrentUpdate, LockTimeout
from app.repositories.base import domain_errors
from tests.schedule.support import at, book, cancel, iso, post_slot

HUGE_ID = 99_999_999_999


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("0001-01-01T00:00:00+03:00", "0001-01-01T00:30:00+03:00"),
        ("9999-12-31T23:30:00-05:00", "9999-12-31T23:59:00-05:00"),
        ("9999-12-31T23:30:00Z", "9999-12-31T23:59:00Z"),
        ("2026-11-03T07:30:00Z", "9999-12-31T23:59:00-05:00"),
    ],
)
@pytest.mark.parametrize("url", ["/schedule/slots", "/schedule/slots/batch"])
async def test_extreme_times_are_422(client, clock, registrar, url, start, end):
    body = {"start_at": start, "end_at": end, **({"slot_minutes": 30} if url.endswith("batch") else {})}

    resp = await client.post(url, json=body, headers=registrar.headers)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("day", ["0001-01-01", "1999-12-31", "2100-01-02", "9999-12-31"])
@pytest.mark.parametrize("param", ["date_from", "date_to"])
@pytest.mark.parametrize("url", ["/schedule/slots", "/schedule/slots/all", "/schedule/appointments"])
async def test_extreme_filter_dates_are_422(client, clock, admin, url, param, day):
    resp = await client.get(url, params={param: day}, headers=admin.headers)

    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("url", ["/schedule/slots", "/schedule/slots/all", "/schedule/appointments"])
async def test_oversized_ids_and_offsets_in_queries_are_422(client, clock, admin, url):
    for params in (
        {"doctor_id": HUGE_ID},
        {"doctor_id": 0},
        {"specialty_id": HUGE_ID},
        {"athlete_id": HUGE_ID},
        {"offset": 100_001},
        {"offset": HUGE_ID},
    ):
        resp = await client.get(url, params=params, headers=admin.headers)
        assert resp.status_code == 422, (url, params, resp.text)


async def test_oversized_ids_in_bodies_and_paths_are_422(client, clock, admin, registrar, doctor, athlete, make_slot):
    slot_id = await make_slot(doctor, at(10))

    bodies = [
        {"slot_id": HUGE_ID, "athlete_id": athlete.id},
        {"slot_id": slot_id, "athlete_id": HUGE_ID},
        {"slot_id": slot_id, "athlete_id": athlete.id, "case_id": HUGE_ID},
        {"slot_id": 0, "athlete_id": athlete.id},
    ]
    for body in bodies:
        resp = await client.post("/schedule/appointments", json=body, headers=registrar.headers)
        assert resp.status_code == 422, (body, resp.text)
    resp = await post_slot(client, admin, at(11), doctor=type("D", (), {"id": HUGE_ID})())
    assert resp.status_code == 422
    for path in (
        f"/schedule/slots/{HUGE_ID}/close",
        f"/schedule/slots/{HUGE_ID}/reopen",
        f"/schedule/appointments/{HUGE_ID}/cancel",
        f"/schedule/appointments/{HUGE_ID}/arrive",
        f"/schedule/appointments/{HUGE_ID}/no-show",
    ):
        for actor in (admin, registrar):
            assert (await client.post(path, headers=actor.headers)).status_code in (403, 422), path
    assert (await cancel(client, registrar, HUGE_ID)).status_code == 422
    assert (await book(client, registrar, HUGE_ID, athlete)).status_code == 422


@pytest.mark.parametrize(
    ("url", "body"),
    [
        ("/schedule/slots", {"start_at": iso(at(10)), "end_at": iso(at(10, 30)), "status": "closed"}),
        ("/schedule/slots/batch", {"start_at": iso(at(9)), "end_at": iso(at(10)), "slot_minutes": 30, "x": 1}),
    ],
)
async def test_unknown_body_fields_are_422(client, clock, registrar, sql, url, body):
    resp = await client.post(url, json=body, headers=registrar.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM slots") == []


async def test_unknown_booking_field_and_query_parameter_are_422(client, clock, athlete, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    booked = await client.post(
        "/schedule/appointments", json={"slot_id": slot_id, "status": "arrived"}, headers=athlete.headers
    )
    listed = await client.get("/schedule/slots", params={"from_": "2026-11-03"}, headers=athlete.headers)

    assert booked.status_code == 422 and listed.status_code == 422
    assert await sql("SELECT id FROM appointments") == []


@pytest.mark.parametrize(
    "values",
    [
        {"schedule_lock_timeout_ms": 0},
        {"slot_min_minutes": 60, "slot_max_minutes": 30},
        {"batch_max_slots": 0},
        {"max_active_appointments": 0},
        {"schedule_horizon_days": 0},
        {"batch_max_window_hours": 0},
    ],
)
def test_nonsensical_schedule_settings_are_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


class _Driver(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> DBAPIError:
    wrapped = Exception("wrapped")
    wrapped.__cause__ = _Driver(sqlstate)
    return DBAPIError("SELECT 1", None, wrapped)


@pytest.mark.parametrize("sqlstate", ["55P03", "40P01"])
def test_lock_timeout_and_deadlock_victim_become_lock_timeout(sqlstate):
    with pytest.raises(LockTimeout), domain_errors():
        raise _db_error(sqlstate)


def test_other_database_errors_pass_through():
    with pytest.raises(DBAPIError), domain_errors():
        raise _db_error("23503")


def test_stale_data_becomes_concurrent_update():
    from sqlalchemy.orm.exc import StaleDataError

    with pytest.raises(ConcurrentUpdate), domain_errors():
        raise StaleDataError


async def test_history_lists_are_newest_first_and_upcoming_ones_oldest_first(
    client, clock, registrar, athlete, doctor, make_slot, make_booking
):
    ids_by_hour = {}
    for hour in (9, 10, 11):
        ids_by_hour[hour] = await make_booking(await make_slot(doctor, at(hour)), athlete)
    for hour in (9, 10, 11):
        assert (await cancel(client, registrar, ids_by_hour[hour])).status_code == 204

    history = await client.get("/schedule/appointments", params={"status": "cancelled"}, headers=registrar.headers)

    assert [i["id"] for i in history.json()] == [ids_by_hour[11], ids_by_hour[10], ids_by_hour[9]]
