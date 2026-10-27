"""Spec section 6, block P: closing and re-opening slots."""

from datetime import timedelta

import pytest

from app.core.rbac import Role
from tests.schedule.support import NOW, at, book, cancel, close_slot, ids, reopen_slot

SLOTS = "/schedule/slots"


async def test_P1_doctor_closes_own_free_slot(client, clock, doctor, athlete, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    resp = await close_slot(client, doctor, slot_id)

    assert resp.status_code == 204
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "closed"
    assert slot_id not in ids(await client.get(SLOTS, headers=athlete.headers))
    booking = await book(client, athlete, slot_id)
    assert booking.status_code == 409 and booking.json()["detail"] == "Slot is closed"


async def test_P2_booked_slot_cannot_be_closed_until_the_appointment_is_cancelled(
    client, clock, doctor, athlete, make_slot, make_booking, sql
):
    slot_id = await make_slot(doctor, at(10))
    appointment_id = await make_booking(slot_id, athlete)

    resp = await close_slot(client, doctor, slot_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot is booked"
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "booked"
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"

    assert (await cancel(client, athlete, appointment_id)).status_code == 204
    assert (await close_slot(client, doctor, slot_id)).status_code == 204
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "closed"


async def test_P3_closed_future_slot_can_be_reopened(client, clock, doctor, athlete, make_slot, sql):
    slot_id = await make_slot(doctor, at(10), status="closed")

    resp = await reopen_slot(client, doctor, slot_id)

    assert resp.status_code == 204
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "free"
    assert ids(await client.get(SLOTS, headers=athlete.headers)) == [slot_id]


async def test_P3_started_slot_cannot_be_reopened(client, clock, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, NOW - timedelta(hours=1), status="closed")

    resp = await reopen_slot(client, doctor, slot_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot has already started"
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "closed"


async def test_P3_slot_starting_exactly_now_cannot_be_reopened(client, clock, doctor, make_slot):
    slot_id = await make_slot(doctor, NOW, status="closed")

    assert (await reopen_slot(client, doctor, slot_id)).status_code == 409


async def test_P3_past_slot_may_be_closed(client, clock, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, NOW - timedelta(days=1))

    assert (await close_slot(client, doctor, slot_id)).status_code == 204
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "closed"


async def test_P4_closing_a_closed_slot_is_a_silent_204(client, clock, doctor, make_slot, audit, sql):
    slot_id = await make_slot(doctor, at(10))
    assert (await close_slot(client, doctor, slot_id)).status_code == 204

    again = await close_slot(client, doctor, slot_id)

    assert again.status_code == 204
    assert len(await audit("slot_close")) == 1
    assert len(await sql("SELECT id FROM status_history WHERE entity_type = 'slot'")) == 1


async def test_P4_reopening_a_free_slot_is_a_silent_204(client, clock, doctor, make_slot, audit, sql):
    slot_id = await make_slot(doctor, at(10))

    resp = await reopen_slot(client, doctor, slot_id)

    assert resp.status_code == 204
    assert await audit("slot_reopen") == []
    assert await sql("SELECT id FROM status_history") == []
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "free"


async def test_P4_reopening_a_booked_slot_changes_nothing(client, clock, doctor, athlete, make_slot, make_booking, sql):
    slot_id = await make_slot(doctor, at(10))
    await make_booking(slot_id, athlete)

    resp = await reopen_slot(client, doctor, slot_id)

    assert resp.status_code in (204, 409)  # the spec fixes only "free -> 204"; the booking must survive either way
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "booked"
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


@pytest.mark.parametrize("action", [close_slot, reopen_slot], ids=["close", "reopen"])
async def test_P5_doctor_cannot_touch_a_foreign_slot_and_gets_404(
    client, clock, doctor, doctor2, make_slot, sql, action
):
    slot_id = await make_slot(doctor2, at(10), status="free" if action is close_slot else "closed")
    before = await sql("SELECT status FROM slots")

    resp = await action(client, doctor, slot_id)

    assert resp.status_code == 404
    assert await sql("SELECT status FROM slots") == before


async def test_P5_admin_closes_and_reopens_any_slot(client, clock, admin, doctor2, make_slot, sql):
    slot_id = await make_slot(doctor2, at(10))

    assert (await close_slot(client, admin, slot_id)).status_code == 204
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "closed"
    assert (await reopen_slot(client, admin, slot_id)).status_code == 204
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "free"


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ATHLETE, Role.COACH])
@pytest.mark.parametrize("action", [close_slot, reopen_slot], ids=["close", "reopen"])
async def test_P5_other_roles_are_forbidden(client, clock, users_by_role, doctor, make_slot, sql, role, action):
    slot_id = await make_slot(doctor, at(10), status="free" if action is close_slot else "closed")
    before = await sql("SELECT status FROM slots")

    resp = await action(client, users_by_role[role], slot_id)

    assert resp.status_code == 403
    assert await sql("SELECT status FROM slots") == before


async def test_P5_without_token_is_401(client, clock):
    assert (await client.post("/schedule/slots/1/close")).status_code == 401
    assert (await client.post("/schedule/slots/1/reopen")).status_code == 401


@pytest.mark.parametrize("role", [Role.DOCTOR, Role.ADMIN])
async def test_P5_unknown_slot_is_404(client, clock, users_by_role, role):
    assert (await close_slot(client, users_by_role[role], 99999)).status_code == 404
    assert (await reopen_slot(client, users_by_role[role], 99999)).status_code == 404
