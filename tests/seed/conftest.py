"""Fixtures of the demo seed tests (stage 2.1, spec 5 and 6.6)."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from app.cli import seed_demo
from app.core.db import Database
from app.seed import DEMO_PASSWORD
from tests.conftest import TEST_DATABASE_URL
from tests.schedule.support import assert_schedule_invariants

ROOT = Path(__file__).resolve().parent.parent.parent


async def run_seed() -> list:
    db = Database(TEST_DATABASE_URL)
    try:
        return await seed_demo(db, DEMO_PASSWORD)
    finally:
        await db.dispose()


@pytest_asyncio.fixture
async def seeded(db_engine, clean_db, sql):
    """Demo data created once by `seed_demo`; ends with the schedule invariants (spec 6.6 D-3)."""
    logins = await run_seed()
    yield logins
    await assert_schedule_invariants(sql)


@pytest.fixture
def cli():
    """`await cli("seed-demo", "--force", env={...})` -> CompletedProcess; DEBUG=false, ALLOW_DEMO_SEED=1 by default."""

    async def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        full_env = {
            **os.environ,
            "DATABASE_URL": TEST_DATABASE_URL,
            "DEBUG": "false",
            "ALLOW_DEMO_SEED": "1",
            **(env or {}),
        }
        return await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "app.cli", *args],
            cwd=ROOT,
            env=full_env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )

    return run
