"""Spec section 6, block L: GET /schedule/slots (free slots) and GET /schedule/slots/all (management list)."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import event

from app.core.rbac import Role
from tests.schedule.support import HORIZON_DAYS, NOW, at, book, cancel, ids, msk

URL = "/schedule/slots"
ALL_URL = "/schedule/slots/all"
ITEM_KEYS = {"id", "doctor_id", "doctor_name", "specialty", "cabinet", "start_at", "end_at", "status"}


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.ADMIN, 200), (Role.REGISTRAR, 200), (Role.DOCTOR, 200), (Role.ATHLETE, 200), (Role.COACH, 403)],
)
async def test_L1_access_by_role(client, clock, users_by_role, role, expected):
    resp = await client.get(URL, headers=users_by_role[role].headers)

    assert resp.status_code == expected


async def test_L1_without_token_is_401(client, clock):
    assert (await client.get(URL)).status_code == 401


async def test_L2_only_free_future_slots_inside_the_horizon_of_active_doctors(
    client, clock, athlete, doctor, doctor2, make_user, make_slot, make_booking
):
    inactive = await make_user(Role.DOCTOR, is_active=False)
    visible = await make_slot(doctor, at(10))
    on_horizon = await make_slot(doctor, NOW + timedelta(days=HORIZON_DAYS))
    booked = await make_slot(doctor, at(11))
    await make_booking(booked, athlete)
    await make_slot(doctor, at(12), status="closed")
    await make_slot(doctor, NOW, minutes=30)  # starts exactly now
    await make_slot(doctor, NOW - timedelta(hours=2))  # already past
    await make_slot(doctor, NOW + timedelta(days=HORIZON_DAYS, minutes=1))  # one minute too far
    await make_slot(inactive, at(10))  # doctor deactivated

    resp = await client.get(URL, headers=athlete.headers)

    assert resp.status_code == 200
    assert set(ids(resp)) == {visible, on_horizon}
    assert {item["status"] for item in resp.json()} == {"free"}


async def test_L3_filters_work_alone_and_combined(
    client, clock, athlete, doctor, doctor2, specialty, second_specialty, make_slot
):
    a1 = await make_slot(doctor, at(10))  # doctor, specialty 1, 03.11
    a2 = await make_slot(doctor, at(10, days=3))  # 05.11
    b1 = await make_slot(doctor2, at(10))  # doctor2, specialty 2, 03.11
    b2 = await make_slot(doctor2, at(10, days=3))  # 05.11
    h = athlete.headers

    async def query(**params):
        return set(ids(await client.get(URL, params=params, headers=h)))

    assert await query(doctor_id=doctor.id) == {a1, a2}
    assert await query(specialty_id=second_specialty) == {b1, b2}
    assert await query(date_from="2026-11-04") == {a2, b2}
    assert await query(date_to="2026-11-03") == {a1, b1}
    assert await query(date_from="2026-11-03", date_to="2026-11-03") == {a1, b1}
    assert await query(doctor_id=doctor.id, date_from="2026-11-04") == {a2}
    assert await query(doctor_id=doctor.id, specialty_id=second_specialty) == set()
    assert await query(doctor_id=doctor2.id, specialty_id=second_specialty, date_to="2026-11-03") == {b1}


async def test_L3_date_filters_are_moscow_calendar_days(client, clock, athlete, doctor, make_slot):
    early = await make_slot(doctor, msk(2026, 11, 3, 1, 0))  # 22:00 UTC on 02.11, still 03.11 in Moscow
    late = await make_slot(doctor, msk(2026, 11, 3, 23, 30))  # 20:30 UTC
    next_day = await make_slot(doctor, msk(2026, 11, 4, 0, 0))  # 21:00 UTC on 03.11, already 04.11 in Moscow

    on_third = await client.get(
        URL, params={"date_from": "2026-11-03", "date_to": "2026-11-03"}, headers=athlete.headers
    )
    on_fourth = await client.get(
        URL, params={"date_from": "2026-11-04", "date_to": "2026-11-04"}, headers=athlete.headers
    )

    assert set(ids(on_third)) == {early, late}
    assert ids(on_fourth) == [next_day]


async def test_L3_default_date_from_is_today_in_moscow(client, clock, athlete, doctor, make_slot):
    later_today = await make_slot(doctor, msk(2026, 11, 2, 23, 30), minutes=10)
    clock.set(msk(2026, 11, 2, 23, 40))
    await make_slot(doctor, msk(2026, 11, 2, 23, 45), minutes=10)  # still today, in the future

    resp = await client.get(URL, headers=athlete.headers)

    assert resp.status_code == 200
    assert later_today not in ids(resp)  # it has already started at 23:40
    assert len(ids(resp)) == 1


async def test_L4_date_from_after_date_to_is_422(client, clock, athlete):
    resp = await client.get(URL, params={"date_from": "2026-11-05", "date_to": "2026-11-04"}, headers=athlete.headers)

    assert resp.status_code == 422


async def test_L4_unknown_doctor_or_specialty_gives_an_empty_list(client, clock, athlete, doctor, make_slot):
    await make_slot(doctor, at(10))

    for params in ({"doctor_id": 99999}, {"specialty_id": 99999}):
        resp = await client.get(URL, params=params, headers=athlete.headers)
        assert resp.status_code == 200 and resp.json() == []


async def test_L4_date_to_beyond_the_horizon_is_cut_silently(client, clock, athlete, doctor, make_slot):
    inside = await make_slot(doctor, at(10, days=59))
    await make_slot(doctor, at(10, days=61))

    resp = await client.get(URL, params={"date_to": "2030-01-01"}, headers=athlete.headers)

    assert resp.status_code == 200 and ids(resp) == [inside]


async def test_L5_order_and_pagination_do_not_overlap(client, clock, athlete, doctor, doctor2, make_slot):
    created = []
    for hour in (12, 9, 11, 10):  # inserted out of order
        created.append(await make_slot(doctor, at(hour)))
    created.append(await make_slot(doctor2, at(9)))  # same start_at as one slot of `doctor`: ties go by id
    created.append(await make_slot(doctor2, at(13)))

    full = await client.get(URL, headers=athlete.headers)
    starts = [(i["start_at"], i["id"]) for i in full.json()]
    assert starts == sorted(starts) and set(ids(full)) == set(created)

    pages = []
    for offset in (0, 2, 4, 6):
        page = await client.get(URL, params={"limit": 2, "offset": offset}, headers=athlete.headers)
        assert page.status_code == 200
        pages.append(ids(page))
    flat = [i for page in pages for i in page]
    assert flat == ids(full) and pages[3] == [] and len(set(flat)) == len(flat)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_L5_invalid_paging_is_422(client, clock, athlete, params):
    assert (await client.get(URL, params=params, headers=athlete.headers)).status_code == 422


async def test_L5_limit_200_is_accepted_and_default_is_50(client, clock, athlete, doctor, sql):
    await sql(
        "INSERT INTO slots (doctor_id, start_at, end_at, status) "
        "SELECT :d, t, t + interval '10 minutes', 'free' "
        "FROM (SELECT CAST(:s AS timestamptz) + g * interval '10 minutes' AS t FROM generate_series(0, 79) g) x",
        d=doctor.id,
        s=at(8),
    )

    default = await client.get(URL, headers=athlete.headers)
    maximum = await client.get(URL, params={"limit": 200}, headers=athlete.headers)

    assert len(default.json()) == 50 and len(maximum.json()) == 80


async def test_L6_response_carries_doctor_name_specialty_cabinet_and_no_private_data(
    client, clock, athlete, doctor2, make_slot
):
    slot_id = await make_slot(doctor2, at(10, 30))

    resp = await client.get(URL, headers=athlete.headers)

    [item] = resp.json()
    assert set(item) == ITEM_KEYS
    assert item["id"] == slot_id and item["doctor_id"] == doctor2.id
    assert item["doctor_name"] == "Кузнецов Пётр Иванович"
    assert item["specialty"] == "Кардиология" and item["cabinet"] == "305"
    for secret in (doctor2.email, "+79990000000", "password_hash", "argon2"):
        assert secret not in resp.text


async def test_L6_doctor_without_cabinet_gives_null(client, clock, athlete, doctor, make_slot):
    await make_slot(doctor, at(10))

    [item] = (await client.get(URL, headers=athlete.headers)).json()

    assert item["cabinet"] is None and item["specialty"] == "Спортивная медицина"


@pytest.mark.no_schedule_invariants  # bulk-loaded synthetic slots: no appointments or histories behind the booked ones
async def test_L7_free_slot_query_uses_the_partial_index_on_50000_slots(
    client, clock, athlete, make_user, sql, db_engine
):
    from app.core.db import get_database

    doctors = [await make_user(Role.DOCTOR) for _ in range(20)]
    await sql(
        "INSERT INTO slots (doctor_id, start_at, end_at, status) "
        "SELECT d.id, t, t + interval '10 minutes', CASE WHEN (day + n) % 10 < 3 THEN 'free' ELSE 'booked' END "
        "FROM unnest(CAST(:ids AS int[])) AS d(id), generate_series(0, 59) day, generate_series(0, 41) n, "
        "LATERAL (SELECT CAST(:s AS timestamptz) + day * interval '1 day' + n * interval '10 minutes' AS t) x",
        ids=[d.id for d in doctors],
        s=at(8, days=1),
    )
    await sql("ANALYZE slots")
    assert (await sql("SELECT count(*) AS n FROM slots"))[0]["n"] == 50400

    captured: list[tuple[str, tuple]] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM slots" in statement and statement.lstrip().upper().startswith("SELECT"):
            captured.append((statement, parameters))

    sync_engine = get_database().engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        resp = await client.get(URL, params={"doctor_id": doctors[0].id}, headers=athlete.headers)
        assert resp.status_code == 200
        unfiltered = await client.get(URL, headers=athlete.headers)
        assert unfiltered.status_code == 200 and len(unfiltered.json()) == 50
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)

    assert captured, "the list endpoint must read slots with a SELECT"
    statement, parameters = captured[-1]  # the unfiltered query, the heaviest one
    async with db_engine.connect() as conn:
        result = await conn.exec_driver_sql("EXPLAIN (FORMAT JSON) " + statement, parameters)
        plan = result.scalar()
    plan = plan if isinstance(plan, list) else json.loads(plan)
    text = json.dumps(plan)
    assert "slots" not in _seq_scans(plan), text
    assert "ix_slots_free_start_at" in text, text


def _seq_scans(plan) -> list[str]:
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("Node Type") == "Seq Scan":
                found.append(node.get("Relation Name"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(plan)
    return found


async def test_L8_slot_leaves_the_list_when_booked_and_returns_when_cancelled(
    client, clock, athlete, doctor, make_slot
):
    slot_id = await make_slot(doctor, at(10))
    assert ids(await client.get(URL, headers=athlete.headers)) == [slot_id]

    booked = await book(client, athlete, slot_id)
    assert booked.status_code == 201, booked.text
    assert ids(await client.get(URL, headers=athlete.headers)) == []

    assert (await cancel(client, athlete, booked.json()["id"])).status_code == 204
    assert ids(await client.get(URL, headers=athlete.headers)) == [slot_id]


# --------------------------------------------------------------------------- management list


async def test_L9_doctor_sees_own_slots_of_any_status_with_the_athlete_name(
    client, clock, doctor, doctor2, athlete, make_slot, make_booking
):
    free = await make_slot(doctor, at(10))
    taken = await make_slot(doctor, at(11))
    appointment_id = await make_booking(taken, athlete)
    closed = await make_slot(doctor, at(12), status="closed")
    past = await make_slot(doctor, NOW - timedelta(days=3))
    foreign = await make_slot(doctor2, at(10))

    resp = await client.get(ALL_URL, headers=doctor.headers)

    assert resp.status_code == 200, resp.text
    by_id = {i["id"]: i for i in resp.json()}
    assert set(by_id) == {free, taken, closed, past} and foreign not in by_id
    assert by_id[taken]["status"] == "booked"
    assert by_id[taken]["appointment"] == {
        "id": appointment_id,
        "status": "booked",
        "athlete_name": "Иванов Иван Иванович",
    }
    assert by_id[free]["appointment"] is None
    assert by_id[past]["status"] == "free" and by_id[closed]["status"] == "closed"
    assert ITEM_KEYS <= set(by_id[free])
    assert athlete.email not in resp.text and "+79990000000" not in resp.text


async def test_L9_doctor_asking_for_another_doctor_is_403(client, clock, doctor, doctor2):
    resp = await client.get(ALL_URL, params={"doctor_id": doctor2.id}, headers=doctor.headers)

    assert resp.status_code == 403


async def test_L9_doctor_may_filter_by_own_id(client, clock, doctor, make_slot):
    slot_id = await make_slot(doctor, at(10))

    resp = await client.get(ALL_URL, params={"doctor_id": doctor.id}, headers=doctor.headers)

    assert resp.status_code == 200 and ids(resp) == [slot_id]


async def test_L10_admin_sees_all_and_filters(client, clock, admin, doctor, doctor2, athlete, make_slot, make_booking):
    a = await make_slot(doctor, at(10))
    b = await make_slot(doctor, at(11))
    await make_booking(b, athlete)
    c = await make_slot(doctor2, at(10, days=3), status="closed")
    past = await make_slot(doctor2, NOW - timedelta(days=2))

    async def query(**params):
        resp = await client.get(ALL_URL, params=params, headers=admin.headers)
        assert resp.status_code == 200, resp.text
        return set(ids(resp))

    assert await query() == {a, b, c, past}
    assert await query(doctor_id=doctor2.id) == {c, past}
    assert await query(status="booked") == {b}
    assert await query(status="closed") == {c}
    assert await query(status="free") == {a, past}
    assert await query(date_from="2026-11-04") == {c}
    assert await query(date_to="2026-11-03") == {a, b, past}
    assert await query(doctor_id=doctor.id, status="free", date_from="2026-11-03", date_to="2026-11-03") == {a}


async def test_L10_invalid_status_filter_is_422(client, clock, admin):
    assert (await client.get(ALL_URL, params={"status": "bogus"}, headers=admin.headers)).status_code == 422


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ATHLETE, Role.COACH])
async def test_L10_other_roles_are_forbidden(client, clock, users_by_role, role):
    assert (await client.get(ALL_URL, headers=users_by_role[role].headers)).status_code == 403


async def test_L10_without_token_is_401(client, clock):
    assert (await client.get(ALL_URL)).status_code == 401
