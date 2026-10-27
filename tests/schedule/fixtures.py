"""Fixtures of the stage 2 tests (registered as a plugin from tests/conftest.py).

Contract with the implementation (spec section 12): `app.core.clock.get_clock` is the only source of "now" and is
replaced here through `app.dependency_overrides`; settings are changed through environment variables + a cleared
`get_settings` cache, so both `Depends(get_settings)` and direct `get_settings()` calls see them.
"""

from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import get_settings
from app.core.rbac import Role
from app.main import app
from tests.schedule.support import NOW, FakeClock, assert_schedule_invariants, at, book


@pytest.fixture
def clock():
    fake = FakeClock(NOW)
    try:
        from app.core.clock import get_clock
    except ImportError:
        # Before the implementation: run against the stubs so that tests fail on the missing behaviour (501/404),
        # while `test_contract.py::test_clock_dependency_exists` reports the missing module itself.
        yield fake
        return
    app.dependency_overrides[get_clock] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_clock, None)


@pytest.fixture
def settings_env(monkeypatch):
    """`settings_env(max_active_appointments=3, schedule_timezone="Asia/Yekaterinburg")`."""

    def apply(**values) -> None:
        for key, value in values.items():
            monkeypatch.setenv(key.upper(), str(value))
        get_settings.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def second_specialty(session_factory) -> int:
    from app.models.reference import Specialty

    async with session_factory() as s:
        obj = Specialty(name="Кардиология")
        s.add(obj)
        await s.commit()
        return obj.id


@pytest_asyncio.fixture
async def doctor2(make_user, second_specialty):
    """Second doctor: other specialty, has a cabinet, distinguishable surname. (`doctor` has no cabinet.)"""
    return await make_user(
        Role.DOCTOR, specialty_id=second_specialty, cabinet="305", last_name="Кузнецов", first_name="Пётр"
    )


@pytest_asyncio.fixture
async def athlete2(make_user):
    return await make_user(Role.ATHLETE, last_name="Петров", first_name="Пётр", middle_name=None)


@pytest_asyncio.fixture
async def athlete3(make_user):
    return await make_user(Role.ATHLETE, last_name="Сидоров", first_name="Сидор", birth_date=date(2001, 1, 9))


@pytest_asyncio.fixture
async def make_slot(sql):
    """Direct SQL insert (independent of the create endpoint). Non-free status also writes the slot's history row."""

    async def go(doctor, start: datetime | None = None, *, minutes: int = 30, status: str = "free") -> int:
        start = start or at(10)
        [row] = await sql(
            "INSERT INTO slots (doctor_id, start_at, end_at, status, created_by) "
            "VALUES (:d, :s, :e, :st, :d) RETURNING id",
            d=doctor.id,
            s=start,
            e=start + timedelta(minutes=minutes),
            st=status,
        )
        if status != "free":
            await sql(
                "INSERT INTO status_history (entity_type, entity_id, from_status, to_status, changed_by) "
                "VALUES ('slot', :i, 'free', :st, :d)",
                i=row["id"],
                st=status,
                d=doctor.id,
            )
        return row["id"]

    return go


@pytest_asyncio.fixture
async def make_booking(client):
    """Books through the API (athlete books themselves) and returns the appointment id."""

    async def go(slot_id: int, athlete, **extra) -> int:
        resp = await book(client, athlete, slot_id, **extra)
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    return go


@pytest_asyncio.fixture
async def insert_booking(sql):
    """A booking made by direct SQL (what `POST /schedule/appointments` must leave behind), for tests that must not
    depend on the booking endpoint, e.g. the permission matrix."""

    async def go(slot_id: int, athlete, *, created_by=None, case_id: int | None = None) -> int:
        actor = (created_by or athlete).id
        [row] = await sql(
            "INSERT INTO appointments (slot_id, athlete_id, case_id, status, created_by) "
            "VALUES (:s, :a, :c, 'booked', :by) RETURNING id",
            s=slot_id,
            a=athlete.id,
            c=case_id,
            by=actor,
        )
        await sql("UPDATE slots SET status = 'booked' WHERE id = :s", s=slot_id)
        await sql(
            "INSERT INTO status_history (entity_type, entity_id, from_status, to_status, changed_by) VALUES "
            "('appointment', :i, NULL, 'booked', :by), ('slot', :s, 'free', 'booked', :by)",
            i=row["id"],
            s=slot_id,
            by=actor,
        )
        return row["id"]

    return go


@pytest_asyncio.fixture
async def force_status(sql):
    """Put an appointment into a status the API cannot reach yet (or cheaply), keeping the history consistent."""

    async def go(appointment_id: int, status: str) -> None:
        previous = {"arrived": "booked", "no_show": "booked", "done": "arrived", "cancelled": "booked"}[status]
        await sql(
            "UPDATE appointments SET status = :st, cancelled_at = CASE WHEN :st = 'cancelled' THEN now() END "
            "WHERE id = :i",
            st=status,
            i=appointment_id,
        )
        await sql(
            "INSERT INTO status_history (entity_type, entity_id, from_status, to_status) "
            "VALUES ('appointment', :i, :f, :t)",
            i=appointment_id,
            f=previous,
            t=status,
        )
        if status == "cancelled":
            await sql(
                "UPDATE slots SET status = 'free' WHERE id = (SELECT slot_id FROM appointments WHERE id = :i)",
                i=appointment_id,
            )

    return go


@pytest_asyncio.fixture
async def make_case(session_factory, sql):
    """Medical case of an athlete (stage 3 owns case creation; stage 2 only needs rows to link and to move)."""

    async def go(athlete, status: str = "registered", opened_by=None) -> int:
        from app.models.enums import CaseStatus, ProgramCode
        from app.models.medical import MedicalCase
        from app.models.reference import ExamProgram

        async with session_factory() as s:
            program = await s.scalar(select(ExamProgram).limit(1))
            if program is None:
                program = ExamProgram(code=ProgramCode.BASE, name="Базовая", validity_months=12)
                s.add(program)
                await s.flush()
            case = MedicalCase(
                athlete_id=athlete.id,
                program_id=program.id,
                status=CaseStatus(status),
                opened_by=(opened_by or athlete).id,
                opened_at=NOW,
            )
            s.add(case)
            await s.commit()
            return case.id

    return go


@pytest_asyncio.fixture
async def schedule_invariants(sql):
    """assert_schedule_invariants after the test (teardown runs before `sql` / `clean_db` truncate the data)."""
    yield
    await assert_schedule_invariants(sql)
