"""Top-bar / cabinet links by role, HTMX policy for forbidden pages, role whitelist in the user form."""

import re
from pathlib import Path

import pytest

from app.core.rbac import Action, Role, roles_for
from app.models.user import User
from app.web.nav import nav_links

MATRIX = (Path(__file__).resolve().parents[2] / "docs" / "03_matrix.md").read_text()
ROWS = {  # link href -> (rbac action, label of the row in docs/03_matrix.md)
    "/cabinet/users/new": (Action.USER_CREATE, "Создать пользователя"),
    "/cabinet/athletes/new": (Action.ATHLETE_REGISTER, "Зарегистрировать спортсмена"),
}
MATRIX_COLUMNS = [Role.ADMIN, Role.REGISTRAR, Role.DOCTOR, Role.COACH, Role.ATHLETE]


def matrix_roles(label: str) -> set[Role]:
    row = next(line for line in MATRIX.splitlines() if line.startswith(f"| {label}"))
    cells = [c.strip() for c in row.strip("|").split("|")][1:]
    return {role for role, cell in zip(MATRIX_COLUMNS, cells, strict=False) if cell.startswith("✓")}


@pytest.mark.parametrize("role", list(Role))
def test_nav_links_follow_rbac_and_matrix(role):
    shown = {link.href for link in nav_links(User(role=role))}

    assert "/cabinet/password" in shown
    for href, (action, label) in ROWS.items():
        assert (href in shown) == (role in roles_for(action)) == (role in matrix_roles(label))


def test_nav_links_for_guest_is_empty():
    assert nav_links(None) == []


async def test_htmx_forbidden_redirects_instead_of_swapping_a_page(client, users_by_role, web_session):
    web_session(client, users_by_role[Role.REGISTRAR])

    resp = await client.post("/cabinet/users/new", data={}, headers={"HX-Request": "true"})

    assert resp.status_code == 403
    assert resp.headers["HX-Redirect"] == "/cabinet"
    assert "<html" not in resp.text


async def test_user_form_role_is_whitelisted_before_it_reaches_alpine(client, users_by_role, web_session):
    web_session(client, users_by_role[Role.ADMIN])
    evil = "x'}); alert(1); ({'"

    resp = await client.post("/cabinet/users/new", data={"role": evil}, headers={"HX-Request": "true"})

    assert evil not in resp.text and "alert(1)" not in resp.text
    assert re.search(r"x-data='\{ role: \"doctor\" \}'", resp.text)


# --------------------------------------------------------------------------- dates typed as дд.мм.гггг

from datetime import date, timedelta  # noqa: E402

from app.web.dates import DATE_FORMAT_ERROR, normalize_dates, parse_page_date, show_dates  # noqa: E402
from tests.helpers import athlete_payload  # noqa: E402


def test_parse_page_date_accepts_russian_and_iso():
    assert parse_page_date("12.03.2004") == date(2004, 3, 12)
    assert parse_page_date(" 2004-03-12 ") == date(2004, 3, 12)
    assert parse_page_date("29.02.2024") == date(2024, 2, 29)


@pytest.mark.parametrize("text", ["29.02.2023", "31.04.2020", "12/03/2004", "3.4.2004", "12.03.04", "abc", ""])
def test_parse_page_date_rejects_nonsense(text):
    assert parse_page_date(text) is None


def test_normalize_and_show_dates_round_trip():
    payload, errors = normalize_dates({"birth_date": "12.03.2004", "consent_signed_at": "31.02.2020", "email": "a@b.c"})

    assert payload == {"birth_date": "2004-03-12", "email": "a@b.c"}
    assert errors == {"consent_signed_at": DATE_FORMAT_ERROR}
    assert show_dates({"birth_date": "2004-03-12", "consent_signed_at": "31.02.2020"}) == {
        "birth_date": "12.03.2004",
        "consent_signed_at": "31.02.2020",
    }


async def submit_athlete(client, users_by_role, web_session, **overrides):
    web_session(client, users_by_role[Role.REGISTRAR])
    data = athlete_payload() | overrides
    return await client.post("/cabinet/athletes/new", data=data)


async def test_athlete_form_accepts_russian_dates(client, users_by_role, web_session, sql):
    resp = await submit_athlete(client, users_by_role, web_session, birth_date="12.03.2004")

    assert resp.status_code == 200 and "Создан" in resp.text
    rows = await sql(
        "SELECT a.birth_date FROM athlete_profiles a JOIN users u ON u.id = a.user_id WHERE u.email = :email",
        email=athlete_payload()["email"],
    )
    assert rows[0]["birth_date"] == date(2004, 3, 12)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("29.02.2023", DATE_FORMAT_ERROR),
        ("не дата", DATE_FORMAT_ERROR),
        ((date.today() + timedelta(days=1)).strftime("%d.%m.%Y"), None),
        ("01.01.1800", None),
    ],
)
async def test_athlete_form_reports_bad_birth_date_in_the_field(client, users_by_role, web_session, value, message):
    resp = await submit_athlete(client, users_by_role, web_session, birth_date=value)

    assert resp.status_code == 422
    assert 'id="e-birth_date"' in resp.text
    assert message is None or message in resp.text
    assert f'value="{value}"' in resp.text  # typed text comes back as it was


async def test_athlete_form_shows_iso_input_as_russian_date_after_an_error(client, users_by_role, web_session):
    resp = await submit_athlete(client, users_by_role, web_session, birth_date="2004-03-12", last_name="")

    assert resp.status_code == 422
    assert 'value="12.03.2004"' in resp.text
