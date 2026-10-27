"""Spec section 6, block J: POST /schedule/slots."""

from datetime import timedelta

import pytest

from app.core.rbac import Role
from tests.schedule.support import HORIZON_DAYS, NOW, assert_utc, at, iso, post_slot

URL = "/schedule/slots"


async def test_J1_doctor_creates_own_slot(client, clock, doctor, sql):
    start = at(10, 30)

    resp = await post_slot(client, doctor, start)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "free" and body["doctor_id"] == doctor.id
    assert_utc(body["start_at"], start)
    assert_utc(body["end_at"], start + timedelta(minutes=30))
    [row] = await sql("SELECT status, created_by, doctor_id, start_at FROM slots WHERE id = :i", i=body["id"])
    assert row["status"] == "free" and row["created_by"] == doctor.id and row["start_at"] == start


async def test_J1_doctor_may_name_himself_explicitly(client, clock, doctor):
    resp = await post_slot(client, doctor, at(10), doctor=doctor)

    assert resp.status_code == 201, resp.text


async def test_J2_admin_creates_slot_for_a_doctor(client, clock, admin, doctor2, sql):
    resp = await post_slot(client, admin, at(10), doctor=doctor2)

    assert resp.status_code == 201, resp.text
    [row] = await sql("SELECT doctor_id, created_by FROM slots")
    assert row == {"doctor_id": doctor2.id, "created_by": admin.id}


async def test_J2_admin_without_doctor_id_is_422(client, clock, admin, sql):
    resp = await post_slot(client, admin, at(10))

    assert resp.status_code == 422
    assert await sql("SELECT id FROM slots") == []


@pytest.mark.parametrize("target", ["registrar", "athlete", "coach", "inactive_doctor", "missing"])
async def test_J2_doctor_id_must_be_an_active_doctor(client, clock, admin, users_by_role, make_user, sql, target):
    if target == "inactive_doctor":
        doctor_id = (await make_user(Role.DOCTOR, is_active=False)).id
    elif target == "missing":
        doctor_id = 99999
    else:
        doctor_id = users_by_role[Role(target)].id
    body = {"doctor_id": doctor_id, "start_at": iso(at(10)), "end_at": iso(at(10, 30))}

    resp = await client.post(URL, json=body, headers=admin.headers)

    assert resp.status_code == 422, resp.text
    assert await sql("SELECT id FROM slots") == []


async def test_J3_doctor_cannot_create_slot_for_another_doctor(client, clock, doctor, doctor2, sql):
    resp = await post_slot(client, doctor, at(10), doctor=doctor2)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM slots") == []


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ATHLETE, Role.COACH])
async def test_J3_other_roles_are_forbidden(client, clock, users_by_role, doctor, sql, role):
    resp = await post_slot(client, users_by_role[role], at(10), doctor=doctor)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM slots") == []


async def test_J3_without_token_is_401(client, clock):
    resp = await client.post(URL, json={"start_at": iso(at(10)), "end_at": iso(at(10, 30))})

    assert resp.status_code == 401


@pytest.mark.parametrize("delta_min", [0, -30])
async def test_J4_end_not_after_start_is_422(client, clock, doctor, sql, delta_min):
    start = at(10)
    body = {"start_at": iso(start), "end_at": iso(start + timedelta(minutes=delta_min))}

    resp = await client.post(URL, json=body, headers=doctor.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM slots") == []


@pytest.mark.parametrize(("minutes", "expected"), [(9, 422), (10, 201), (240, 201), (241, 422), (1, 422), (600, 422)])
async def test_J4_duration_limits_are_inclusive(client, clock, doctor, minutes, expected):
    resp = await post_slot(client, doctor, at(10), minutes=minutes)

    assert resp.status_code == expected, resp.text


async def test_J5_start_equal_to_now_or_earlier_is_422(client, clock, doctor, sql):
    for start in (NOW, NOW - timedelta(minutes=1), NOW - timedelta(days=1)):
        resp = await post_slot(client, doctor, start)
        assert resp.status_code == 422, (start, resp.text)
    assert await sql("SELECT id FROM slots") == []


async def test_J5_one_minute_after_now_is_accepted(client, clock, doctor):
    resp = await post_slot(client, doctor, NOW + timedelta(minutes=1))

    assert resp.status_code == 201, resp.text


async def test_J5_horizon_boundary(client, clock, doctor):
    on_horizon = NOW + timedelta(days=HORIZON_DAYS)

    beyond = await post_slot(client, doctor, on_horizon + timedelta(minutes=1))
    exact = await post_slot(client, doctor, on_horizon)

    assert beyond.status_code == 422, beyond.text
    assert exact.status_code == 201, exact.text


async def test_J6_time_without_timezone_is_422(client, clock, doctor, sql):
    body = {"start_at": "2026-11-03T10:30:00", "end_at": "2026-11-03T11:00:00"}

    resp = await client.post(URL, json=body, headers=doctor.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM slots") == []


@pytest.mark.parametrize("start", ["2026-11-03T07:30:15Z", "2026-11-03T07:30:00.5Z", "2026-11-03T10:30:01+03:00"])
async def test_J6_nonzero_seconds_are_422(client, clock, doctor, sql, start):
    body = {"start_at": start, "end_at": "2026-11-03T08:30:00Z"}

    resp = await client.post(URL, json=body, headers=doctor.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM slots") == []


@pytest.mark.parametrize(
    ("start_h", "start_m", "minutes"),
    [(10, 15, 30), (10, 5, 20), (10, 0, 30), (10, 0, 20), (9, 45, 60), (9, 45, 30)],
    ids=["partial", "nested", "identical", "same-start", "containing", "overlaps-start"],
)
async def test_J7_overlapping_slot_of_the_same_doctor_is_409(
    client, clock, doctor, make_slot, sql, start_h, start_m, minutes
):
    await make_slot(doctor, at(10), minutes=30)  # 10:00-10:30

    resp = await post_slot(client, doctor, at(start_h, start_m), minutes=minutes)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"].startswith("Slots overlap")
    assert len(await sql("SELECT id FROM slots")) == 1


async def test_J7_duplicate_start_is_the_same_409(client, clock, doctor, make_slot):
    await make_slot(doctor, at(10), minutes=30)

    resp = await post_slot(client, doctor, at(10), minutes=45)

    assert resp.status_code == 409 and resp.json()["detail"].startswith("Slots overlap")


async def test_J7_other_doctor_at_the_same_time_is_fine(client, clock, admin, doctor, doctor2, make_slot):
    await make_slot(doctor, at(10), minutes=30)

    resp = await post_slot(client, admin, at(10), doctor=doctor2)

    assert resp.status_code == 201, resp.text


async def test_J8_touching_slots_are_both_accepted(client, clock, doctor, make_slot):
    await make_slot(doctor, at(10), minutes=30)

    after = await post_slot(client, doctor, at(10, 30))
    before = await post_slot(client, doctor, at(9, 30))

    assert after.status_code == 201 and before.status_code == 201, (after.text, before.text)


async def test_J9_overlap_with_a_closed_slot_is_409(client, clock, doctor, make_slot):
    await make_slot(doctor, at(10), minutes=30, status="closed")

    resp = await post_slot(client, doctor, at(10, 15))

    assert resp.status_code == 409 and resp.json()["detail"].startswith("Slots overlap")


async def test_Q2_offset_and_Z_forms_of_one_instant_are_stored_identically(client, clock, admin, doctor, doctor2, sql):
    plus3 = {"doctor_id": doctor.id, "start_at": "2026-11-03T10:30:00+03:00", "end_at": "2026-11-03T11:00:00+03:00"}
    zulu = {"doctor_id": doctor2.id, "start_at": "2026-11-03T07:30:00Z", "end_at": "2026-11-03T08:00:00Z"}

    first = await client.post(URL, json=plus3, headers=admin.headers)
    second = await client.post(URL, json=zulu, headers=admin.headers)

    assert first.status_code == second.status_code == 201, (first.text, second.text)
    for resp in (first, second):
        assert resp.json()["start_at"].endswith(("Z", "+00:00"))
        assert resp.json()["start_at"].startswith("2026-11-03T07:30:00")
    rows = await sql("SELECT to_char(start_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS s FROM slots")
    assert {r["s"] for r in rows} == {"2026-11-03 07:30:00"}
