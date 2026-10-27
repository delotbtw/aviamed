"""Spec section 6, block F: PATCH /users/me (+ GET /users/me regression)."""

import pytest

from app.core.rbac import Role

URL = "/users/me"
STAFF = [Role.REGISTRAR, Role.DOCTOR, Role.COACH, Role.ADMIN]


async def get_user(sql, user_id):
    [row] = await sql("SELECT * FROM users WHERE id = :u", u=user_id)
    return row


@pytest.mark.parametrize("role", STAFF)
async def test_F1_staff_can_change_phone_and_first_name(client, users_by_role, sql, role):
    user = users_by_role[role]
    before = await get_user(sql, user.id)

    resp = await client.patch(URL, json={"phone": "+79995554433", "first_name": "Алексей"}, headers=user.headers)

    assert resp.status_code == 200
    assert resp.json()["phone"] == "+79995554433" and resp.json()["first_name"] == "Алексей"
    after = await get_user(sql, user.id)
    assert (after["phone"], after["first_name"]) == ("+79995554433", "Алексей")
    for untouched in ("last_name", "middle_name", "email", "role", "is_active", "password_hash"):
        assert after[untouched] == before[untouched]


async def test_F1_only_passed_fields_change(client, doctor, sql):
    resp = await client.patch(URL, json={"last_name": "Новиков"}, headers=doctor.headers)

    assert resp.status_code == 200
    row = await get_user(sql, doctor.id)
    assert row["last_name"] == "Новиков" and row["phone"] == "+79990000000" and row["first_name"] == "Иван"


async def test_F1_middle_name_null_clears_it(client, doctor, sql):
    resp = await client.patch(URL, json={"middle_name": None}, headers=doctor.headers)

    assert resp.status_code == 200
    assert (await get_user(sql, doctor.id))["middle_name"] is None


async def test_F2_athlete_can_change_phone(client, athlete, sql):
    resp = await client.patch(URL, json={"phone": "+79995554433"}, headers=athlete.headers)

    assert resp.status_code == 200
    assert (await get_user(sql, athlete.id))["phone"] == "+79995554433"


@pytest.mark.parametrize("field", ["first_name", "last_name", "middle_name"])
async def test_F2_athlete_cannot_change_name(client, athlete, sql, field):
    before = await get_user(sql, athlete.id)

    resp = await client.patch(URL, json={field: "Другое"}, headers=athlete.headers)

    assert resp.status_code == 403
    assert await get_user(sql, athlete.id) == before


async def test_F2_athlete_mixed_phone_and_name_changes_nothing(client, athlete, sql):
    before = await get_user(sql, athlete.id)

    resp = await client.patch(URL, json={"phone": "+79995554433", "last_name": "Другое"}, headers=athlete.headers)

    assert resp.status_code == 403
    assert await get_user(sql, athlete.id) == before


async def test_F3_phone_null_clears_phone(client, doctor, sql):
    resp = await client.patch(URL, json={"phone": None}, headers=doctor.headers)

    assert resp.status_code == 200 and resp.json()["phone"] is None
    assert (await get_user(sql, doctor.id))["phone"] is None


@pytest.mark.parametrize("field", ["first_name", "last_name"])
async def test_F3_required_name_cannot_be_null(client, doctor, sql, field):
    resp = await client.patch(URL, json={field: None}, headers=doctor.headers)

    assert resp.status_code == 422
    assert (await get_user(sql, doctor.id))[field] == {"first_name": "Иван", "last_name": "Иванов"}[field]


@pytest.mark.parametrize(
    ("field", "value"),
    [("email", "hacker1@example.com"), ("role", "admin"), ("is_active", False), ("id", 999)],
)
async def test_F4_forbidden_fields_are_422_and_change_nothing(client, doctor, sql, field, value):
    before = await get_user(sql, doctor.id)

    resp = await client.patch(URL, json={field: value}, headers=doctor.headers)

    assert resp.status_code == 422
    assert await get_user(sql, doctor.id) == before


async def test_F4_forbidden_field_next_to_valid_one_blocks_whole_request(client, doctor, sql):
    resp = await client.patch(URL, json={"phone": "+79995554433", "role": "admin"}, headers=doctor.headers)

    assert resp.status_code == 422
    assert (await get_user(sql, doctor.id))["phone"] == "+79990000000"


async def test_F5_empty_body_is_422(client, doctor):
    assert (await client.patch(URL, json={}, headers=doctor.headers)).status_code == 422


@pytest.mark.parametrize("phone", ["abc", "12", "+7 (999) 12", "9" * 40])
async def test_F5_bad_phone_is_422(client, doctor, sql, phone):
    resp = await client.patch(URL, json={"phone": phone}, headers=doctor.headers)

    assert resp.status_code == 422
    assert (await get_user(sql, doctor.id))["phone"] == "+79990000000"


async def test_F6_requires_authentication(client):
    assert (await client.patch(URL, json={"phone": "+79995554433"})).status_code == 401


async def test_F6_there_is_no_endpoint_to_edit_someone_elses_profile(client, admin, doctor):
    resp = await client.patch(f"/users/{doctor.id}", json={"phone": "+79995554433"}, headers=admin.headers)

    assert resp.status_code in (404, 405)


async def test_F6_update_is_audited_without_values(client, doctor, audit):
    await client.patch(URL, json={"phone": "+79995554433", "first_name": "Алексей"}, headers=doctor.headers)

    [row] = await audit("profile_update")
    assert row["user_id"] == doctor.id and row["entity_type"] == "user" and row["entity_id"] == doctor.id
    dump = str(await audit())
    assert "+79995554433" not in dump and "Алексей" not in dump


async def test_F7_get_me_regression(client, doctor):
    resp = await client.get(URL, headers=doctor.headers)

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"id", "email", "role", "last_name", "first_name", "middle_name", "phone", "is_active"}
    assert body["id"] == doctor.id and "password_hash" not in body
