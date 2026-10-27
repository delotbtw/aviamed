"""Spec section 6, block D: POST /users (admin creates staff)."""

import pytest

from app.core.rbac import Role
from tests.helpers import STRONG_PASSWORD, staff_payload

URL = "/users"


async def test_D1_admin_creates_doctor_with_conclusion_flag(client, admin, specialty, sql):
    payload = staff_payload("doctor", specialty_id=specialty, cabinet="214", can_issue_conclusion=True)

    resp = await client.post(URL, json=payload, headers=admin.headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "doctor" and body["is_active"] is True and body["email"] == payload["email"]
    assert "password" not in body and "password_hash" not in body
    assert STRONG_PASSWORD not in resp.text
    [prof] = await sql("SELECT * FROM doctor_profiles WHERE user_id = :u", u=body["id"])
    assert prof["can_issue_conclusion"] is True and prof["specialty_id"] == specialty and prof["cabinet"] == "214"
    [user] = await sql("SELECT password_hash FROM users WHERE id = :u", u=body["id"])
    assert user["password_hash"].startswith("$argon2")
    assert STRONG_PASSWORD not in user["password_hash"]


async def test_D2_conclusion_flag_defaults_to_false(client, admin, specialty, sql):
    resp = await client.post(URL, json=staff_payload("doctor", specialty_id=specialty), headers=admin.headers)

    assert resp.status_code == 201
    [prof] = await sql("SELECT can_issue_conclusion FROM doctor_profiles WHERE user_id = :u", u=resp.json()["id"])
    assert prof["can_issue_conclusion"] is False


@pytest.mark.parametrize("role", ["registrar", "admin"])
@pytest.mark.parametrize("extra", [{"position": "Старший", "workplace": "Каб. 1"}, {}], ids=["with_profile", "bare"])
async def test_D3_registrar_and_admin_get_staff_profile(client, admin, sql, role, extra):
    resp = await client.post(URL, json=staff_payload(role, **extra), headers=admin.headers)

    assert resp.status_code == 201
    uid = resp.json()["id"]
    [prof] = await sql("SELECT * FROM staff_profiles WHERE user_id = :u", u=uid)
    assert prof["position"] == extra.get("position") and prof["workplace"] == extra.get("workplace")


async def test_D3_coach_gets_coach_profile(client, admin, sport, sql):
    resp = await client.post(URL, json=staff_payload("coach", sport_id=sport), headers=admin.headers)

    assert resp.status_code == 201
    [prof] = await sql("SELECT * FROM coach_profiles WHERE user_id = :u", u=resp.json()["id"])
    assert prof["sport_id"] == sport


async def test_D3_coach_without_sport_is_allowed(client, admin, sql):
    resp = await client.post(URL, json=staff_payload("coach"), headers=admin.headers)

    assert resp.status_code == 201
    [prof] = await sql("SELECT sport_id FROM coach_profiles WHERE user_id = :u", u=resp.json()["id"])
    assert prof["sport_id"] is None


async def test_D4_doctor_without_specialty_is_422(client, admin, sql):
    resp = await client.post(URL, json=staff_payload("doctor"), headers=admin.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM users WHERE email = 'new-doctor@example.com'") == []


async def test_D4_unknown_specialty_is_422_and_rolls_back(client, admin, sql):
    resp = await client.post(URL, json=staff_payload("doctor", specialty_id=99999), headers=admin.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM users WHERE email = 'new-doctor@example.com'") == []


async def test_D4_unknown_sport_for_coach_is_422(client, admin, sql):
    resp = await client.post(URL, json=staff_payload("coach", sport_id=99999), headers=admin.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM users WHERE email = 'new-coach@example.com'") == []


async def test_D5_athlete_role_is_422(client, admin, sql):
    resp = await client.post(URL, json=staff_payload("athlete"), headers=admin.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM users WHERE email = 'new-athlete@example.com'") == []


@pytest.mark.parametrize(
    ("role", "foreign"),
    [
        ("registrar", {"specialty_id": 1}),
        ("registrar", {"can_issue_conclusion": True}),
        ("admin", {"sport_id": 1}),
        ("coach", {"specialty_id": 1}),
        ("coach", {"position": "Тренер"}),
    ],
)
async def test_D5_foreign_role_fields_are_422(client, admin, specialty, sport, role, foreign):
    resp = await client.post(URL, json=staff_payload(role, **foreign), headers=admin.headers)

    assert resp.status_code == 422


async def test_D6_duplicate_email_is_409_also_in_other_case(client, admin, doctor, sql):
    for email in (doctor.email, doctor.email.upper()):
        resp = await client.post(URL, json=staff_payload("registrar", email=email), headers=admin.headers)
        assert resp.status_code == 409

    [row] = await sql("SELECT count(*) AS n FROM users WHERE lower(email) = :e", e=doctor.email.lower())
    assert row["n"] == 1


@pytest.mark.parametrize("actor_role", [Role.REGISTRAR, Role.DOCTOR, Role.ATHLETE, Role.COACH])
async def test_D7_non_admin_is_403(client, users_by_role, actor_role, sql):
    resp = await client.post(URL, json=staff_payload("registrar"), headers=users_by_role[actor_role].headers)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM users WHERE email = 'new-registrar@example.com'") == []


async def test_D7_no_token_is_401(client):
    assert (await client.post(URL, json=staff_payload("registrar"))).status_code == 401


async def test_D8_created_user_can_log_in_with_given_password(client, admin):
    payload = staff_payload("registrar")
    await client.post(URL, json=payload, headers=admin.headers)

    resp = await client.post("/auth/login", json={"email": payload["email"], "password": STRONG_PASSWORD})

    assert resp.status_code == 200


async def test_D8_email_is_normalized_to_lowercase(client, admin, sql):
    resp = await client.post(
        URL, json=staff_payload("registrar", email="  New-MIXED1@Example.com "), headers=admin.headers
    )

    assert resp.status_code == 201
    assert resp.json()["email"] == "new-mixed1@example.com"
    [row] = await sql("SELECT email FROM users WHERE id = :u", u=resp.json()["id"])
    assert row["email"] == "new-mixed1@example.com"


@pytest.mark.parametrize(
    "password",
    ["Ab1", "abcdefghijkl", "1234567890123", "a1" + "x" * 127, "new-registrar1@example.com"],
    ids=["short", "no_digit", "no_letter", "too_long", "equals_email"],
)
async def test_D_weak_password_is_422(client, admin, password):
    payload = staff_payload("registrar", email="new-registrar1@example.com", password=password)

    assert (await client.post(URL, json=payload, headers=admin.headers)).status_code == 422


async def test_D9_creation_is_audited_with_ids_only(client, admin, audit):
    payload = staff_payload("registrar", phone="+79990001122")
    resp = await client.post(URL, json=payload, headers=admin.headers)

    [row] = await audit("user_create")
    assert row["user_id"] == admin.id
    assert row["entity_type"] == "user" and row["entity_id"] == resp.json()["id"]
    dump = str(await audit())
    for secret in (payload["email"], payload["last_name"], payload["phone"], STRONG_PASSWORD):
        assert secret not in dump
