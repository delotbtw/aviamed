"""`python -m app.cli seed-demo`: idempotent demo data, one user per role."""

from app.cli import seed_demo
from app.core.db import Database
from app.core.rbac import Role
from app.seed import DEMO_EMAILS, DEMO_PASSWORD, SPECIALTIES, SPORTS
from tests.conftest import TEST_DATABASE_URL


async def count(sql, table: str) -> int:
    [row] = await sql(f"SELECT count(*) AS n FROM {table}")
    return row["n"]


async def run_seed(db: Database):
    return await seed_demo(db, DEMO_PASSWORD)


async def test_seed_creates_reference_data_and_one_user_per_role(db_engine, clean_db, sql):
    db = Database(TEST_DATABASE_URL)
    try:
        logins = await run_seed(db)
    finally:
        await db.dispose()

    assert {login.role for login in logins} == set(Role)
    assert all(login.created for login in logins)
    assert await count(sql, "sports") == len(SPORTS)
    assert await count(sql, "specialties") == len(SPECIALTIES)
    users = {u["email"]: u for u in await sql("SELECT * FROM users")}
    assert set(users) == set(DEMO_EMAILS.values())
    assert all(u["is_active"] and u["password_hash"].startswith("$argon2") for u in users.values())
    [doctor] = await sql("SELECT * FROM doctor_profiles")
    [spec] = await sql("SELECT name FROM specialties WHERE id = :i", i=doctor["specialty_id"])
    assert spec["name"] == "Спортивная медицина" and doctor["can_issue_conclusion"] is True
    [athlete] = await sql("SELECT * FROM athlete_profiles")
    assert athlete["coach_id"] == users[DEMO_EMAILS[Role.COACH]]["id"]
    assert await count(sql, "consents") == 1


async def test_seed_is_idempotent_and_demo_users_can_log_in(client, sql):
    db = Database(TEST_DATABASE_URL)
    try:
        await run_seed(db)
        before = {t: await count(sql, t) for t in ("sports", "specialties", "users", "consents", "staff_profiles")}
        second = await run_seed(db)
    finally:
        await db.dispose()

    assert not any(login.created for login in second)
    assert {t: await count(sql, t) for t in before} == before
    resp = await client.post("/auth/login", json={"email": DEMO_EMAILS[Role.DOCTOR], "password": DEMO_PASSWORD})
    assert resp.status_code == 200


def test_seed_demo_refuses_without_debug_or_force(capsys):
    from app.cli import main

    assert main(["seed-demo"]) == 1
    assert "--force" in capsys.readouterr().err


async def test_seed_demo_never_prints_a_custom_password(db_engine, clean_db):
    import asyncio
    import os
    import subprocess
    import sys
    from pathlib import Path

    secret = "Custom-Secret-Passw0rd"
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL, "DEMO_PASSWORD": secret}
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "app.cli", "seed-demo", "--force"],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout + result.stderr
    assert "demo-doctor@example.com" in result.stdout
