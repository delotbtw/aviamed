"""Spec section 6 J-10, U-2, U-3 and section 11 (tests 11): the database itself rejects what the service must prevent.

All inserts here bypass the application (and its row locks) on purpose.
"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.schedule.support import at

# Raw inserts deliberately skip status_history and the slot <-> appointment bookkeeping.
pytestmark = pytest.mark.no_schedule_invariants

INSERT_SLOT = "INSERT INTO slots (doctor_id, start_at, end_at, status) VALUES (:d, :s, :e, :st) RETURNING id"
INSERT_APPOINTMENT = (
    "INSERT INTO appointments (slot_id, athlete_id, status, created_by) VALUES (:slot, :a, :st, :a) RETURNING id"
)


async def insert_slot(sql, doctor, start, minutes=30, status="free") -> int:
    [row] = await sql(INSERT_SLOT, d=doctor.id, s=start, e=start + timedelta(minutes=minutes), st=status)
    return row["id"]


async def expect_db_error(coro, constraint: str) -> None:
    with pytest.raises(DBAPIError) as caught:
        await coro
    assert constraint in str(caught.value), caught.value


# --------------------------------------------------------------------------- slots


@pytest.mark.parametrize(
    ("start_h", "start_m", "minutes"),
    [(10, 15, 30), (10, 5, 20), (10, 0, 20), (10, 0, 30), (9, 45, 60), (9, 45, 30)],
    ids=["partial", "nested", "same-start", "identical", "containing", "overlaps-start"],
)
async def test_J10_exclusion_constraint_rejects_overlapping_slots_of_one_doctor(sql, doctor, start_h, start_m, minutes):
    await insert_slot(sql, doctor, at(10), 30)

    await expect_db_error(insert_slot(sql, doctor, at(start_h, start_m), minutes), "ex_slots_no_overlap")

    assert len(await sql("SELECT id FROM slots")) == 1


async def test_J10_exclusion_covers_closed_slots_too(sql, doctor):
    await insert_slot(sql, doctor, at(10), 30, status="closed")

    await expect_db_error(insert_slot(sql, doctor, at(10, 10), 30), "ex_slots_no_overlap")


async def test_J10_touching_slots_and_other_doctors_are_allowed(sql, doctor, doctor2):
    await insert_slot(sql, doctor, at(10), 30)

    await insert_slot(sql, doctor, at(10, 30), 30)  # starts when the first ends
    await insert_slot(sql, doctor, at(9, 30), 30)  # ends when the first starts
    await insert_slot(sql, doctor2, at(10), 30)  # same time, another doctor

    assert len(await sql("SELECT id FROM slots")) == 4


@pytest.mark.parametrize("minutes", [0, -10])
async def test_J10_check_constraint_rejects_end_not_after_start(sql, doctor, minutes):
    await expect_db_error(insert_slot(sql, doctor, at(10), minutes), "ck_slots_end_after_start")

    assert await sql("SELECT id FROM slots") == []


async def test_J10_check_constraint_also_guards_updates(sql, doctor):
    slot_id = await insert_slot(sql, doctor, at(10), 30)

    await expect_db_error(
        sql("UPDATE slots SET end_at = start_at WHERE id = :i", i=slot_id), "ck_slots_end_after_start"
    )


async def test_exclusion_constraint_rejects_overlap_without_the_lock(db_engine, doctor):
    """Two transactions insert overlapping slots at once: the second one waits for the first and then fails (23P01)."""
    params = {"d": doctor.id, "s": at(10), "e": at(10, 30), "st": "free"}
    overlapping = {**params, "s": at(10, 15), "e": at(10, 45)}
    async with db_engine.connect() as first, db_engine.connect() as second:
        await first.execute(text(INSERT_SLOT), params)
        pending = asyncio.create_task(second.execute(text(INSERT_SLOT), overlapping))
        await asyncio.sleep(0.4)
        assert not pending.done()  # blocked on the uncommitted row of `first`
        await first.commit()
        with pytest.raises(DBAPIError) as caught:
            await asyncio.wait_for(pending, 10)
        assert "ex_slots_no_overlap" in str(caught.value)
        await second.rollback()


# --------------------------------------------------------------------------- appointments


@pytest.mark.parametrize("state", ["booked", "arrived", "done", "no_show"])
async def test_U2_second_active_appointment_on_a_slot_is_rejected(sql, doctor, athlete, athlete2, state):
    slot_id = await insert_slot(sql, doctor, at(10))
    await sql(INSERT_APPOINTMENT, slot=slot_id, a=athlete.id, st=state)

    await expect_db_error(
        sql(INSERT_APPOINTMENT, slot=slot_id, a=athlete2.id, st="booked"), "uq_appointments_slot_active"
    )

    assert len(await sql("SELECT id FROM appointments")) == 1


async def test_U2_cancelled_appointment_does_not_block_a_new_one(sql, doctor, athlete, athlete2):
    slot_id = await insert_slot(sql, doctor, at(10))
    await sql(INSERT_APPOINTMENT, slot=slot_id, a=athlete.id, st="cancelled")
    await sql(INSERT_APPOINTMENT, slot=slot_id, a=athlete.id, st="cancelled")  # history may hold many

    await sql(INSERT_APPOINTMENT, slot=slot_id, a=athlete2.id, st="booked")

    rows = await sql("SELECT status FROM appointments ORDER BY id")
    assert [r["status"] for r in rows] == ["cancelled", "cancelled", "booked"]


async def test_U2_updating_a_cancelled_row_back_to_active_is_guarded_too(sql, doctor, athlete, athlete2):
    slot_id = await insert_slot(sql, doctor, at(10))
    [old] = await sql(INSERT_APPOINTMENT, slot=slot_id, a=athlete.id, st="cancelled")
    await sql(INSERT_APPOINTMENT, slot=slot_id, a=athlete2.id, st="booked")

    await expect_db_error(
        sql("UPDATE appointments SET status = 'booked' WHERE id = :i", i=old["id"]), "uq_appointments_slot_active"
    )


async def test_unique_index_rejects_second_active_appointment_without_the_lock(
    db_engine, sql, doctor, athlete, athlete2
):
    """Two connections insert an active appointment for one slot at once (no row lock taken, as after a bug)."""
    slot_id = await insert_slot(sql, doctor, at(10))
    async with db_engine.connect() as first, db_engine.connect() as second:
        await first.execute(text(INSERT_APPOINTMENT), {"slot": slot_id, "a": athlete.id, "st": "booked"})
        pending = asyncio.create_task(
            second.execute(text(INSERT_APPOINTMENT), {"slot": slot_id, "a": athlete2.id, "st": "booked"})
        )
        await asyncio.sleep(0.4)
        assert not pending.done()
        await first.commit()
        with pytest.raises(DBAPIError) as caught:
            await asyncio.wait_for(pending, 10)
        assert "uq_appointments_slot_active" in str(caught.value)
        await second.rollback()

    assert len(await sql("SELECT id FROM appointments")) == 1


# --------------------------------------------------------------------------- schema shape


async def test_U2_full_unique_slot_id_is_gone_and_the_partial_one_exists(sql):
    constraints = {r["conname"] for r in await sql("SELECT conname FROM pg_constraint")}
    indexes = {r["indexname"]: r["indexdef"] for r in await sql("SELECT indexname, indexdef FROM pg_indexes")}

    assert "uq_appointments_slot_id" not in constraints and "uq_appointments_slot_id" not in indexes
    definition = indexes["uq_appointments_slot_active"]
    assert "UNIQUE" in definition and "(slot_id)" in definition
    assert "<> 'cancelled'" in definition


async def test_U3_slot_constraints_and_indexes_exist(sql):
    constraints = {r["conname"]: r for r in await sql(
        "SELECT conname, contype, pg_get_constraintdef(oid) AS definition FROM pg_constraint"
    )}  # fmt: skip
    indexes = {r["indexname"]: r["indexdef"] for r in await sql("SELECT indexname, indexdef FROM pg_indexes")}
    extensions = {r["extname"] for r in await sql("SELECT extname FROM pg_extension")}

    assert "btree_gist" in extensions
    exclusion = constraints["ex_slots_no_overlap"]
    assert exclusion["contype"] == "x"
    assert "gist" in exclusion["definition"].lower() and "doctor_id WITH =" in exclusion["definition"]
    assert "tstzrange" in exclusion["definition"] and "&&" in exclusion["definition"]
    check = constraints["ck_slots_end_after_start"]
    assert check["contype"] == "c" and "end_at > start_at" in check["definition"]
    free_index = indexes["ix_slots_free_start_at"]
    assert "(start_at)" in free_index and "'free'" in free_index and "UNIQUE" not in free_index
