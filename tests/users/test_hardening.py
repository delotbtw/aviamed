"""Review round 1: DB-level uniqueness of paper consent numbers and its race."""

import asyncio

import pytest
from sqlalchemy.exc import IntegrityError

from tests.helpers import athlete_payload


async def test_parallel_registrations_with_same_paper_number_create_one_consent(client, registrar, sql):
    async def register(n: int):
        payload = athlete_payload(email=f"race{n}@example.com", consent_paper_number="RACE-1")
        return await client.post("/users/athletes", json=payload, headers=registrar.headers)

    resps = await asyncio.gather(*(register(n) for n in range(4)))

    assert sorted(r.status_code for r in resps) == [201, 409, 409, 409]
    assert len(await sql("SELECT id FROM consents")) == 1
    assert len(await sql("SELECT id FROM users WHERE role = 'athlete'")) == 1


async def test_unique_index_rejects_duplicate_active_number_but_allows_revoked(sql):
    await sql(
        "INSERT INTO users (email, password_hash, role, last_name, first_name) "
        "VALUES ('u1@example.com','x','admin','a','b')"
    )
    insert = (
        "INSERT INTO consents (user_id, consent_type, paper_number, signed_at, revoked_at) "
        "VALUES (1, 'personal_data_health', 'N-1', current_date, {revoked})"
    )
    await sql(insert.format(revoked="current_date"))
    await sql(insert.format(revoked="NULL"))  # a revoked consent frees the number

    with pytest.raises(IntegrityError):
        await sql(insert.format(revoked="NULL"))


async def test_list_active_coaches_returns_only_active_coaches(db, make_user, doctor, athlete):
    from app.core.rbac import Role
    from app.repositories.user import UserRepository

    active = await make_user(Role.COACH)
    await make_user(Role.COACH, is_active=False)

    ids = {u.id for u in await UserRepository(db).list_active_coaches()}

    assert active.id in ids
    assert doctor.id not in ids and athlete.id not in ids
    assert len(ids) == 2  # the `athlete` fixture brings its own coach


async def test_parallel_user_creation_with_same_email_creates_one_user(client, admin, sql):
    from tests.helpers import staff_payload

    payload = staff_payload("registrar", email="same-email1@example.com")

    resps = await asyncio.gather(*(client.post("/users", json=payload, headers=admin.headers) for _ in range(4)))

    assert sorted(r.status_code for r in resps) == [201, 409, 409, 409]
    assert len(await sql("SELECT id FROM users WHERE email = 'same-email1@example.com'")) == 1
    assert len(await sql("SELECT user_id FROM staff_profiles")) == 2  # fixture admin + the new registrar
