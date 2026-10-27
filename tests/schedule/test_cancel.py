"""Spec section 6, block N: POST /schedule/appointments/{id}/cancel and re-booking."""

from datetime import timedelta

import pytest

from app.core.rbac import Role
from tests.schedule.support import at, book, cancel, ids

SLOTS = "/schedule/slots"


async def test_N1_athlete_cancels_own_appointment_before_the_start(
    client, clock, athlete, doctor, make_slot, make_booking, sql
):
    slot_id = await make_slot(doctor, at(10))
    appointment_id = await make_booking(slot_id, athlete)
    clock.advance(hours=1)

    resp = await cancel(client, athlete, appointment_id)

    assert resp.status_code == 204 and resp.content == b""
    [row] = await sql("SELECT status, cancelled_at FROM appointments WHERE id = :i", i=appointment_id)
    assert row["status"] == "cancelled" and row["cancelled_at"] == clock.now()
    assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == "free"
    assert slot_id in ids(await client.get(SLOTS, headers=athlete.headers))


async def test_N2_same_athlete_books_the_slot_again(client, clock, athlete, doctor, make_slot, make_booking, sql):
    slot_id = await make_slot(doctor, at(10))
    first = await make_booking(slot_id, athlete)
    assert (await cancel(client, athlete, first)).status_code == 204

    again = await book(client, athlete, slot_id)

    assert again.status_code == 201, again.text
    second = again.json()["id"]
    assert second != first
    rows = {r["id"]: r["status"] for r in await sql("SELECT id, status FROM appointments")}
    assert rows == {first: "cancelled", second: "booked"}


async def test_N2_another_athlete_books_the_freed_slot(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking, sql
):
    slot_id = await make_slot(doctor, at(10))
    first = await make_booking(slot_id, athlete)
    assert (await cancel(client, athlete, first)).status_code == 204

    resp = await book(client, athlete2, slot_id)

    assert resp.status_code == 201, resp.text
    assert resp.json()["athlete_id"] == athlete2.id
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "booked"


async def test_N3_three_book_cancel_cycles_leave_one_active_appointment(client, clock, athlete, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    for _ in range(2):
        created = await book(client, athlete, slot_id)
        assert created.status_code == 201, created.text
        assert (await cancel(client, athlete, created.json()["id"])).status_code == 204
    last = await book(client, athlete, slot_id)

    assert last.status_code == 201
    rows = await sql("SELECT status, count(*) AS n FROM appointments GROUP BY status")
    assert {r["status"]: r["n"] for r in rows} == {"cancelled": 2, "booked": 1}


async def test_N4_athlete_cannot_cancel_a_foreign_appointment_and_gets_404(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking, sql
):
    slot_id = await make_slot(doctor, at(10))
    appointment_id = await make_booking(slot_id, athlete)

    resp = await cancel(client, athlete2, appointment_id)

    assert resp.status_code == 404
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "booked"
    assert await sql("SELECT id FROM audit_log WHERE action = 'appointment_cancel'") == []


async def test_N4_foreign_and_missing_appointments_are_indistinguishable_for_an_athlete(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)

    foreign = await cancel(client, athlete2, appointment_id)
    missing = await cancel(client, athlete2, 99999)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize("role", [Role.DOCTOR, Role.COACH])
async def test_N4_doctor_and_coach_are_forbidden(
    client, clock, users_by_role, athlete, doctor, make_slot, make_booking, sql, role
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)

    resp = await cancel(client, users_by_role[role], appointment_id)

    assert resp.status_code == 403
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


async def test_N4_without_token_is_401(client, clock):
    assert (await client.post("/schedule/appointments/1/cancel")).status_code == 401


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ADMIN])
async def test_N5_registrar_and_admin_cancel_any_booked_appointment(
    client, clock, users_by_role, athlete, doctor, make_slot, make_booking, sql, role
):
    slot_id = await make_slot(doctor, at(10))
    appointment_id = await make_booking(slot_id, athlete)

    resp = await cancel(client, users_by_role[role], appointment_id)

    assert resp.status_code == 204
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "cancelled"
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "free"


async def test_N5_athlete_cannot_cancel_once_the_slot_has_started(
    client, clock, athlete, doctor, make_slot, make_booking, sql
):
    slot_id = await make_slot(doctor, at(10), minutes=30)
    appointment_id = await make_booking(slot_id, athlete)
    clock.set(at(10))  # now == start_at: "now < start_at" is false

    resp = await cancel(client, athlete, appointment_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot has already started"
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


async def test_N5_one_minute_before_the_start_the_athlete_still_may(
    client, clock, athlete, doctor, make_slot, make_booking
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    clock.set(at(10) - timedelta(minutes=1))

    assert (await cancel(client, athlete, appointment_id)).status_code == 204


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ADMIN])
async def test_N5_staff_may_cancel_until_the_end_of_the_slot(
    client, clock, users_by_role, athlete, doctor, make_slot, make_booking, role
):
    appointment_id = await make_booking(await make_slot(doctor, at(10), minutes=30), athlete)
    clock.set(at(10, 29))  # started, not finished

    resp = await cancel(client, users_by_role[role], appointment_id)

    assert resp.status_code == 204


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ADMIN])
async def test_N5_staff_cannot_cancel_after_the_end(
    client, clock, users_by_role, athlete, doctor, make_slot, make_booking, sql, role
):
    appointment_id = await make_booking(await make_slot(doctor, at(10), minutes=30), athlete)
    clock.set(at(10, 30))  # now == end_at

    resp = await cancel(client, users_by_role[role], appointment_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot has already started"
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


async def test_N5_slot_freed_by_staff_during_the_slot_is_not_bookable(
    client, clock, registrar, athlete, athlete2, doctor, make_slot, make_booking, sql
):
    slot_id = await make_slot(doctor, at(10), minutes=30)
    appointment_id = await make_booking(slot_id, athlete)
    clock.set(at(10, 10))
    assert (await cancel(client, registrar, appointment_id)).status_code == 204

    resp = await book(client, athlete2, slot_id)

    assert (await sql("SELECT status FROM slots"))[0]["status"] == "free"
    assert resp.status_code == 409 and resp.json()["detail"] == "Slot has already started"
    assert slot_id not in ids(await client.get(SLOTS, headers=athlete2.headers))


@pytest.mark.parametrize("state", ["arrived", "done", "no_show"])
async def test_N6_cancelling_a_non_booked_appointment_is_409(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, force_status, sql, state
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    if state == "done":
        await force_status(appointment_id, "arrived")
    await force_status(appointment_id, state)

    for actor in (athlete, registrar):
        resp = await cancel(client, actor, appointment_id)
        assert resp.status_code == 409 and resp.json()["detail"] == "Invalid appointment status"

    assert (await sql("SELECT status, cancelled_at FROM appointments"))[0] == {"status": state, "cancelled_at": None}
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "booked"


async def test_N7_repeated_cancel_is_a_silent_204(
    client, clock, athlete, registrar, doctor, make_slot, make_booking, sql, audit
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    assert (await cancel(client, athlete, appointment_id)).status_code == 204
    first = (await sql("SELECT cancelled_at FROM appointments"))[0]["cancelled_at"]
    clock.advance(minutes=5)

    again = await cancel(client, athlete, appointment_id)
    by_staff = await cancel(client, registrar, appointment_id)

    assert again.status_code == 204 and by_staff.status_code == 204
    assert (await sql("SELECT cancelled_at FROM appointments"))[0]["cancelled_at"] == first
    assert len(await audit("appointment_cancel")) == 1
    history = await sql("SELECT id FROM status_history WHERE entity_type = 'appointment' AND to_status = 'cancelled'")
    assert len(history) == 1


async def test_N7_repeated_cancel_does_not_touch_a_slot_that_was_taken_again(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking, sql
):
    slot_id = await make_slot(doctor, at(10))
    first = await make_booking(slot_id, athlete)
    assert (await cancel(client, athlete, first)).status_code == 204
    await make_booking(slot_id, athlete2)

    again = await cancel(client, athlete, first)

    assert again.status_code == 204
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "booked"  # the new booking is intact


@pytest.mark.parametrize("role", [Role.ATHLETE, Role.REGISTRAR, Role.ADMIN])
async def test_N8_unknown_appointment_is_404(client, clock, users_by_role, role):
    assert (await cancel(client, users_by_role[role], 99999)).status_code == 404


async def test_N9_reschedule_is_cancel_plus_a_new_booking(client, clock, athlete, doctor, make_slot, make_booking, sql):
    old_slot = await make_slot(doctor, at(10))
    new_slot = await make_slot(doctor, at(14))
    appointment_id = await make_booking(old_slot, athlete)

    assert (await cancel(client, athlete, appointment_id)).status_code == 204
    assert (await book(client, athlete, new_slot)).status_code == 201

    slots = {r["id"]: r["status"] for r in await sql("SELECT id, status FROM slots")}
    assert slots == {old_slot: "free", new_slot: "booked"}
    active = await sql("SELECT id FROM appointments WHERE status = 'booked' AND athlete_id = :a", a=athlete.id)
    assert len(active) == 1
