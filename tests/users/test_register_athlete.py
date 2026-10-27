"""Spec section 6, block E: POST /users/athletes."""

from datetime import date, timedelta

import pytest

from app.core.rbac import Role
from app.repositories.user import AthleteProfileRepository
from tests.helpers import STRONG_PASSWORD, athlete_payload, tomorrow

URL = "/users/athletes"


async def counts(sql) -> tuple[int, int, int]:
    out = []
    for table in ("users", "athlete_profiles", "consents"):
        [row] = await sql(f"SELECT count(*) AS n FROM {table}")
        out.append(row["n"])
    return tuple(out)


async def test_E1_registrar_registers_athlete_with_profile_and_consent(client, registrar, coach, sport, sql):
    payload = athlete_payload(sport_id=sport, coach_id=coach.id, consent_paper_number="PD-77")

    resp = await client.post(URL, json=payload, headers=registrar.headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "athlete" and body["is_active"] is True
    assert "password" not in body and "password_hash" not in body
    [prof] = await sql("SELECT * FROM athlete_profiles WHERE user_id = :u", u=body["id"])
    assert (str(prof["birth_date"]), prof["sex"], prof["sport_id"], prof["coach_id"]) == (
        "2004-03-12",
        "male",
        sport,
        coach.id,
    )
    [consent] = await sql("SELECT * FROM consents WHERE user_id = :u", u=body["id"])
    assert consent["consent_type"] == "personal_data_health"
    assert consent["paper_number"] == "PD-77"
    assert consent["signed_at"] == date.today()
    assert consent["created_by"] == registrar.id
    assert consent["revoked_at"] is None


async def test_E1_optional_profile_fields_are_stored(client, registrar, sql):
    payload = athlete_payload(faculty="Мехмат", study_group="Б-101", training_stage="training", registry_number="R-5")

    resp = await client.post(URL, json=payload, headers=registrar.headers)

    assert resp.status_code == 201
    [prof] = await sql("SELECT * FROM athlete_profiles WHERE user_id = :u", u=resp.json()["id"])
    assert (prof["faculty"], prof["study_group"], prof["training_stage"], prof["registry_number"]) == (
        "Мехмат",
        "Б-101",
        "training",
        "R-5",
    )


async def test_E2_admin_registers_athlete(client, admin):
    assert (await client.post(URL, json=athlete_payload(), headers=admin.headers)).status_code == 201


@pytest.mark.parametrize("actor_role", [Role.DOCTOR, Role.ATHLETE, Role.COACH])
async def test_E3_other_roles_are_403(client, users_by_role, actor_role, sql):
    resp = await client.post(URL, json=athlete_payload(), headers=users_by_role[actor_role].headers)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM consents") == []


async def test_E3_no_token_is_401(client):
    assert (await client.post(URL, json=athlete_payload())).status_code == 401


async def test_E4_duplicate_email_is_409_without_side_effects(client, registrar, doctor, sql):
    before = await counts(sql)

    resp = await client.post(URL, json=athlete_payload(email=doctor.email.upper()), headers=registrar.headers)

    assert resp.status_code == 409
    assert await counts(sql) == before


async def test_E4_duplicate_paper_number_is_409_without_side_effects(client, registrar, sql):
    first = await client.post(URL, json=athlete_payload(consent_paper_number="DUP-1"), headers=registrar.headers)
    assert first.status_code == 201
    before = await counts(sql)

    resp = await client.post(
        URL,
        json=athlete_payload(email="other-athlete2@example.com", consent_paper_number="DUP-1"),
        headers=registrar.headers,
    )

    assert resp.status_code == 409
    assert await counts(sql) == before


async def test_E4_paper_number_may_be_reused_after_revocation(client, registrar, sql):
    await client.post(URL, json=athlete_payload(consent_paper_number="REV-1"), headers=registrar.headers)
    await sql("UPDATE consents SET revoked_at = current_date")

    resp = await client.post(
        URL,
        json=athlete_payload(email="other-athlete2@example.com", consent_paper_number="REV-1"),
        headers=registrar.headers,
    )

    assert resp.status_code == 201


async def test_E5_coach_id_must_be_active_coach(client, registrar, doctor, make_user, sql):
    inactive_coach = await make_user(Role.COACH, is_active=False)
    before = await counts(sql)

    for bad_id in (doctor.id, inactive_coach.id, 999999):
        resp = await client.post(URL, json=athlete_payload(coach_id=bad_id), headers=registrar.headers)
        assert resp.status_code == 422, bad_id

    assert await counts(sql) == before


async def test_E5_without_coach_id_athlete_is_created_with_null_coach(client, registrar, sql):
    resp = await client.post(URL, json=athlete_payload(), headers=registrar.headers)

    assert resp.status_code == 201
    [prof] = await sql("SELECT coach_id FROM athlete_profiles WHERE user_id = :u", u=resp.json()["id"])
    assert prof["coach_id"] is None


async def test_E6_unknown_sport_is_422(client, registrar, sql):
    resp = await client.post(URL, json=athlete_payload(sport_id=99999), headers=registrar.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM users WHERE role = 'athlete'") == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"birth_date": tomorrow()},
        {"birth_date": (date.today() - timedelta(days=121 * 366)).isoformat()},
        {"consent_signed_at": tomorrow()},
        {"consent_paper_number": ""},
        {"consent_paper_number": "   "},
        {"consent_paper_number": "N" * 65},
    ],
    ids=["birth_future", "birth_over_120y", "consent_future", "paper_empty", "paper_blank", "paper_65_chars"],
)
async def test_E7_invalid_dates_and_paper_number_are_422(client, registrar, sql, overrides):
    resp = await client.post(URL, json=athlete_payload(**overrides), headers=registrar.headers)

    assert resp.status_code == 422
    assert await sql("SELECT id FROM users") == [{"id": registrar.id}]


async def test_E7_paper_number_is_trimmed(client, registrar, sql):
    resp = await client.post(URL, json=athlete_payload(consent_paper_number="  PD-9  "), headers=registrar.headers)

    assert resp.status_code == 201
    [row] = await sql("SELECT paper_number FROM consents")
    assert row["paper_number"] == "PD-9"


@pytest.mark.parametrize(
    "missing", ["email", "password", "last_name", "first_name", "birth_date", "sex", "consent_paper_number"]
)
async def test_E7_required_fields(client, registrar, missing):
    payload = athlete_payload()
    del payload[missing]

    assert (await client.post(URL, json=payload, headers=registrar.headers)).status_code == 422


async def test_E7_weak_password_is_422(client, registrar):
    assert (
        await client.post(URL, json=athlete_payload(password="short1"), headers=registrar.headers)
    ).status_code == 422


async def test_E8_health_group_is_rejected(client, registrar, sql):
    resp = await client.post(URL, json=athlete_payload(health_group=2), headers=registrar.headers)

    assert resp.status_code == 422
    assert await sql("SELECT user_id FROM athlete_profiles") == []


async def test_E8_profile_health_group_is_null_on_success(client, registrar, sql):
    resp = await client.post(URL, json=athlete_payload(), headers=registrar.headers)

    [prof] = await sql("SELECT health_group FROM athlete_profiles WHERE user_id = :u", u=resp.json()["id"])
    assert prof["health_group"] is None


async def test_E9_consent_insert_failure_rolls_everything_back(client, registrar, sql):
    """DB-level failure injection (trigger) so the test does not depend on which repository inserts the consent."""
    ok = await client.post(URL, json=athlete_payload(email="first-athlete1@example.com"), headers=registrar.headers)
    assert ok.status_code == 201  # sanity: registration works before the fault is injected
    await sql(
        "CREATE OR REPLACE FUNCTION test_fail() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'boom'; END; $$ "
        "LANGUAGE plpgsql"
    )
    await sql("CREATE TRIGGER test_fail BEFORE INSERT ON consents FOR EACH ROW EXECUTE FUNCTION test_fail()")
    before = await counts(sql)

    try:
        resp = await client.post(
            URL,
            json=athlete_payload(email="second-athlete2@example.com", consent_paper_number="PD-2"),
            headers=registrar.headers,
        )
        assert resp.status_code >= 500  # the failure itself is not a client error
    except Exception:  # noqa: BLE001  (ASGITransport re-raises unhandled app exceptions)
        pass

    assert await counts(sql) == before


async def test_E10_registered_athlete_logs_in_sees_only_self_and_is_linked_to_coach(client, registrar, coach, db):
    payload = athlete_payload(coach_id=coach.id)
    created = (await client.post(URL, json=payload, headers=registrar.headers)).json()

    login = await client.post("/auth/login", json={"email": payload["email"], "password": STRONG_PASSWORD})
    assert login.status_code == 200
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["id"] == created["id"] and me.json()["email"] == payload["email"]

    profiles = await AthleteProfileRepository(db).list_by_coach(coach.id)
    assert [p.user_id for p in profiles] == [created["id"]]


async def test_E11_audit_records_ids_but_not_values(client, registrar, audit, sql):
    payload = athlete_payload(consent_paper_number="SECRET-NUM-42", phone="+79991112233")
    resp = await client.post(URL, json=payload, headers=registrar.headers)

    [reg] = await audit("athlete_register")
    assert reg["user_id"] == registrar.id and reg["entity_type"] == "user" and reg["entity_id"] == resp.json()["id"]
    [cons] = await audit("consent_create")
    [consent] = await sql("SELECT id FROM consents")
    assert cons["entity_type"] == "consent" and cons["entity_id"] == consent["id"]
    dump = str(await audit())
    for secret in ("SECRET-NUM-42", payload["email"], payload["last_name"], payload["phone"], STRONG_PASSWORD):
        assert secret not in dump
