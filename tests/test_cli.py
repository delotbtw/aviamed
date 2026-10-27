"""Spec section 6, block I and 7.1: `python -m app.cli create-admin`.

Assumed contract (spec: "пароль из интерактивного ввода или переменной окружения"): the password is read from the
environment variable ADMIN_PASSWORD when stdin is not a TTY.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

from tests.conftest import TEST_DATABASE_URL
from tests.helpers import STRONG_PASSWORD

ROOT = Path(__file__).resolve().parent.parent
EMAIL = "first-admin1@example.com"


async def run_cli(email: str = EMAIL):
    import os

    env = {
        **os.environ,
        "DATABASE_URL": TEST_DATABASE_URL,
        "ADMIN_PASSWORD": STRONG_PASSWORD,
        "SECRET_KEY": "test-secret-key-not-for-production-0123456789",
    }
    return await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "app.cli", "create-admin", "--email", email],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )


async def test_I1_create_admin_creates_active_admin_with_argon2_hash(db_engine, clean_db, sql):
    result = await run_cli()

    assert result.returncode == 0, result.stderr
    [user] = await sql("SELECT * FROM users WHERE email = :e", e=EMAIL)
    assert user["role"] == "admin" and user["is_active"] is True
    assert user["password_hash"].startswith("$argon2")
    assert len(await sql("SELECT user_id FROM staff_profiles WHERE user_id = :u", u=user["id"])) == 1
    assert STRONG_PASSWORD not in result.stdout + result.stderr


async def test_I1_created_admin_can_log_in(client, sql):
    assert (await run_cli()).returncode == 0

    resp = await client.post("/auth/login", json={"email": EMAIL, "password": STRONG_PASSWORD})

    assert resp.status_code == 200


async def test_I1_second_run_fails_with_message_and_no_duplicate(db_engine, clean_db, sql):
    assert (await run_cli()).returncode == 0

    result = await run_cli()

    assert result.returncode != 0
    assert (result.stdout + result.stderr).strip(), "an understandable message is expected"
    assert "Traceback" not in result.stderr
    assert STRONG_PASSWORD not in result.stdout + result.stderr
    assert len(await sql("SELECT id FROM users WHERE email = :e", e=EMAIL)) == 1
