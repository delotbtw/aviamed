"""Spec section 6, block K: POST /schedule/slots/batch."""

from datetime import timedelta

import pytest

from app.core.rbac import Role
from tests.schedule.support import NOW, at, gather, iso, parse_dt, post_batch

URL = "/schedule/slots/batch"


async def test_K1_window_is_cut_into_consecutive_slots(client, clock, doctor, sql, audit):
    resp = await post_batch(client, doctor, at(9), at(12), 30)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body) == 6
    starts = [parse_dt(s["start_at"]) for s in body]
    assert starts == [at(9) + timedelta(minutes=30 * i) for i in range(6)]
    assert all(s["status"] == "free" and s["doctor_id"] == doctor.id for s in body)
    assert all(parse_dt(s["end_at"]) - parse_dt(s["start_at"]) == timedelta(minutes=30) for s in body)
    assert len(await sql("SELECT id FROM slots WHERE status = 'free'")) == 6
    rows = await audit("slot_create")
    assert len(rows) == 6 and {r["entity_id"] for r in rows} == {s["id"] for s in body}


async def test_K1_admin_creates_a_batch_for_a_doctor(client, clock, admin, doctor2, sql):
    resp = await post_batch(client, admin, at(9), at(10), 20, doctor=doctor2)

    assert resp.status_code == 201, resp.text
    assert len(await sql("SELECT id FROM slots WHERE doctor_id = :d", d=doctor2.id)) == 3


async def test_K2_window_not_divisible_by_slot_length_is_422(client, clock, doctor, sql):
    resp = await post_batch(client, doctor, at(9), at(11, 50), 30)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM slots") == []


@pytest.mark.parametrize(
    ("start", "end", "minutes", "expected"),
    [
        (at(8), at(8) + timedelta(minutes=500), 10, 201),  # exactly 50 slots
        (at(8), at(8) + timedelta(minutes=510), 10, 422),  # 51 slots
        (at(8), at(20), 240, 201),  # exactly 12 hours
        (at(8), at(20, 30), 30, 422),  # more than 12 hours (25 slots)
        (at(8), at(21), 60, 422),  # 13 hours
        (at(8), at(10), 9, 422),  # slot_minutes below the minimum
        (at(8), at(20), 241, 422),  # slot_minutes above the maximum
    ],
    ids=["50-slots", "51-slots", "12h", "12h30", "13h", "slot-9min", "slot-241min"],
)
async def test_K3_batch_size_limits(client, clock, doctor, start, end, minutes, expected):
    resp = await post_batch(client, doctor, start, end, minutes)

    assert resp.status_code == expected, resp.text


async def test_K4_one_conflicting_slot_rolls_back_the_whole_batch(client, clock, doctor, make_slot, sql, audit):
    existing = await make_slot(doctor, at(10, 30), minutes=30)

    resp = await post_batch(client, doctor, at(9), at(12), 30)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"].startswith("Slots overlap")
    assert "2026-11-03T07:30:00Z" in resp.json()["detail"]  # start_at of the first offending slot (10:30 Moscow)
    assert [r["id"] for r in await sql("SELECT id FROM slots")] == [existing]
    assert await audit("slot_create") == []


async def test_K4_overlap_with_a_closed_slot_also_rolls_back(client, clock, doctor, make_slot, sql):
    await make_slot(doctor, at(11), minutes=30, status="closed")

    resp = await post_batch(client, doctor, at(9), at(12), 30)

    assert resp.status_code == 409
    assert len(await sql("SELECT id FROM slots")) == 1


async def test_K5_batch_in_the_past_is_422(client, clock, doctor, sql):
    resp = await post_batch(client, doctor, NOW - timedelta(hours=3), NOW + timedelta(hours=3), 30)

    assert resp.status_code == 422, resp.text
    assert await sql("SELECT id FROM slots") == []  # the future half of the window is not created either


async def test_K5_batch_beyond_the_horizon_is_422(client, clock, doctor, sql):
    resp = await post_batch(client, doctor, at(9, days=61), at(10, days=61), 30)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM slots") == []


async def test_K5_naive_time_is_422(client, clock, doctor):
    body = {"start_at": "2026-11-03T09:00:00", "end_at": "2026-11-03T10:00:00", "slot_minutes": 30}

    resp = await client.post(URL, json=body, headers=doctor.headers)

    assert resp.status_code == 422


async def test_K5_doctor_cannot_create_a_batch_for_another_doctor(client, clock, doctor, doctor2, sql):
    resp = await post_batch(client, doctor, at(9), at(10), 30, doctor=doctor2)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM slots") == []


async def test_K5_admin_without_doctor_id_is_422(client, clock, admin):
    resp = await post_batch(client, admin, at(9), at(10), 30)

    assert resp.status_code == 422


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ATHLETE, Role.COACH])
async def test_K5_other_roles_are_forbidden(client, clock, users_by_role, doctor, sql, role):
    resp = await post_batch(client, users_by_role[role], at(9), at(10), 30, doctor=doctor)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM slots") == []


async def test_K5_without_token_is_401(client, clock):
    body = {"start_at": iso(at(9)), "end_at": iso(at(10)), "slot_minutes": 30}

    assert (await client.post(URL, json=body)).status_code == 401


async def test_K6_two_identical_parallel_batches_one_wins(client, clock, doctor, sql):
    resps = await gather(*(post_batch(client, doctor, at(9), at(12), 30) for _ in range(2)))

    assert sorted(r.status_code for r in resps) == [201, 409], [r.text for r in resps]
    assert len(await sql("SELECT id FROM slots")) == 6


async def test_K6_overlapping_parallel_batches_one_succeeds_entirely(client, clock, doctor, sql):
    resps = await gather(
        post_batch(client, doctor, at(9), at(12), 30),
        post_batch(client, doctor, at(10, 30), at(13, 30), 30),
    )

    assert sorted(r.status_code for r in resps) == [201, 409], [r.text for r in resps]
    assert len(await sql("SELECT id FROM slots")) == 6  # the loser left nothing behind
