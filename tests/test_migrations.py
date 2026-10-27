"""Spec section 6, block U: the Alembic migrations on an empty database agree with the models.

Runs alembic in a subprocess against a scratch database created next to the test one (name contains `test`).
Slow (several seconds): `pytest -m "not slow"` skips it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = "medcenter_test_migrations"


def alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
    )


def assert_ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, f"alembic failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"


@pytest_asyncio.fixture(scope="module")
async def scratch_url(db_engine):
    base = make_url(TEST_DATABASE_URL)
    assert "test" in SCRATCH
    async with db_engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{SCRATCH}"'))
    url = base.set(database=SCRATCH).render_as_string(hide_password=False)
    yield url
    async with db_engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)'))


@pytest_asyncio.fixture(scope="module")
async def migrated(scratch_url):
    """Scratch database upgraded to head once for the module."""
    assert_ok(alembic(scratch_url, "upgrade", "head"))
    return scratch_url


async def test_U1_upgrade_downgrade_upgrade_and_check_are_clean(migrated):
    assert_ok(alembic(migrated, "downgrade", "-1"))
    assert_ok(alembic(migrated, "upgrade", "head"))

    check = alembic(migrated, "check")

    assert check.returncode == 0, f"models and migrations differ:\n{check.stdout}\n{check.stderr}"


async def test_U1_there_is_exactly_one_head(migrated):
    result = alembic(migrated, "heads")

    assert_ok(result)
    assert len([line for line in result.stdout.splitlines() if "(head)" in line]) == 1


async def test_U2_U3_migrated_schema_has_the_stage_2_constraints(migrated):
    engine = create_async_engine(migrated)
    try:
        async with engine.connect() as conn:
            constraints = {
                r.conname: (r.contype, r.definition)
                for r in await conn.execute(
                    text("SELECT conname, contype, pg_get_constraintdef(oid) AS definition FROM pg_constraint")
                )
            }
            indexes = {
                r.indexname: r.indexdef for r in await conn.execute(text("SELECT indexname, indexdef FROM pg_indexes"))
            }
            extensions = {r.extname for r in await conn.execute(text("SELECT extname FROM pg_extension"))}
    finally:
        await engine.dispose()

    assert "uq_appointments_slot_id" not in constraints and "uq_appointments_slot_id" not in indexes
    active = indexes["uq_appointments_slot_active"]
    assert "UNIQUE" in active and "(slot_id)" in active and "<> 'cancelled'" in active
    assert "btree_gist" in extensions
    kind, definition = constraints["ex_slots_no_overlap"]
    assert kind == "x" and "doctor_id WITH =" in definition and "tstzrange" in definition
    kind, definition = constraints["ck_slots_end_after_start"]
    assert kind == "c" and "end_at > start_at" in definition
    free = indexes["ix_slots_free_start_at"]
    assert "(start_at)" in free and "'free'" in free


async def test_U2_migrated_database_enforces_the_partial_unique_index(migrated):
    """Behaviour on the migrated schema, not only its shape: cancelled + active may coexist, two active may not."""
    engine = create_async_engine(migrated)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO users (id, email, password_hash, role, last_name, first_name) VALUES "
                "(1, 'd@example.com', 'x', 'doctor', 'Д', 'Д'), (2, 'a@example.com', 'x', 'athlete', 'А', 'А'), "
                "(3, 'b@example.com', 'x', 'athlete', 'Б', 'Б')"
            ))  # fmt: skip
            await conn.execute(text(
                "INSERT INTO slots (id, doctor_id, start_at, end_at, status) VALUES "
                "(1, 1, '2030-01-01 10:00+00', '2030-01-01 10:30+00', 'booked')"
            ))  # fmt: skip
            insert = "INSERT INTO appointments (slot_id, athlete_id, status, created_by) VALUES (1, :a, :s, :a)"
            await conn.execute(text(insert), {"a": 2, "s": "cancelled"})
            await conn.execute(text(insert), {"a": 3, "s": "booked"})
        with pytest.raises(Exception, match="uq_appointments_slot_active"):
            async with engine.begin() as conn:
                await conn.execute(text(insert), {"a": 2, "s": "booked"})
        with pytest.raises(Exception, match="ex_slots_no_overlap"):
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO slots (doctor_id, start_at, end_at, status) "
                    "VALUES (1, '2030-01-01 10:15+00', '2030-01-01 10:45+00', 'free')"
                ))  # fmt: skip
    finally:
        await engine.dispose()
