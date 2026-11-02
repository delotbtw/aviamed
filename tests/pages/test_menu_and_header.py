"""Stage 2.1 spec section 6.3 (M-1..M-8): side menu, user box, header without role."""

import pytest

from app.core.rbac import Role
from app.models.user import User
from app.web.deps import ROLE_LABELS
from app.web.nav import nav_links
from tests.pages.dom import by_id, parse
from tests.schedule.support import has_element

SCHEDULE, QUEUE, SLOTS = "Расписание и запись", "Очередь и приход", "Слоты врачей"
REGISTER, CREATE_USER, PASSWORD = "Зарегистрировать спортсмена", "Создать пользователя", "Сменить пароль"
LABELS = {  # spec 4.2.5, in display order
    Role.ATHLETE: ["Записаться на приём", "Моя запись", PASSWORD],
    Role.REGISTRAR: [SCHEDULE, QUEUE, SLOTS, REGISTER, PASSWORD],
    Role.ADMIN: [SCHEDULE, QUEUE, SLOTS, REGISTER, CREATE_USER, PASSWORD],
    Role.DOCTOR: ["Свободные слоты", "Моё расписание", PASSWORD],
    Role.COACH: [PASSWORD],
}


async def cabinet(client, users_by_role, web_session, role, path="/cabinet"):
    web_session(client, users_by_role[role])
    resp = await client.get(path)
    assert resp.status_code == 200
    return parse(resp.text)


@pytest.mark.parametrize("role", list(Role))
async def test_M1_side_menu_holds_exactly_the_nav_links_without_notes(client, clock, users_by_role, web_session, role):
    root = await cabinet(client, users_by_role, web_session, role, "/cabinet/password")

    nav = by_id(root, "side-nav")
    assert nav is not None and nav.tag == "nav" and nav.attrs["aria-label"] == "Разделы"
    assert nav.parent.tag == "aside"
    links = nav.find_all("a")
    expected = nav_links(User(role=role))
    assert [a.attrs["href"] for a in links] == [x.href for x in expected]
    for a, x in zip(links, expected, strict=True):
        assert a.text == x.label and a.attrs["title"] == x.note
    assert by_id(root, "main").tag == "main"


@pytest.mark.parametrize("role", list(Role))
def test_M2_note_is_one_short_sentence_without_a_period(role):
    for link in nav_links(User(role=role)):
        assert 0 < len(link.note) <= 60 and not link.note.endswith(".")


@pytest.mark.parametrize("role", list(Role))
async def test_M2_menu_names_by_role(client, clock, users_by_role, web_session, role):
    root = await cabinet(client, users_by_role, web_session, role, "/cabinet/password")

    names = [a.text for a in by_id(root, "side-nav").find_all("a")]

    assert names == LABELS[role]


async def test_M2_doctor_sees_slots_as_my_schedule_not_my_slots(client, clock, users_by_role, web_session):
    root = await cabinet(client, users_by_role, web_session, Role.DOCTOR, "/cabinet/password")
    menu = by_id(root, "side-nav")

    assert menu.find("a", href="/cabinet/slots").text == "Моё расписание"
    assert "Мои слоты" not in menu.text and "Управление слотами" not in menu.text


async def test_M3_current_section_is_marked_only_on_its_link(client, clock, users_by_role, web_session):
    root = await cabinet(client, users_by_role, web_session, Role.REGISTRAR, "/cabinet/slots")

    marked = [a.attrs["href"] for a in by_id(root, "side-nav").find_all("a") if a.attrs.get("aria-current")]

    assert marked == ["/cabinet/slots"]
    assert by_id(root, "side-nav").find("a", href="/cabinet/slots").attrs["aria-current"] == "page"


@pytest.mark.parametrize("role", list(Role))
async def test_M3_cabinet_start_has_no_side_menu_and_marks_nothing(client, clock, users_by_role, web_session, role):
    root = await cabinet(client, users_by_role, web_session, role)

    assert by_id(root, "side-nav") is None
    assert [a for a in root.find_all("a") if a.attrs.get("aria-current")] == []


@pytest.mark.parametrize("role", [Role.ADMIN, Role.REGISTRAR, Role.DOCTOR, Role.ATHLETE, Role.COACH])
async def test_M4_every_menu_link_opens_with_200(client, clock, users_by_role, web_session, role):
    web_session(client, users_by_role[role])

    for link in nav_links(User(role=role)):
        assert (await client.get(link.href)).status_code == 200, link.href


async def test_M5_toggle_button_on_inner_cabinet_pages(client, clock, users_by_role, web_session):
    root = await cabinet(client, users_by_role, web_session, Role.ADMIN, "/cabinet/password")

    button = by_id(root, "menu-toggle")
    assert button is not None and button.tag == "button"
    assert button.attrs["aria-controls"] == "side-nav"
    assert "aria-expanded" in button.attrs or ":aria-expanded" in button.attrs


@pytest.mark.parametrize("path", ["/login", "/"])
async def test_M5_guest_pages_have_no_menu(client, path):
    html = (await client.get(path)).text

    assert not has_element(html, "side-nav") and not has_element(html, "menu-toggle")


@pytest.mark.parametrize("role", list(Role))
async def test_M6_cabinet_start_has_greeting_and_tiles_for_each_link(client, clock, users_by_role, web_session, role):
    root = await cabinet(client, users_by_role, web_session, role)

    main = by_id(root, "main")
    assert "Здравствуйте" in main.text and "Иванов" in main.text and "Иван" in main.text
    assert [a.attrs["href"] for a in main.by_class("tile")] == [x.href for x in nav_links(User(role=role))]


async def test_M6_coach_sees_a_stub_until_stage_4(client, clock, users_by_role, web_session):
    root = await cabinet(client, users_by_role, web_session, Role.COACH)

    home = by_id(root, "coach-home")
    assert home is not None and "Раздел со статусом допуска подопечных появится позже" in home.text


@pytest.mark.parametrize("role", [Role.ADMIN, Role.REGISTRAR, Role.DOCTOR, Role.ATHLETE])
async def test_M6_only_the_coach_has_the_stub(client, clock, users_by_role, web_session, role):
    root = await cabinet(client, users_by_role, web_session, role)

    assert by_id(root, "coach-home") is None


@pytest.mark.parametrize("role", list(Role))
async def test_M7_user_box_has_name_and_logout_and_header_has_no_role(client, clock, users_by_role, web_session, role):
    root = await cabinet(client, users_by_role, web_session, role)

    header = root.find("header")  # the masthead is the first header of the page
    box = by_id(root, "user-box")
    assert box is not None and box.inside(header)
    assert "Иванов" in box.text and "Иван" in box.text
    out = [f for f in box.find_all("form") if f.attrs.get("action") == "/logout"]
    assert out and "Выйти" in out[0].text
    assert header.by_class("role-badge") == [] and header.by_class("site-nav__role") == []
    for label in ROLE_LABELS.values():
        assert label not in header.text
    assert role.value not in header.text.lower().split()  # no bare "admin"/"doctor" text


@pytest.mark.parametrize("role", list(Role))
async def test_M7_header_outside_the_user_box_has_only_the_brand_link(client, clock, users_by_role, web_session, role):
    root = await cabinet(client, users_by_role, web_session, role)
    header = root.find("header")
    box = by_id(root, "user-box")

    outside = [a for a in header.find_all("a") if not a.inside(box)]

    assert [a.attrs["href"] for a in outside] == ["/cabinet"] and outside[0].text == "АвиаМед"


@pytest.mark.parametrize("path", ["/cabinet", "/cabinet/slots", "/cabinet/schedule", "/cabinet/athletes/new"])
async def test_M8_no_inline_style_or_script_code(client, clock, admin, web_session, path):
    web_session(client, admin)

    root = parse((await client.get(path)).text)

    assert [n.tag for n in root.walk() if "style" in n.attrs] == []
    assert [n for n in root.find_all("script") if "src" not in n.attrs] == []
