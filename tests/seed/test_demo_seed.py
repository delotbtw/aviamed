"""Spec 2.1 section 5 / 6.6: extended demo seed (D-1 .. D-7). Written before the implementation (red)."""

import shutil
import subprocess
from collections import Counter

import pytest

from app.core.rbac import Role
from app.seed import DEMO_PASSWORD
from tests.seed.conftest import ROOT, run_seed

TABLES = ("users", "slots", "appointments", "status_history", "audit_log", "consents", "sports", "specialties")
MSK = "Europe/Moscow"
MSK_DAY = f"(s.start_at AT TIME ZONE '{MSK}')::date"
TODAY = f"(now() AT TIME ZONE '{MSK}')::date"


async def counts(sql) -> dict[str, int]:
    return {t: (await sql(f"SELECT count(*) AS n FROM {t}"))[0]["n"] for t in TABLES}  # noqa: S608


# --------------------------------------------------------------------------- D-1


async def test_D1_users_per_role_minimums(seeded, sql):
    rows = await sql("SELECT role, count(*) AS n FROM users GROUP BY role")
    assert {r["role"]: r["n"] for r in rows} == {
        Role.ADMIN.value: 1,
        Role.REGISTRAR.value: 2,
        Role.DOCTOR.value: 6,
        Role.COACH.value: 3,
        Role.ATHLETE.value: 40,
    }


async def test_D1_doctors_have_six_specialties_and_exactly_one_sports_doctor(seeded, sql):
    docs = await sql("SELECT specialty_id, can_issue_conclusion FROM doctor_profiles")
    assert len(docs) == 6
    assert len({d["specialty_id"] for d in docs}) == 6
    assert [d["can_issue_conclusion"] for d in docs].count(True) == 1
    [sports_doctor] = [d for d in docs if d["can_issue_conclusion"]]
    [spec] = await sql("SELECT name FROM specialties WHERE id = :i", i=sports_doctor["specialty_id"])
    assert spec["name"] == "Спортивная медицина"


async def test_D1_athletes_have_profile_coach_sport_and_consent_and_coaches_are_balanced(seeded, sql):
    athletes = await sql(
        "SELECT u.id, a.coach_id, a.sport_id FROM users u LEFT JOIN athlete_profiles a ON a.user_id = u.id "
        "WHERE u.role = 'athlete'"
    )
    assert len(athletes) == 40
    coach_ids = {r["id"] for r in await sql("SELECT id FROM users WHERE role = 'coach'")}
    assert all(a["coach_id"] in coach_ids and a["sport_id"] is not None for a in athletes)
    per_coach = Counter(a["coach_id"] for a in athletes)
    assert set(per_coach) == coach_ids
    assert max(per_coach.values()) - min(per_coach.values()) <= 2  # "поровну ±1"
    consents = await sql(
        "SELECT user_id, paper_number FROM consents WHERE user_id = ANY(:ids)", ids=[a["id"] for a in athletes]
    )
    assert {c["user_id"] for c in consents} == {a["id"] for a in athletes}
    assert all(c["paper_number"].startswith("DEMO-") for c in consents)


async def test_D1_reference_data_is_seeded(seeded, sql):
    from app.seed import SPECIALTIES, SPORTS

    assert (await counts(sql))["sports"] == len(SPORTS)
    assert (await counts(sql))["specialties"] == len(SPECIALTIES)


async def test_D1_emails_follow_the_naming_scheme(seeded, sql):
    rows = await sql("SELECT email, role FROM users")
    emails = {r["email"] for r in rows}
    for role, n in (("admin", 1), ("registrar", 2), ("doctor", 6), ("coach", 3), ("athlete", 40)):
        expected = {f"demo-{role}@example.com"} | {f"demo-{role}-{i}@example.com" for i in range(2, n + 1)}
        assert expected <= emails, role
    assert all(r["email"].startswith("demo-") and r["email"].endswith("@example.com") for r in rows)


# --------------------------------------------------------------------------- D-2


async def test_D2_every_doctor_has_past_future_and_closed_future_slots(seeded, sql):
    rows = await sql(
        f"""SELECT d.user_id,
               count(*) FILTER (WHERE {MSK_DAY} BETWEEN {TODAY} - 14 AND {TODAY} - 1) AS past,
               count(*) FILTER (WHERE {MSK_DAY} BETWEEN {TODAY} + 1 AND {TODAY} + 14) AS future,
               count(*) FILTER (WHERE {MSK_DAY} > {TODAY} AND s.status = 'closed') AS closed_future
            FROM doctor_profiles d LEFT JOIN slots s ON s.doctor_id = d.user_id GROUP BY d.user_id"""  # noqa: S608
    )
    assert len(rows) == 6
    for r in rows:
        assert r["past"] >= 14 * 12 and r["future"] >= 14 * 12, r  # 6 hours of 30-minute slots per day
        assert r["closed_future"] > 0, r


async def test_D2_slot_grid_is_30_minutes_inside_moscow_working_windows(seeded, sql):
    rows = await sql(
        f"""SELECT DISTINCT to_char(s.start_at AT TIME ZONE '{MSK}', 'HH24:MI') AS t,
               (s.end_at - s.start_at) AS length
            FROM slots s"""
    )
    starts = {r["t"] for r in rows}
    expected = {f"{h:02d}:{m:02d}" for h in (9, 10, 11, 14, 15, 16) for m in (0, 30)}
    assert starts == expected
    assert {r["length"].total_seconds() for r in rows} == {1800}


async def test_D2_no_duplicate_slot_per_doctor_and_start(seeded, sql):
    assert await sql("SELECT 1 FROM slots GROUP BY doctor_id, start_at HAVING count(*) > 1") == []


async def test_D2_appointment_minimums_by_status_and_period(seeded, sql):
    rows = await sql(
        f"""SELECT a.status AS st,
               CASE WHEN {MSK_DAY} < {TODAY} THEN 'past' WHEN {MSK_DAY} = {TODAY} THEN 'today' ELSE 'future' END AS per,
               count(*) AS n
            FROM appointments a JOIN slots s ON s.id = a.slot_id GROUP BY 1, 2"""  # noqa: S608
    )
    got = {(r["per"], r["st"]): r["n"] for r in rows}
    minimums = {
        ("past", "done"): 8,
        ("past", "no_show"): 4,
        ("past", "cancelled"): 4,
        ("today", "arrived"): 2,
        ("today", "booked"): 2,
        ("future", "booked"): 15,
        ("future", "cancelled"): 3,
    }
    short = {k: (got.get(k, 0), need) for k, need in minimums.items() if got.get(k, 0) < need}
    assert short == {}, f"(have, need): {short}"


async def test_D2_slot_status_matches_appointment_status(seeded, sql):
    rows = await sql(
        "SELECT a.status AS ast, s.status AS sst, count(*) AS n FROM appointments a JOIN slots s ON s.id = a.slot_id "
        "GROUP BY 1, 2"
    )
    assert rows, "no appointments seeded"
    for r in rows:
        expected = "free" if r["ast"] == "cancelled" else "booked"
        assert r["sst"] == expected, r


async def test_D2_athletes_stay_within_active_appointment_limit(seeded, sql):
    from app.core.config import get_settings

    limit = get_settings().max_active_appointments
    assert await sql("SELECT 1 FROM appointments"), "no appointments seeded"
    rows = await sql(
        "SELECT athlete_id, count(*) AS n FROM appointments WHERE status IN ('booked', 'arrived') GROUP BY 1 "
        "HAVING count(*) > :m",
        m=limit,
    )
    assert rows == []


# --------------------------------------------------------------------------- D-3


async def test_D3_every_appointment_has_a_correct_history_chain_and_audit(seeded, sql):
    appointments = await sql("SELECT id, status FROM appointments ORDER BY id")
    assert appointments
    history = {}
    for h in await sql(
        "SELECT entity_id, from_status, to_status FROM status_history WHERE entity_type = 'appointment' ORDER BY id"
    ):
        history.setdefault(h["entity_id"], []).append((h["from_status"], h["to_status"]))
    chains = {
        "booked": [(None, "booked")],
        "arrived": [(None, "booked"), ("booked", "arrived")],
        "done": [(None, "booked"), ("booked", "arrived"), ("arrived", "done")],
        "no_show": [(None, "booked"), ("booked", "no_show")],
        "cancelled": [(None, "booked"), ("booked", "cancelled")],
    }
    wrong = {a["id"]: history.get(a["id"]) for a in appointments if history.get(a["id"]) != chains[a["status"]]}
    assert wrong == {}

    audit = Counter((r["action"], r["entity_id"]) for r in await sql("SELECT action, entity_id FROM audit_log"))
    for a in appointments:
        assert audit[("appointment_book", a["id"])] == 1, a
        for status, action in (("cancelled", "appointment_cancel"), ("no_show", "appointment_no_show")):
            assert audit[(action, a["id"])] == (1 if a["status"] == status else 0), a
        if a["status"] in ("arrived", "done"):
            assert audit[("appointment_arrive", a["id"])] == 1, a


async def test_D3_cancelled_appointments_free_their_slot_in_history(seeded, sql):
    assert await sql("SELECT 1 FROM appointments WHERE status = 'cancelled'"), "no cancelled appointments seeded"
    rows = await sql(
        """SELECT a.id FROM appointments a WHERE a.status = 'cancelled' AND NOT EXISTS (
             SELECT 1 FROM status_history h WHERE h.entity_type = 'slot' AND h.entity_id = a.slot_id
               AND h.from_status = 'booked' AND h.to_status = 'free')"""
    )
    assert rows == []


# --------------------------------------------------------------------------- D-4


async def test_D4_second_run_changes_nothing(seeded, sql):
    before = await counts(sql)
    assert before["appointments"] > 0 and before["slots"] > 0
    snapshot = await sql("SELECT id, status FROM appointments ORDER BY id")

    second = await run_seed()

    assert not any(login.created for login in second)
    assert await counts(sql) == before
    assert await sql("SELECT id, status FROM appointments ORDER BY id") == snapshot


async def test_EXTRA_seed_is_deterministic_across_fresh_databases(db_engine, clean_db, sql):
    async def people() -> list[tuple]:
        rows = await sql("SELECT email, role, last_name, first_name, middle_name FROM users ORDER BY email")
        return [tuple(r.values()) for r in rows]

    await run_seed()
    first = await people()
    await sql("TRUNCATE users RESTART IDENTITY CASCADE")
    await run_seed()

    assert first and await people() == first


# --------------------------------------------------------------------------- D-5


async def test_D5_cli_without_debug_or_force_exits_1_and_writes_nothing(db_engine, clean_db, sql, cli):
    result = await cli("seed-demo")

    assert result.returncode == 1
    assert "--force" in result.stderr
    assert (await counts(sql)) == dict.fromkeys(TABLES, 0)


async def test_S2_cli_refuses_without_the_second_key_and_writes_nothing(db_engine, clean_db, sql, cli):
    result = await cli("seed-demo", "--force", env={"ALLOW_DEMO_SEED": ""})

    assert result.returncode == 1
    assert "ALLOW_DEMO_SEED" in result.stderr
    assert (await counts(sql)) == dict.fromkeys(TABLES, 0)


async def test_S2_cli_refuses_a_database_with_real_users(db_engine, clean_db, sql, cli, make_user):
    await make_user(Role.DOCTOR, email="real.doctor@clinic.ru")

    result = await cli("seed-demo", "--force")

    assert result.returncode == 1
    assert "похоже на боевую БД" in result.stderr
    assert (await counts(sql))["slots"] == 0


async def test_D5_cli_with_force_succeeds_and_prints_logins_by_role(db_engine, clean_db, sql, cli):
    result = await cli("seed-demo", "--force")

    assert result.returncode == 0, result.stderr
    for role in Role:
        assert f"demo-{role.value}@example.com" in result.stdout
    assert (await counts(sql))["users"] == 52
    assert DEMO_PASSWORD in result.stdout  # the public default is shown


async def test_D5_cli_output_lists_first_three_athletes_only(db_engine, clean_db, cli):
    result = await cli("seed-demo", "--force")

    assert result.returncode == 0, result.stderr
    for n in (2, 3):
        assert f"demo-athlete-{n}@example.com" in result.stdout
    assert "demo-athlete-4@example.com" not in result.stdout
    assert "37" in result.stdout  # "…и ещё 37"


async def test_D5_cli_runs_with_debug_true_without_force(db_engine, clean_db, sql, cli):
    result = await cli("seed-demo", env={"DEBUG": "true"})

    assert result.returncode == 0, result.stderr
    assert (await counts(sql))["users"] == 52


async def test_D5_custom_demo_password_is_never_printed(db_engine, clean_db, cli):
    secret = "Custom-Secret-Passw0rd"

    result = await cli("seed-demo", "--force", env={"DEMO_PASSWORD": secret})

    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout + result.stderr
    assert "demo-doctor@example.com" in result.stdout


async def test_D5_cli_second_run_reports_exists_and_adds_nothing(db_engine, clean_db, sql, cli):
    await cli("seed-demo", "--force")
    before = await counts(sql)

    result = await cli("seed-demo", "--force")

    assert result.returncode == 0, result.stderr
    assert "exists" in result.stdout
    assert await counts(sql) == before


# --------------------------------------------------------------------------- D-6


@pytest.mark.parametrize("role", [r.value for r in Role])
async def test_D6_first_demo_user_of_each_role_logs_in(seeded, client, role):
    resp = await client.post("/auth/login", json={"email": f"demo-{role}@example.com", "password": DEMO_PASSWORD})
    assert resp.status_code == 200


async def test_D6_all_demo_users_share_the_password_hash_policy(seeded, sql):
    rows = await sql("SELECT password_hash, is_active FROM users")
    assert len(rows) == 52
    assert all(r["is_active"] and r["password_hash"].startswith("$argon2") for r in rows)


# --------------------------------------------------------------------------- D-7

needs_make = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")


def make(*args: str, dry: bool = True, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        ["make", *(["-n"] if dry else []), *args, *(f"{k}={v}" for k, v in env.items())],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


@needs_make
@pytest.mark.parametrize("target", ["seed-demo", "seed"])
def test_D7_make_refuses_without_confirm_local(target):
    # `make -n` never runs the recipe's guard (`test ...`), so the refusal is checked on a real run: it must stop
    # before docker is reached (a missing target also gives a non-zero code, hence the explicit message check).
    result = make(target, dry=False)
    assert result.returncode != 0
    assert "CONFIRM=local" in result.stdout + result.stderr
    assert "No rule to make target" not in result.stderr


@needs_make
@pytest.mark.parametrize("target", ["seed-demo", "seed"])
def test_D7_make_with_confirm_local_runs_the_cli_with_force(target):
    result = make(target, CONFIRM="local")
    assert result.returncode == 0, result.stderr
    assert "app.cli seed-demo --force" in result.stdout
