"""Spec section 6, block S (+ section 4): audit_log and status_history of the schedule actions."""

import pytest

from app.core.rbac import Role
from tests.schedule.support import arrive, at, book, cancel, close_slot, no_show, post_batch, post_slot, reopen_slot

PRIVATE_FRAGMENTS = ("Иванов", "Иван", "@example.com", "+7999", "2026-1", "10:00")


def assert_no_private_values(rows: list[dict]) -> None:
    for row in rows:
        assert set(row) == {"id", "user_id", "action", "entity_type", "entity_id", "ip", "created_at"}
        for key in ("action", "entity_type", "ip"):
            for fragment in PRIVATE_FRAGMENTS:
                assert fragment not in str(row[key] or ""), (key, row)


async def new_audit(audit, before: int) -> list[dict]:
    return (await audit())[before:]


async def test_S1_slot_create(client, clock, doctor, audit):
    before = len(await audit())

    resp = await post_slot(client, doctor, at(10))

    [row] = await new_audit(audit, before)
    assert (row["action"], row["user_id"], row["entity_type"], row["entity_id"]) == (
        "slot_create", doctor.id, "slot", resp.json()["id"],
    )  # fmt: skip
    assert_no_private_values([row])


async def test_S1_slot_close_and_reopen(client, clock, doctor, make_slot, audit):
    slot_id = await make_slot(doctor, at(10))
    before = len(await audit())

    await close_slot(client, doctor, slot_id)
    [closed] = await new_audit(audit, before)
    await reopen_slot(client, doctor, slot_id)
    [_, reopened] = await new_audit(audit, before)

    assert (closed["action"], closed["user_id"], closed["entity_type"], closed["entity_id"]) == (
        "slot_close", doctor.id, "slot", slot_id,
    )  # fmt: skip
    assert (reopened["action"], reopened["user_id"], reopened["entity_type"], reopened["entity_id"]) == (
        "slot_reopen", doctor.id, "slot", slot_id,
    )  # fmt: skip
    assert_no_private_values([closed, reopened])


@pytest.mark.parametrize("role", [Role.ATHLETE, Role.REGISTRAR, Role.ADMIN])
async def test_S1_book_is_audited_with_the_actor_not_the_athlete(
    client, clock, users_by_role, athlete, doctor, make_slot, audit, role
):
    slot_id = await make_slot(doctor, at(10))
    before = len(await audit())

    resp = await book(client, users_by_role[role], slot_id, athlete)

    assert resp.status_code == 201
    [row] = await new_audit(audit, before)
    assert (row["action"], row["user_id"], row["entity_type"], row["entity_id"]) == (
        "appointment_book", users_by_role[role].id, "appointment", resp.json()["id"],
    )  # fmt: skip
    assert_no_private_values([row])


async def test_S1_cancel_arrive_and_no_show(
    client, clock, registrar, athlete, athlete2, doctor, make_slot, make_booking, audit
):
    cancelled = await make_booking(await make_slot(doctor, at(9)), athlete)
    arrived = await make_booking(await make_slot(doctor, at(10)), athlete)
    missed = await make_booking(await make_slot(doctor, at(11)), athlete2)
    before = len(await audit())

    await cancel(client, athlete, cancelled)
    clock.set(at(9, 0))
    await arrive(client, registrar, arrived)
    clock.set(at(12))
    await no_show(client, registrar, missed)

    rows = await new_audit(audit, before)
    got = [(r["action"], r["user_id"], r["entity_type"], r["entity_id"]) for r in rows]
    assert got == [
        ("appointment_cancel", athlete.id, "appointment", cancelled),
        ("appointment_arrive", registrar.id, "appointment", arrived),
        ("appointment_no_show", registrar.id, "appointment", missed),
    ]
    assert_no_private_values(rows)


async def test_S2_booking_history(client, clock, athlete, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    resp = await book(client, athlete, slot_id)

    appointment_id = resp.json()["id"]
    rows = await sql(
        "SELECT entity_type, entity_id, from_status, to_status, changed_by FROM status_history ORDER BY id"
    )
    assert sorted(map(tuple, (r.values() for r in rows)), key=str) == sorted(
        [
            ("appointment", appointment_id, None, "booked", athlete.id),
            ("slot", slot_id, "free", "booked", athlete.id),
        ],
        key=str,
    )


async def test_S2_cancellation_history(client, clock, registrar, athlete, doctor, make_slot, make_booking, sql):
    slot_id = await make_slot(doctor, at(10))
    appointment_id = await make_booking(slot_id, athlete)
    before = (await sql("SELECT count(*) AS n FROM status_history"))[0]["n"]

    await cancel(client, registrar, appointment_id)

    rows = await sql(
        "SELECT entity_type, entity_id, from_status, to_status, changed_by FROM status_history ORDER BY id OFFSET :o",
        o=before,
    )
    assert {tuple(r.values()) for r in rows} == {
        ("appointment", appointment_id, "booked", "cancelled", registrar.id),
        ("slot", slot_id, "booked", "free", registrar.id),
    }


async def test_S2_arrival_history(client, clock, registrar, athlete, doctor, make_slot, make_booking, sql):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)
    before = (await sql("SELECT count(*) AS n FROM status_history"))[0]["n"]
    clock.set(at(9))

    await arrive(client, registrar, appointment_id)

    rows = await sql(
        "SELECT entity_type, entity_id, from_status, to_status, changed_by FROM status_history ORDER BY id OFFSET :o",
        o=before,
    )
    assert [tuple(r.values()) for r in rows] == [("appointment", appointment_id, "booked", "arrived", registrar.id)]


async def test_S2_close_and_reopen_history(client, clock, doctor, make_slot, sql):
    slot_id = await make_slot(doctor, at(10))

    await close_slot(client, doctor, slot_id)
    await reopen_slot(client, doctor, slot_id)

    rows = await sql(
        "SELECT from_status, to_status, changed_by FROM status_history WHERE entity_type = 'slot' ORDER BY id"
    )
    assert [tuple(r.values()) for r in rows] == [("free", "closed", doctor.id), ("closed", "free", doctor.id)]


async def test_S3_failed_attempts_leave_no_audit_and_no_history(
    client, clock, athlete, athlete2, registrar, doctor, make_slot, make_booking, sql, audit
):
    taken = await make_slot(doctor, at(10))
    appointment_id = await make_booking(taken, athlete)
    closed = await make_slot(doctor, at(12), status="closed")
    audits, histories = len(await audit()), len(await sql("SELECT id FROM status_history"))

    attempts = [
        await book(client, athlete2, taken),  # 409 taken
        await book(client, athlete2, closed),  # 409 closed
        await book(client, athlete2, 99999),  # 404
        await post_slot(client, doctor, at(10, 15)),  # 409 overlap
        await post_slot(client, doctor, at(2, days=-1)),  # 422 in the past
        await post_slot(client, athlete, at(15), doctor=doctor),  # 403
        await cancel(client, athlete2, appointment_id),  # 404 foreign
        await arrive(client, registrar, appointment_id),  # 409 not today
        await no_show(client, registrar, appointment_id),  # 409 not ended
        await close_slot(client, doctor, taken),  # 409 booked
    ]

    assert [r.status_code for r in attempts] == [409, 409, 404, 409, 422, 403, 404, 409, 409, 409]
    assert len(await audit()) == audits
    assert len(await sql("SELECT id FROM status_history")) == histories


async def test_S3_listings_are_not_audited(client, clock, admin, athlete, doctor, make_slot, audit):
    await make_slot(doctor, at(10))
    before = len(await audit())

    for url in ("/schedule/slots", "/schedule/slots/all", "/schedule/appointments"):
        assert (await client.get(url, headers=admin.headers)).status_code == 200

    assert len(await audit()) == before


async def test_S4_a_batch_of_n_slots_writes_n_audit_rows(client, clock, doctor, audit):
    resp = await post_batch(client, doctor, at(9), at(11), 20)  # 6 slots

    assert resp.status_code == 201
    rows = await audit("slot_create")
    assert len(rows) == 6 and {r["entity_id"] for r in rows} == {s["id"] for s in resp.json()}
    assert {r["user_id"] for r in rows} == {doctor.id}


def test_slot_transition_table_matches_the_spec():
    from app.models.enums import SlotStatus
    from app.services.status import SLOT_TRANSITIONS

    ath_staff = frozenset({Role.ATHLETE, Role.REGISTRAR, Role.ADMIN})
    doc_admin = frozenset({Role.DOCTOR, Role.ADMIN})
    assert SLOT_TRANSITIONS == {
        (SlotStatus.FREE, SlotStatus.BOOKED): ath_staff,
        (SlotStatus.BOOKED, SlotStatus.FREE): ath_staff,
        (SlotStatus.FREE, SlotStatus.CLOSED): doc_admin,
        (SlotStatus.CLOSED, SlotStatus.FREE): doc_admin,
    }
