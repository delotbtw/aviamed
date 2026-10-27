"""Spec section 6, block M: POST /schedule/appointments."""

from datetime import timedelta

import pytest

from app.core.rbac import Role
from tests.schedule.support import HORIZON_DAYS, NOW, at, book, cancel

URL = "/schedule/appointments"


async def test_M1_athlete_books_himself(client, clock, athlete, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    resp = await book(client, athlete, slot_id)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "booked" and body["slot_id"] == slot_id and body["athlete_id"] == athlete.id
    assert body["case_id"] is None
    [appointment] = await sql("SELECT status, created_by, athlete_id, cancelled_at FROM appointments")
    assert appointment == {"status": "booked", "created_by": athlete.id, "athlete_id": athlete.id, "cancelled_at": None}
    assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == "booked"


async def test_M2_registrar_books_an_athlete(client, clock, registrar, athlete, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    resp = await book(client, registrar, slot_id, athlete)

    assert resp.status_code == 201, resp.text
    [row] = await sql("SELECT created_by, athlete_id FROM appointments")
    assert row == {"created_by": registrar.id, "athlete_id": athlete.id}


async def test_M2_admin_books_an_athlete(client, clock, admin, athlete2, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    resp = await book(client, admin, slot_id, athlete2)

    assert resp.status_code == 201, resp.text
    [row] = await sql("SELECT created_by, athlete_id FROM appointments")
    assert row == {"created_by": admin.id, "athlete_id": athlete2.id}


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ADMIN])
async def test_M3_staff_must_name_the_athlete(client, clock, users_by_role, doctor, make_slot, sql, role):
    slot_id = await make_slot(doctor, at(10))

    resp = await client.post(URL, json={"slot_id": slot_id}, headers=users_by_role[role].headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM appointments") == []


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ADMIN])
@pytest.mark.parametrize("target", ["doctor", "coach", "registrar", "inactive_athlete", "missing"])
async def test_M3_athlete_id_must_be_an_active_athlete(
    client, clock, users_by_role, make_user, doctor, make_slot, sql, role, target
):
    slot_id = await make_slot(doctor, at(10))
    if target == "inactive_athlete":
        athlete_id = (await make_user(Role.ATHLETE, is_active=False)).id
    elif target == "missing":
        athlete_id = 99999
    else:
        athlete_id = users_by_role[Role(target)].id

    resp = await client.post(
        URL, json={"slot_id": slot_id, "athlete_id": athlete_id}, headers=users_by_role[role].headers
    )

    assert resp.status_code == 422, resp.text
    assert await sql("SELECT id FROM appointments") == []
    assert (await sql("SELECT status FROM slots"))[0]["status"] == "free"


async def test_M4_athlete_cannot_book_for_someone_else(client, clock, athlete, athlete2, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    resp = await client.post(URL, json={"slot_id": slot_id, "athlete_id": athlete2.id}, headers=athlete.headers)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM appointments") == []


async def test_M4_athlete_may_name_himself(client, clock, athlete, doctor, make_slot):
    slot_id = await make_slot(doctor, at(10))

    resp = await client.post(URL, json={"slot_id": slot_id, "athlete_id": athlete.id}, headers=athlete.headers)

    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("role", [Role.DOCTOR, Role.COACH])
async def test_M4_doctor_and_coach_are_forbidden(client, clock, users_by_role, athlete, doctor, make_slot, sql, role):
    slot_id = await make_slot(doctor, at(10))

    resp = await book(client, users_by_role[role], slot_id, athlete)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM appointments") == []


async def test_M4_without_token_is_401(client, clock):
    assert (await client.post(URL, json={"slot_id": 1})).status_code == 401


async def test_M5_unknown_slot_is_404(client, clock, athlete):
    assert (await book(client, athlete, 99999)).status_code == 404


async def test_M5_taken_slot_is_409(client, clock, athlete, athlete2, doctor, make_slot, make_booking, sql):
    slot_id = await make_slot(doctor, at(10))
    await make_booking(slot_id, athlete)

    resp = await book(client, athlete2, slot_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot is already taken"
    assert len(await sql("SELECT id FROM appointments")) == 1


async def test_M5_same_athlete_booking_the_same_slot_twice_is_409(
    client, clock, athlete, doctor, make_slot, make_booking
):
    slot_id = await make_slot(doctor, at(10))
    await make_booking(slot_id, athlete)

    resp = await book(client, athlete, slot_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot is already taken"


async def test_M5_closed_slot_is_409(client, clock, athlete, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10), status="closed")

    resp = await book(client, athlete, slot_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot is closed"
    assert await sql("SELECT id FROM appointments") == []


@pytest.mark.parametrize("role", [Role.ATHLETE, Role.REGISTRAR, Role.ADMIN])
@pytest.mark.parametrize("offset_min", [0, -1, -600], ids=["starts-now", "started", "long-past"])
async def test_M6_slot_that_has_started_is_409_for_everyone(
    client, clock, users_by_role, athlete, doctor, make_slot, sql, role, offset_min
):
    slot_id = await make_slot(doctor, NOW + timedelta(minutes=offset_min), minutes=30)

    resp = await book(client, users_by_role[role], slot_id, athlete)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot has already started"
    assert await sql("SELECT id FROM appointments") == []


async def test_M6_slot_beyond_the_horizon_is_409(client, clock, athlete, doctor, make_slot):
    slot_id = await make_slot(doctor, NOW + timedelta(days=HORIZON_DAYS, minutes=1))

    resp = await book(client, athlete, slot_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Slot is too far ahead"


async def test_M6_slot_exactly_on_the_horizon_is_bookable(client, clock, athlete, doctor, make_slot):
    slot_id = await make_slot(doctor, NOW + timedelta(days=HORIZON_DAYS))

    assert (await book(client, athlete, slot_id)).status_code == 201


async def test_M6_slot_of_a_deactivated_doctor_is_409(client, clock, athlete, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))
    await sql("UPDATE users SET is_active = false WHERE id = :i", i=doctor.id)

    resp = await book(client, athlete, slot_id)

    assert resp.status_code == 409 and resp.json()["detail"] == "Doctor is not active"
    assert await sql("SELECT id FROM appointments") == []


async def test_M7_overlapping_appointment_at_another_doctor_is_409(
    client, clock, athlete, doctor, doctor2, make_slot, make_booking, sql
):
    first = await make_slot(doctor, at(10), minutes=30)  # 10:00-10:30
    second = await make_slot(doctor2, at(10, 15), minutes=30)  # 10:15-10:45
    await make_booking(first, athlete)

    resp = await book(client, athlete, second)

    assert resp.status_code == 409 and resp.json()["detail"] == "Athlete has an overlapping appointment"
    assert len(await sql("SELECT id FROM appointments")) == 1
    assert (await sql("SELECT status FROM slots WHERE id = :i", i=second))[0]["status"] == "free"


async def test_M7_registrar_is_bound_by_the_same_overlap_rule(
    client, clock, registrar, athlete, doctor, doctor2, make_slot, make_booking
):
    await make_booking(await make_slot(doctor, at(10)), athlete)
    other = await make_slot(doctor2, at(10))

    resp = await book(client, registrar, other, athlete)

    assert resp.status_code == 409 and resp.json()["detail"] == "Athlete has an overlapping appointment"


async def test_M7_arrived_appointment_still_blocks_the_time(
    client, clock, athlete, doctor, doctor2, make_slot, make_booking, force_status
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    await force_status(appointment_id, "arrived")

    resp = await book(client, athlete, await make_slot(doctor2, at(10, 15)))

    assert resp.status_code == 409 and resp.json()["detail"] == "Athlete has an overlapping appointment"


async def test_M7_cancelled_appointment_does_not_block_the_time(
    client, clock, athlete, doctor, doctor2, make_slot, make_booking
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    assert (await cancel(client, athlete, appointment_id)).status_code == 204

    resp = await book(client, athlete, await make_slot(doctor2, at(10, 15)))

    assert resp.status_code == 201, resp.text


async def test_M7_touching_appointments_are_fine(client, clock, athlete, doctor, doctor2, make_slot, make_booking):
    await make_booking(await make_slot(doctor, at(10), minutes=30), athlete)

    resp = await book(client, athlete, await make_slot(doctor2, at(10, 30), minutes=30))

    assert resp.status_code == 201, resp.text


async def test_M7_other_athlete_may_take_the_overlapping_slot(
    client, clock, athlete, athlete2, doctor, doctor2, make_slot, make_booking
):
    await make_booking(await make_slot(doctor, at(10)), athlete)

    resp = await book(client, athlete2, await make_slot(doctor2, at(10)))

    assert resp.status_code == 201, resp.text


async def _consecutive_slots(make_slot, doctor, count: int) -> list[int]:
    return [await make_slot(doctor, at(8) + timedelta(minutes=10 * i), minutes=10) for i in range(count)]


async def test_M8_twenty_first_active_appointment_is_409(
    client, clock, athlete, doctor, make_slot, make_booking, force_status, sql
):
    slots = await _consecutive_slots(make_slot, doctor, 23)
    appointments = [await make_booking(s, athlete) for s in slots[:20]]

    over = await book(client, athlete, slots[20])
    assert over.status_code == 409 and over.json()["detail"] == "Too many active appointments"
    assert (await sql("SELECT status FROM slots WHERE id = :i", i=slots[20]))[0]["status"] == "free"

    assert (await cancel(client, athlete, appointments[0])).status_code == 204  # cancelled ones do not count
    assert (await book(client, athlete, slots[20])).status_code == 201

    await force_status(appointments[1], "arrived")  # arrived counts as active
    assert (await book(client, athlete, slots[21])).status_code == 409
    await force_status(appointments[1], "done")  # finished ones do not
    assert (await book(client, athlete, slots[21])).status_code == 201


async def test_M8_limit_comes_from_settings(client, clock, settings_env, athlete, athlete2, doctor, make_slot):
    settings_env(max_active_appointments=2)
    slots = await _consecutive_slots(make_slot, doctor, 4)

    codes = [(await book(client, athlete, s)).status_code for s in slots[:3]]
    other = await book(client, athlete2, slots[3])

    assert codes == [201, 201, 409]
    assert other.status_code == 201  # the limit is per athlete


async def test_M8_registrar_is_bound_by_the_limit(client, clock, settings_env, registrar, athlete, doctor, make_slot):
    settings_env(max_active_appointments=1)
    first, second = await _consecutive_slots(make_slot, doctor, 2)
    assert (await book(client, registrar, first, athlete)).status_code == 201

    resp = await book(client, registrar, second, athlete)

    assert resp.status_code == 409 and resp.json()["detail"] == "Too many active appointments"


@pytest.mark.parametrize("state", ["cancelled", "completed"])
async def test_M9_unusable_case_is_422(client, clock, athlete, doctor, make_slot, make_case, sql, state):
    slot_id = await make_slot(doctor, at(10))
    case_id = await make_case(athlete, state)

    resp = await book(client, athlete, slot_id, case_id=case_id)

    assert resp.status_code == 422, resp.text
    assert await sql("SELECT id FROM appointments") == []


async def test_M9_case_of_another_athlete_is_422(client, clock, athlete, athlete2, doctor, make_slot, make_case, sql):
    slot_id = await make_slot(doctor, at(10))
    foreign_case = await make_case(athlete2)

    resp = await book(client, athlete, slot_id, case_id=foreign_case)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM appointments") == []


async def test_M9_registrar_booking_with_a_case_of_a_different_athlete_is_422(
    client, clock, registrar, athlete, athlete2, doctor, make_slot, make_case
):
    slot_id = await make_slot(doctor, at(10))

    resp = await book(client, registrar, slot_id, athlete, case_id=await make_case(athlete2))

    assert resp.status_code == 422


async def test_M9_unknown_case_is_422(client, clock, athlete, doctor, make_slot):
    resp = await book(client, athlete, await make_slot(doctor, at(10)), case_id=99999)

    assert resp.status_code == 422


@pytest.mark.parametrize("state", ["registered", "in_progress"])
async def test_M9_open_case_is_linked(client, clock, athlete, doctor, make_slot, make_case, sql, state):
    case_id = await make_case(athlete, state)

    resp = await book(client, athlete, await make_slot(doctor, at(10)), case_id=case_id)

    assert resp.status_code == 201, resp.text
    assert resp.json()["case_id"] == case_id
    assert (await sql("SELECT case_id FROM appointments"))[0]["case_id"] == case_id


async def test_M9_without_case_the_link_is_null(client, clock, athlete, doctor, make_slot, sql):
    resp = await book(client, athlete, await make_slot(doctor, at(10)))

    assert resp.status_code == 201 and resp.json()["case_id"] is None
    assert (await sql("SELECT case_id FROM appointments"))[0]["case_id"] is None


async def test_M10_failure_after_the_insert_rolls_everything_back(client, clock, athlete, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))
    await sql(
        "CREATE OR REPLACE FUNCTION test_fail() RETURNS trigger AS $$ BEGIN "
        "IF NEW.action = 'appointment_book' THEN RAISE EXCEPTION 'boom'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    await sql("CREATE TRIGGER test_fail_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION test_fail()")

    try:
        try:
            resp = await book(client, athlete, slot_id)
            assert resp.status_code >= 500  # the injected failure is not a client error
        except Exception:  # noqa: BLE001  (ASGITransport re-raises unhandled app exceptions)
            pass
    finally:
        await sql("DROP TRIGGER IF EXISTS test_fail_audit ON audit_log")

    assert await sql("SELECT id FROM appointments") == []
    assert (await sql("SELECT status FROM slots WHERE id = :i", i=slot_id))[0]["status"] == "free"
    assert await sql("SELECT id FROM status_history") == []
    assert await sql("SELECT id FROM audit_log WHERE action = 'appointment_book'") == []
    retry = await book(client, athlete, slot_id)  # the slot is still usable
    assert retry.status_code == 201, retry.text


async def test_M11_independent_slots_do_not_interfere(client, clock, athlete, doctor, doctor2, make_slot):
    slots = [
        await make_slot(doctor, at(10, days=1)),
        await make_slot(doctor2, at(11, days=2)),
        await make_slot(doctor, at(10, days=5)),
    ]

    codes = [(await book(client, athlete, s)).status_code for s in slots]

    assert codes == [201, 201, 201]
