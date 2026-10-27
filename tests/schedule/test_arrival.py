"""Spec section 6, block O: arrival (POST .../arrive) and no-show (POST .../no-show)."""

import asyncio

import pytest
from sqlalchemy import text

from app.core.rbac import Role
from tests.schedule.support import arrive, at, cancel, gather, msk, no_show


async def _booked(make_slot, make_booking, doctor, athlete, start=None, **extra) -> tuple[int, int]:
    slot_id = await make_slot(doctor, start or at(10), minutes=30)
    return slot_id, await make_booking(slot_id, athlete, **extra)


async def test_O1_registrar_marks_arrival_on_the_day_of_the_slot(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, sql
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(8))

    resp = await arrive(client, registrar, appointment_id)

    assert resp.status_code == 204
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "arrived"
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "booked"


@pytest.mark.parametrize("hour", [0, 10, 11, 23], ids=["midnight", "during", "after-end", "late-evening"])
async def test_O1_any_time_of_the_day_works_even_after_the_slot_ended(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, hour
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(hour, 59 if hour == 23 else 0))

    assert (await arrive(client, registrar, appointment_id)).status_code == 204


@pytest.mark.parametrize(
    "now",
    [msk(2026, 11, 2, 12), msk(2026, 11, 2, 23, 59), msk(2026, 11, 4, 0, 0), msk(2026, 11, 5, 10)],
    ids=["day-before-noon", "day-before-2359", "next-day-0000", "two-days-later"],
)
async def test_O2_arrival_outside_the_day_of_the_slot_is_409(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, sql, now
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)  # 03.11 10:00 Moscow
    clock.set(now)

    resp = await arrive(client, registrar, appointment_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Appointment is not due today"
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


async def test_O2_midnight_boundary(client, clock, registrar, athlete, doctor, make_slot, make_booking):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete, start=at(0, 30))  # 03.11 00:30 Moscow
    clock.set(msk(2026, 11, 2, 23, 59))

    assert (await arrive(client, registrar, appointment_id)).status_code == 409

    clock.set(msk(2026, 11, 3, 0, 0))
    assert (await arrive(client, registrar, appointment_id)).status_code == 204


@pytest.mark.parametrize("role", [Role.ADMIN, Role.DOCTOR, Role.ATHLETE, Role.COACH])
async def test_O3_only_the_registrar_may_mark_arrival(
    client, clock, users_by_role, athlete, doctor, make_slot, make_booking, sql, role
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(9))

    resp = await arrive(client, users_by_role[role], appointment_id)

    assert resp.status_code == 403
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


async def test_O3_without_token_is_401(client, clock):
    assert (await client.post("/schedule/appointments/1/arrive")).status_code == 401


async def test_O3_unknown_appointment_is_404(client, clock, registrar):
    assert (await arrive(client, registrar, 99999)).status_code == 404


@pytest.mark.parametrize("state", ["cancelled", "arrived", "no_show"])
async def test_O4_arrival_from_a_status_other_than_booked_is_409(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, force_status, sql, state
):
    slot_id, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    await force_status(appointment_id, state)
    clock.set(at(9))

    resp = await arrive(client, registrar, appointment_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Invalid appointment status"
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == state


async def test_O4_second_arrival_click_is_409_not_idempotent(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, audit
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(9))
    assert (await arrive(client, registrar, appointment_id)).status_code == 204

    again = await arrive(client, registrar, appointment_id)

    assert again.status_code == 409 and again.json()["detail"] == "Invalid appointment status"
    assert len(await audit("appointment_arrive")) == 1


async def test_O5_arrival_moves_a_registered_case_to_in_progress(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, make_case, sql
):
    case_id = await make_case(athlete, "registered")
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete, case_id=case_id)
    clock.set(at(9))

    resp = await arrive(client, registrar, appointment_id)

    assert resp.status_code == 204
    assert (await sql("SELECT status FROM medical_cases"))[0]["status"] == "in_progress"
    [history] = await sql("SELECT * FROM status_history WHERE entity_type = 'case'")
    assert history["entity_id"] == case_id
    assert (history["from_status"], history["to_status"], history["changed_by"]) == (
        "registered",
        "in_progress",
        registrar.id,
    )


async def test_O5_case_already_in_progress_stays_and_gets_no_extra_history(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, make_case, sql
):
    case_id = await make_case(athlete, "in_progress")
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete, case_id=case_id)
    clock.set(at(9))

    resp = await arrive(client, registrar, appointment_id)

    assert resp.status_code == 204
    assert (await sql("SELECT status FROM medical_cases"))[0]["status"] == "in_progress"
    assert await sql("SELECT id FROM status_history WHERE entity_type = 'case'") == []


async def test_O5_appointment_without_a_case_arrives_without_touching_cases(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, make_case, sql
):
    case_id = await make_case(athlete, "registered")  # exists, but is not linked to the appointment
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(9))

    resp = await arrive(client, registrar, appointment_id)

    assert resp.status_code == 204
    assert (await sql("SELECT status FROM medical_cases WHERE id = :i", i=case_id))[0]["status"] == "registered"


async def test_O6_concurrent_case_change_during_arrival_never_leaves_a_partial_result(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, make_case, sql, db_engine
):
    """A second session holds the case row and bumps its `version` (optimistic lock) while the arrival is in flight.

    Either outcome is correct: the arrival waits for the row lock and then succeeds on the fresh version (204), or it
    notices the stale version (409). A half-applied arrival (appointment arrived, case untouched) never is.
    """
    case_id = await make_case(athlete, "registered")
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete, case_id=case_id)
    clock.set(at(9))

    async with db_engine.connect() as holder:
        await holder.execute(text("SELECT id FROM medical_cases WHERE id = :i FOR UPDATE"), {"i": case_id})
        task = asyncio.create_task(arrive(client, registrar, appointment_id))
        await asyncio.sleep(0.5)
        await holder.execute(text("UPDATE medical_cases SET version = version + 1 WHERE id = :i"), {"i": case_id})
        await holder.commit()
        resp = await asyncio.wait_for(task, 30)

    appointment = (await sql("SELECT status FROM appointments"))[0]["status"]
    case = (await sql("SELECT status FROM medical_cases"))[0]["status"]
    case_history = await sql("SELECT id FROM status_history WHERE entity_type = 'case'")
    audit_rows = await sql("SELECT id FROM audit_log WHERE action = 'appointment_arrive'")
    assert resp.status_code in (204, 409), resp.text
    if resp.status_code == 204:
        assert (appointment, case, len(case_history), len(audit_rows)) == ("arrived", "in_progress", 1, 1)
    else:
        assert (appointment, case, len(case_history), len(audit_rows)) == ("booked", "registered", 0, 0)
        retry = await arrive(client, registrar, appointment_id)  # the client repeats, as the spec says
        assert retry.status_code == 204


async def test_O7_no_show_after_the_end_of_the_slot(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, sql, audit
):
    slot_id, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)  # 10:00-10:30
    clock.set(at(10, 30))  # now == end_at

    resp = await no_show(client, registrar, appointment_id)

    assert resp.status_code == 204
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "no_show"
    assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == "booked"
    [row] = await audit("appointment_no_show")
    assert (row["user_id"], row["entity_type"], row["entity_id"]) == (registrar.id, "appointment", appointment_id)


async def test_O7_no_show_before_the_end_is_409(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, sql
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(10, 29))

    resp = await no_show(client, registrar, appointment_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot has not ended"
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


@pytest.mark.parametrize("role", [Role.ADMIN, Role.DOCTOR, Role.ATHLETE, Role.COACH])
async def test_O7_only_the_registrar_may_mark_no_show(
    client, clock, users_by_role, athlete, doctor, make_slot, make_booking, sql, role
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(12))

    resp = await no_show(client, users_by_role[role], appointment_id)

    assert resp.status_code == 403
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "booked"


async def test_O7_no_show_of_an_already_arrived_appointment_is_409(
    client, clock, registrar, athlete, doctor, make_slot, make_booking
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(9))
    assert (await arrive(client, registrar, appointment_id)).status_code == 204
    clock.set(at(12))

    resp = await no_show(client, registrar, appointment_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Invalid appointment status"


async def test_O8_no_show_cannot_be_cancelled_or_turned_into_an_arrival(
    client, clock, registrar, admin, athlete, doctor, make_slot, make_booking, sql
):
    _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete)
    clock.set(at(11))
    assert (await no_show(client, registrar, appointment_id)).status_code == 204

    cancelled = await cancel(client, registrar, appointment_id)
    cancelled_by_admin = await cancel(client, admin, appointment_id)
    arrived = await arrive(client, registrar, appointment_id)

    assert [cancelled.status_code, cancelled_by_admin.status_code, arrived.status_code] == [409, 409, 409]
    assert (await sql("SELECT status FROM appointments"))[0]["status"] == "no_show"


async def test_O_cancel_and_arrive_race_has_one_winner(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, sql
):
    for n in range(4):
        _, appointment_id = await _booked(make_slot, make_booking, doctor, athlete, start=at(8 + 2 * n))
        clock.set(at(7))

        cancelled, arrived = await gather(
            cancel(client, registrar, appointment_id), arrive(client, registrar, appointment_id)
        )

        assert sorted([cancelled.status_code, arrived.status_code]) == [204, 409], (cancelled.text, arrived.text)
        status = (await sql("SELECT status FROM appointments WHERE id = :i", i=appointment_id))[0]["status"]
        assert status == ("cancelled" if cancelled.status_code == 204 else "arrived")
