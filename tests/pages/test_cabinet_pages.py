"""Spec section 6, block H (H-9..H-13): cabinet, role-based access, forms."""

import pytest

from app.core.rbac import Role
from tests.helpers import STRONG_PASSWORD, athlete_payload, location, set_cookie_headers

ATHLETE_LINK = "Зарегистрировать спортсмена"
USER_LINK = "Создать пользователя"
PASSWORD_LINK = "Сменить пароль"


@pytest.mark.parametrize(
    ("role", "shown", "hidden"),
    [
        (Role.REGISTRAR, [ATHLETE_LINK, PASSWORD_LINK], [USER_LINK]),
        (Role.ADMIN, [ATHLETE_LINK, USER_LINK, PASSWORD_LINK], []),
        (Role.ATHLETE, [PASSWORD_LINK], [ATHLETE_LINK, USER_LINK]),
        (Role.DOCTOR, [PASSWORD_LINK], [ATHLETE_LINK, USER_LINK]),
        (Role.COACH, [PASSWORD_LINK], [ATHLETE_LINK, USER_LINK]),
    ],
)
async def test_H9_cabinet_shows_name_and_role_links(client, users_by_role, web_session, role, shown, hidden):
    user = users_by_role[role]
    web_session(client, user)

    resp = await client.get("/cabinet")

    assert resp.status_code == 200
    assert "Иванов" in resp.text and "Иван" in resp.text
    for text in shown:
        assert text in resp.text
    for text in hidden:
        assert text not in resp.text


@pytest.mark.parametrize(
    ("role", "path", "expected"),
    [
        (Role.ATHLETE, "/cabinet/athletes/new", 403),
        (Role.ATHLETE, "/cabinet/users/new", 403),
        (Role.REGISTRAR, "/cabinet/users/new", 403),
        (Role.REGISTRAR, "/cabinet/athletes/new", 200),
        (Role.ADMIN, "/cabinet/athletes/new", 200),
        (Role.ADMIN, "/cabinet/users/new", 200),
        (Role.DOCTOR, "/cabinet/athletes/new", 403),
        (Role.COACH, "/cabinet/users/new", 403),
    ],
)
async def test_H10_direct_access_by_role(client, users_by_role, web_session, role, path, expected):
    web_session(client, users_by_role[role])

    resp = await client.get(path)

    assert resp.status_code == expected
    assert "text/html" in resp.headers["content-type"]  # 403 is an HTML stub page, not JSON


async def test_H10_unauthenticated_forms_redirect_to_session(client):
    resp = await client.get("/cabinet/athletes/new")

    assert resp.status_code == 303 and location(resp) == "/auth/session?next=/cabinet/athletes/new"


async def test_H11_registrar_form_creates_athlete(client, registrar, web_session, sql):
    web_session(client, registrar)
    data = athlete_payload()

    resp = await client.post("/cabinet/athletes/new", data=data, headers={"HX-Request": "true"})

    assert resp.status_code in (200, 201)
    assert "Создан" in resp.text
    [row] = await sql("SELECT role, is_active FROM users WHERE email = :e", e=data["email"])
    assert row == {"role": "athlete", "is_active": True}
    [c] = await sql("SELECT paper_number, created_by FROM consents")
    assert c["created_by"] == registrar.id


async def test_H11_success_fragment_resets_the_form(client, registrar, web_session):
    web_session(client, registrar)

    resp = await client.post("/cabinet/athletes/new", data=athlete_payload(), headers={"HX-Request": "true"})

    assert athlete_payload()["last_name"] not in resp.text.split("Создан", 1)[1] or 'value=""' in resp.text


async def test_H11_duplicate_email_returns_409_form_keeping_values_but_not_password(
    client, registrar, doctor, web_session
):
    web_session(client, registrar)
    data = athlete_payload(email=doctor.email, last_name="Уникальнофамилов")

    resp = await client.post("/cabinet/athletes/new", data=data, headers={"HX-Request": "true"})

    assert resp.status_code == 409
    assert "Уникальнофамилов" in resp.text  # entered value is preserved
    assert STRONG_PASSWORD not in resp.text  # password is never echoed back
    assert "<form" in resp.text or "error" in resp.text.lower() or "занят" in resp.text.lower()


async def test_H11_validation_error_returns_422_with_message_and_values(client, registrar, web_session, sql):
    web_session(client, registrar)
    data = athlete_payload(consent_paper_number="   ", last_name="Уникальнофамилов")

    resp = await client.post("/cabinet/athletes/new", data=data, headers={"HX-Request": "true"})

    assert resp.status_code == 422
    assert "Уникальнофамилов" in resp.text and STRONG_PASSWORD not in resp.text
    assert await sql("SELECT id FROM consents") == []


async def test_H11_form_post_by_athlete_is_403(client, athlete, web_session, sql):
    web_session(client, athlete)

    resp = await client.post("/cabinet/athletes/new", data=athlete_payload())

    assert resp.status_code == 403
    assert await sql("SELECT id FROM consents") == []


async def test_H12_user_form_has_role_dependent_doctor_fields(client, admin, web_session, specialty):
    web_session(client, admin)

    resp = await client.get("/cabinet/users/new")

    html = resp.text
    assert 'name="specialty_id"' in html
    assert 'name="cabinet"' in html
    assert 'name="can_issue_conclusion"' in html
    assert ":hidden=" in html  # fieldsets are toggled with :hidden (a server-rendered hidden attribute beats x-show)
    assert "x-data" in html
    assert 'name="role"' in html


async def test_H12_admin_creates_staff_through_the_form(client, admin, web_session, specialty, sql):
    web_session(client, admin)
    data = {
        "email": "form-doctor1@example.com",
        "password": STRONG_PASSWORD,
        "role": "doctor",
        "last_name": "Врачев",
        "first_name": "Врач",
        "specialty_id": str(specialty),
        "can_issue_conclusion": "true",
    }

    resp = await client.post("/cabinet/users/new", data=data, headers={"HX-Request": "true"})

    assert resp.status_code in (200, 201) and "Создан" in resp.text
    [prof] = await sql("SELECT can_issue_conclusion FROM doctor_profiles")
    assert prof["can_issue_conclusion"] is True


async def test_H13_password_page_has_three_fields(client, doctor, web_session):
    web_session(client, doctor)

    resp = await client.get("/cabinet/password")

    assert resp.status_code == 200
    assert 'name="old_password"' in resp.text and 'name="new_password"' in resp.text
    assert resp.text.count('type="password"') >= 3


async def test_H13_password_change_clears_cookies_and_redirects_to_login(client, doctor, sql):
    login = await client.post("/login", data={"email": doctor.email, "password": doctor.password})
    assert login.status_code == 303

    resp = await client.post(
        "/cabinet/password",
        data={"old_password": doctor.password, "new_password": STRONG_PASSWORD, "new_password_repeat": STRONG_PASSWORD},
    )

    assert resp.status_code == 303 and location(resp).startswith("/login")
    cookies = set_cookie_headers(resp)
    assert "access_token" in cookies and "Max-Age=0" in cookies["access_token"]
    assert "refresh_token" in cookies and "Max-Age=0" in cookies["refresh_token"]
    assert (
        await client.post("/auth/login", json={"email": doctor.email, "password": STRONG_PASSWORD})
    ).status_code == 200
    active = await sql("SELECT id FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=doctor.id)
    assert len(active) == 1  # only the session created by the check above


async def test_H13_login_page_shows_password_changed_message(client, doctor):
    await client.post("/login", data={"email": doctor.email, "password": doctor.password})
    resp = await client.post(
        "/cabinet/password",
        data={"old_password": doctor.password, "new_password": STRONG_PASSWORD, "new_password_repeat": STRONG_PASSWORD},
    )

    page = await client.get(resp.headers["location"])

    assert page.status_code == 200 and "Пароль изменён, войдите заново" in page.text


async def test_H13_wrong_old_password_returns_400_form_with_error(client, doctor, web_session, sql):
    web_session(client, doctor)

    resp = await client.post(
        "/cabinet/password",
        data={
            "old_password": "Wrong-Passw0rd",
            "new_password": STRONG_PASSWORD,
            "new_password_repeat": STRONG_PASSWORD,
        },
    )

    assert resp.status_code == 400
    assert "<form" in resp.text
    assert STRONG_PASSWORD not in resp.text
    assert (
        await client.post("/auth/login", json={"email": doctor.email, "password": doctor.password})
    ).status_code == 200


async def test_H13_mismatched_repeat_is_rejected(client, doctor, web_session):
    web_session(client, doctor)

    resp = await client.post(
        "/cabinet/password",
        data={
            "old_password": doctor.password,
            "new_password": STRONG_PASSWORD,
            "new_password_repeat": STRONG_PASSWORD + "x",
        },
    )

    assert resp.status_code == 422
    assert (
        await client.post("/auth/login", json={"email": doctor.email, "password": doctor.password})
    ).status_code == 200


async def test_athlete_form_offers_active_coaches_in_a_select(client, registrar, coach, web_session, make_user):
    inactive = await make_user(Role.COACH, is_active=False)
    web_session(client, registrar)

    resp = await client.get("/cabinet/athletes/new")

    assert '<select id="f-coach_id" name="coach_id"' in resp.text
    assert f'value="{coach.id}"' in resp.text and f'value="{inactive.id}"' not in resp.text
