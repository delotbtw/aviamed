"""GET /schedule/appointments (spec 3.7). The criteria list has no block for it: tests are named V<n>."""

from datetime import timedelta

import pytest

from app.core.rbac import Role
from tests.schedule.support import NOW, at, cancel, ids, msk

URL = "/schedule/appointments"
ITEM_KEYS = {
    "id", "status", "slot_id", "start_at", "end_at", "doctor_name", "specialty", "cabinet",
    "athlete_id", "athlete_name", "case_id", "cancelled_at", "doctor_active",
}  # fmt: skip


async def test_V1_athlete_sees_only_his_own_appointments(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking
):
    mine = await make_booking(await make_slot(doctor, at(10)), athlete)
    await make_booking(await make_slot(doctor, at(11)), athlete2)

    resp = await client.get(URL, headers=athlete.headers)

    assert resp.status_code == 200
    assert ids(resp) == [mine]
    assert {i["athlete_id"] for i in resp.json()} == {athlete.id}


async def test_V1_athlete_asking_for_someone_else_is_403_and_for_himself_is_fine(client, clock, athlete, athlete2):
    foreign = await client.get(URL, params={"athlete_id": athlete2.id}, headers=athlete.headers)
    own = await client.get(URL, params={"athlete_id": athlete.id}, headers=athlete.headers)

    assert foreign.status_code == 403
    assert own.status_code == 200


@pytest.mark.parametrize("role", [Role.DOCTOR, Role.COACH])
async def test_V1_doctor_and_coach_are_forbidden(client, clock, users_by_role, role):
    assert (await client.get(URL, headers=users_by_role[role].headers)).status_code == 403


async def test_V1_without_token_is_401(client, clock):
    assert (await client.get(URL)).status_code == 401


async def test_V2_item_shape_and_names(client, clock, registrar, athlete, doctor2, make_slot, make_booking, make_case):
    case_id = await make_case(athlete)
    slot_id = await make_slot(doctor2, at(10, 30))
    appointment_id = await make_booking(slot_id, athlete, case_id=case_id)

    [item] = (await client.get(URL, headers=registrar.headers)).json()

    assert set(item) == ITEM_KEYS
    assert item["id"] == appointment_id and item["slot_id"] == slot_id and item["status"] == "booked"
    assert item["athlete_id"] == athlete.id and item["athlete_name"] == "Иванов Иван Иванович"
    assert item["doctor_name"] == "Кузнецов Пётр Иванович" and item["specialty"] == "Кардиология"
    assert item["cabinet"] == "305" and item["case_id"] == case_id
    assert item["cancelled_at"] is None and item["doctor_active"] is True
    assert item["start_at"].startswith("2026-11-03T07:30:00")


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ADMIN])
async def test_V2_staff_sees_everyone_and_filters(
    client, clock, users_by_role, athlete, athlete2, doctor, doctor2, make_slot, make_booking, force_status, role
):
    h = users_by_role[role].headers
    a = await make_booking(await make_slot(doctor, at(10, days=1)), athlete)
    b = await make_booking(await make_slot(doctor2, at(10, days=3)), athlete2)
    await force_status(b, "arrived")

    async def query(**params):
        resp = await client.get(URL, params=params, headers=h)
        assert resp.status_code == 200, resp.text
        return set(ids(resp))

    assert await query() == {a, b}
    assert await query(athlete_id=athlete.id) == {a}
    assert await query(doctor_id=doctor2.id) == {b}
    assert await query(status="arrived") == {b}
    assert await query(date_from="2026-11-04") == {b}
    assert await query(date_to="2026-11-03") == {a}
    assert await query(athlete_id=athlete2.id, doctor_id=doctor2.id, status="arrived") == {b}
    assert await query(athlete_id=athlete.id, doctor_id=doctor2.id) == set()


async def test_V3_default_list_hides_finished_and_past_cancelled_ones(
    client, clock, registrar, athlete, doctor, make_slot, make_booking
):
    clock.set(msk(2026, 11, 2, 7, 0))
    past_booked = await make_booking(await make_slot(doctor, msk(2026, 11, 2, 8, 0), minutes=30), athlete)
    past_cancelled = await make_booking(await make_slot(doctor, msk(2026, 11, 2, 9, 0), minutes=30), athlete)
    assert (await cancel(client, registrar, past_cancelled)).status_code == 204
    future = await make_booking(await make_slot(doctor, at(10)), athlete)
    future_cancelled = await make_booking(await make_slot(doctor, at(12)), athlete)
    assert (await cancel(client, registrar, future_cancelled)).status_code == 204
    clock.set(msk(2026, 11, 2, 10, 0))  # both of today's slots are over

    default = await client.get(URL, headers=registrar.headers)
    cancelled_only = await client.get(URL, params={"status": "cancelled"}, headers=registrar.headers)

    assert set(ids(default)) == {future, future_cancelled}
    assert set(ids(cancelled_only)) == {past_cancelled, future_cancelled}
    assert past_booked not in ids(cancelled_only)


async def test_V3_explicit_dates_bring_back_the_past(
    client, clock, registrar, athlete, doctor, make_slot, make_booking
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    clock.set(at(12))

    default = await client.get(URL, headers=registrar.headers)
    dated = await client.get(
        URL, params={"date_from": "2026-11-03", "date_to": "2026-11-03"}, headers=registrar.headers
    )

    assert ids(default) == []
    assert ids(dated) == [appointment_id]


async def test_V4_cancelled_item_carries_cancelled_at_and_inactive_doctor_is_flagged(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, sql
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    await sql("UPDATE users SET is_active = false WHERE id = :i", i=doctor.id)

    [item] = (await client.get(URL, headers=registrar.headers)).json()
    assert item["doctor_active"] is False and item["status"] == "booked"

    assert (await cancel(client, registrar, appointment_id)).status_code == 204
    [cancelled] = (await client.get(URL, params={"status": "cancelled"}, headers=registrar.headers)).json()
    assert cancelled["cancelled_at"] is not None and cancelled["status"] == "cancelled"


async def test_V5_order_and_pagination(
    client, clock, registrar, athlete, athlete2, doctor, doctor2, make_slot, make_booking
):
    created = []
    for who, doc, hour in [
        (athlete, doctor, 12),
        (athlete2, doctor2, 9),
        (athlete, doctor2, 11),
        (athlete2, doctor, 10),
    ]:
        created.append(await make_booking(await make_slot(doc, at(hour)), who))

    full = await client.get(URL, headers=registrar.headers)
    starts = [(i["start_at"], i["id"]) for i in full.json()]
    assert starts == sorted(starts) and set(ids(full)) == set(created)

    first = await client.get(URL, params={"limit": 3}, headers=registrar.headers)
    rest = await client.get(URL, params={"limit": 3, "offset": 3}, headers=registrar.headers)
    assert ids(first) + ids(rest) == ids(full) and len(ids(rest)) == 1
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        assert (await client.get(URL, params=bad, headers=registrar.headers)).status_code == 422


async def test_V6_listing_makes_no_audit_entries(
    client, clock, registrar, athlete, doctor, make_slot, make_booking, audit
):
    await make_booking(await make_slot(doctor, at(10)), athlete)
    before = len(await audit())

    await client.get(URL, headers=registrar.headers)
    await client.get(URL, headers=athlete.headers)
    await client.get("/schedule/slots", headers=athlete.headers)

    assert len(await audit()) == before


async def test_V7_slot_datetimes_are_utc(client, clock, athlete, doctor, make_slot, make_booking):
    await make_booking(await make_slot(doctor, NOW + timedelta(days=1, hours=1)), athlete)

    [item] = (await client.get(URL, headers=athlete.headers)).json()

    assert item["start_at"].endswith(("Z", "+00:00")) and item["end_at"].endswith(("Z", "+00:00"))
