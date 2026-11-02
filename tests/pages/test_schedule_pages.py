"""Spec section 6, blocks T-1..T-6, Q-1/Q-4/Q-5/Q-6: /cabinet/schedule, the athlete search and booking from a page.

Element ids, field names and messages are fixed in docs/stages/stage-2-schedule.md, section 12.
"""

from datetime import timedelta

import pytest

from app.core.rbac import Role
from tests.helpers import location
from tests.schedule.support import (
    HX,
    NOW,
    at,
    element,
    has_element,
    input_tag,
    is_fragment,
    msk,
    row,
)

pytestmark = pytest.mark.usefixtures("schedule_invariants")

URL = "/cabinet/schedule"
DATE_ERROR = "Введите существующую дату в формате дд.мм.гггг"


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.ADMIN, 200), (Role.REGISTRAR, 200), (Role.DOCTOR, 200), (Role.ATHLETE, 200), (Role.COACH, 403)],
)
async def test_T1_access_by_role(client, clock, users_by_role, web_session, role, expected):
    web_session(client, users_by_role[role])

    resp = await client.get(URL)

    assert resp.status_code == expected
    assert "text/html" in resp.headers["content-type"]


async def test_T1_without_cookie_redirects_to_the_session_endpoint(client, clock):
    resp = await client.get(URL)

    assert resp.status_code == 303 and location(resp) == "/auth/session?next=/cabinet/schedule"


async def test_T2_table_shows_moscow_date_time_doctor_specialty_and_cabinet(
    client, clock, athlete, doctor2, make_slot, web_session
):
    slot_id = await make_slot(doctor2, msk(2026, 11, 3, 10, 30))  # 07:30 UTC
    web_session(client, athlete)

    resp = await client.get(URL)

    assert resp.status_code == 200
    cells = row(resp.text, f"slot-{slot_id}")
    assert "03.11.2026" in cells and "10:30" in cells
    assert "Кузнецов Пётр Иванович" in cells and "Кардиология" in cells and "305" in cells
    assert "07:30" not in cells and "2026-11-03" not in cells  # neither UTC nor ISO leaks into the page
    assert "Записаться" in cells


async def test_T2_filters_are_in_the_markup_as_text_inputs_with_mask_placeholders(client, clock, athlete, web_session):
    web_session(client, athlete)

    html = (await client.get(URL)).text

    assert has_element(html, "slot-filters") and 'hx-get="/cabinet/schedule"' in html
    assert 'hx-target="#slots-results"' in html and 'hx-push-url="true"' in html
    assert 'name="doctor_id"' in input_tag(html, "f-doctor_id")
    assert 'name="specialty_id"' in input_tag(html, "f-specialty_id")
    for field in ("f-date_from", "f-date_to"):
        tag = input_tag(html, field)
        assert 'type="text"' in tag and 'placeholder="дд.мм.гггг"' in tag
        assert 'type="date"' not in tag


async def test_T2_filter_selects_list_doctors_and_specialties(client, clock, athlete, doctor2, web_session):
    web_session(client, athlete)

    html = (await client.get(URL)).text

    assert "Кузнецов" in element(html, "select", "f-doctor_id")
    assert "Кардиология" in element(html, "select", "f-specialty_id")


async def test_T2_htmx_request_with_filters_returns_only_the_results_fragment(
    client, clock, athlete, doctor, doctor2, make_slot, web_session
):
    mine = await make_slot(doctor, at(10))
    other = await make_slot(doctor2, at(10, 30))
    web_session(client, athlete)

    resp = await client.get(URL, params={"doctor_id": doctor2.id}, headers=HX)

    assert resp.status_code == 200 and is_fragment(resp.text)
    assert has_element(resp.text, "slots-table") and has_element(resp.text, f"slot-{other}")
    assert not has_element(resp.text, f"slot-{mine}") and not has_element(resp.text, "slot-filters")


async def test_T2_plain_request_returns_the_whole_page(client, clock, athlete, web_session):
    web_session(client, athlete)

    html = (await client.get(URL)).text

    assert "<html" in html and has_element(html, "slots-results") and "АвиаМед" in html


async def test_T2_empty_result_says_so(client, clock, athlete, web_session):
    web_session(client, athlete)

    html = (await client.get(URL)).text

    assert "Свободных слотов нет" in element(html, "div", "slots-results")


async def test_T2_show_more_loads_the_next_fifty(client, clock, athlete, doctor, make_slot, web_session, sql):
    await sql(
        "INSERT INTO slots (doctor_id, start_at, end_at, status) "
        "SELECT :d, t, t + interval '10 minutes', 'free' "
        "FROM (SELECT CAST(:s AS timestamptz) + g * interval '10 minutes' AS t FROM generate_series(0, 59) g) x",
        d=doctor.id,
        s=at(8),
    )
    web_session(client, athlete)

    first = await client.get(URL)
    more = await client.get(URL, params={"offset": 50}, headers=HX)

    assert first.text.count('<tr id="slot-') == 50
    assert has_element(first.text, "load-more") and "offset=50" in input_tag_or_button(first.text, "load-more")
    assert more.status_code == 200 and is_fragment(more.text)
    assert more.text.count('<tr id="slot-') == 10 and not has_element(more.text, "load-more")


def input_tag_or_button(html: str, element_id: str) -> str:
    return element(html, "button", element_id)


@pytest.mark.parametrize("bad", ["3.11.2026", "31.02.2026", "03/11/2026", "завтра", "2026.11.03"])
@pytest.mark.parametrize("field", ["date_from", "date_to"])
async def test_T3_malformed_date_is_422_with_the_message_under_the_field(
    client, clock, athlete, web_session, field, bad
):
    web_session(client, athlete)

    resp = await client.get(URL, params={field: bad}, headers=HX)

    assert resp.status_code == 422
    assert DATE_ERROR in element(resp.text, "small", f"e-{field}")
    assert f'value="{bad}"' in input_tag(resp.text, f"f-{field}") or bad in resp.text  # the typed value is kept


async def test_T3_valid_russian_date_is_accepted(client, clock, athlete, doctor, make_slot, web_session):
    slot_id = await make_slot(doctor, at(10))
    web_session(client, athlete)

    resp = await client.get(URL, params={"date_from": "03.11.2026", "date_to": "03.11.2026"})

    assert resp.status_code == 200 and has_element(resp.text, f"slot-{slot_id}")
    assert 'value="03.11.2026"' in input_tag(resp.text, "f-date_from")


async def test_T3_iso_date_is_accepted_for_compatibility(client, clock, athlete, web_session):
    web_session(client, athlete)

    assert (await client.get(URL, params={"date_from": "2026-11-03"})).status_code == 200


async def test_T3_date_from_after_date_to_is_422(client, clock, athlete, web_session):
    web_session(client, athlete)

    resp = await client.get(URL, params={"date_from": "05.11.2026", "date_to": "04.11.2026"})

    assert resp.status_code == 422
    assert "Начальная дата позже конечной" in resp.text


async def test_Q4_page_filters_are_moscow_days(client, clock, athlete, doctor, make_slot, web_session):
    early = await make_slot(doctor, msk(2026, 11, 3, 1, 0))  # 22:00 UTC on 02.11
    next_day = await make_slot(doctor, msk(2026, 11, 4, 0, 0))  # 21:00 UTC on 03.11
    web_session(client, athlete)

    resp = await client.get(URL, params={"date_from": "01.11.2026", "date_to": "03.11.2026"})

    assert has_element(resp.text, f"slot-{early}") and not has_element(resp.text, f"slot-{next_day}")
    assert "03.11.2026" in row(resp.text, f"slot-{early}") and "01:00" in row(resp.text, f"slot-{early}")


async def test_Q6_timezone_comes_from_the_setting(client, clock, settings_env, athlete, doctor, make_slot, web_session):
    slot_id = await make_slot(doctor, msk(2026, 11, 3, 10, 30))  # 07:30 UTC = 12:30 in UTC+5
    settings_env(schedule_timezone="Asia/Yekaterinburg")
    web_session(client, athlete)

    shown = row((await client.get(URL)).text, f"slot-{slot_id}")

    assert "12:30" in shown and "10:30" not in shown and "03.11.2026" in shown


async def test_Q6_date_boundaries_follow_the_setting_too(
    client, clock, settings_env, athlete, doctor, make_slot, web_session
):
    slot_id = await make_slot(doctor, msk(2026, 11, 2, 22, 30))  # 19:30 UTC: 02.11 in Moscow, 00:30 on 03.11 in UTC+5
    web_session(client, athlete)
    params = {"date_from": "03.11.2026", "date_to": "03.11.2026"}
    assert not has_element((await client.get(URL, params=params)).text, f"slot-{slot_id}")

    settings_env(schedule_timezone="Asia/Yekaterinburg")

    assert has_element((await client.get(URL, params=params)).text, f"slot-{slot_id}")


# --------------------------------------------------------------------------- booking from the page


async def test_T4_athlete_books_from_the_page(client, clock, athlete, doctor2, make_slot, web_session, sql):
    slot_id = await make_slot(doctor2, msk(2026, 11, 3, 10, 30))
    web_session(client, athlete)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": slot_id}, headers=HX)

    assert resp.status_code == 200 and is_fragment(resp.text)
    result = element(resp.text, "div", "booking-result")
    assert "Записано: 03.11.2026 в 10:30" in result
    assert "Кузнецов Пётр Иванович" in result and "кабинет 305" in result
    assert has_element(resp.text, f"slot-{slot_id}") and 'hx-swap-oob="delete"' in resp.text  # the row goes away
    [appointment] = await sql("SELECT athlete_id, created_by, status FROM appointments")
    assert appointment == {"athlete_id": athlete.id, "created_by": athlete.id, "status": "booked"}
    assert slot_id and not has_element((await client.get(URL)).text, f"slot-{slot_id}")


async def test_T4_athlete_does_not_see_the_athlete_search(client, clock, athlete, doctor, make_slot, web_session):
    await make_slot(doctor, at(10))
    web_session(client, athlete)

    html = (await client.get(URL)).text

    assert not has_element(html, "athlete-search") and 'name="athlete_id"' not in html


async def test_T4_doctor_sees_slots_but_no_booking_controls(client, clock, doctor, doctor2, make_slot, web_session):
    slot_id = await make_slot(doctor2, at(10))
    web_session(client, doctor)

    html = (await client.get(URL)).text

    assert has_element(html, f"slot-{slot_id}") and "Записаться" not in html
    assert not has_element(html, "athlete-search")


async def test_T4_doctor_cannot_post_a_booking(client, clock, doctor, athlete, doctor2, make_slot, web_session, sql):
    slot_id = await make_slot(doctor2, at(10))
    web_session(client, doctor)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": slot_id, "athlete_id": athlete.id}, headers=HX)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM appointments") == []


async def test_T5_slot_taken_in_the_meantime_gives_409_and_a_refreshed_table(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking, web_session, sql
):
    taken = await make_slot(doctor, at(10))
    still_free = await make_slot(doctor, at(11))
    await make_booking(taken, athlete2)  # someone else was faster
    web_session(client, athlete)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": taken}, headers=HX)

    assert resp.status_code == 409 and is_fragment(resp.text)
    assert "Слот уже занят, выберите другой" in element(resp.text, "div", "booking-result")
    assert has_element(resp.text, "slots-results") and has_element(resp.text, f"slot-{still_free}")
    assert not has_element(resp.text, f"slot-{taken}")
    assert len(await sql("SELECT id FROM appointments")) == 1


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("closed", "Слот закрыт для записи"),
        ("started", "Приём уже начался, запись невозможна"),
        ("far", "Запись на эту дату пока недоступна"),
        ("inactive_doctor", "Врач не принимает, выберите другого"),
    ],
)
async def test_T5_other_reasons_have_their_own_russian_text(
    client, clock, athlete, doctor, make_slot, web_session, sql, setup, message
):
    start = {
        "closed": at(10),
        "started": NOW - timedelta(minutes=5),
        "far": NOW + timedelta(days=61),
        "inactive_doctor": at(10),
    }[setup]
    slot_id = await make_slot(doctor, start, status="closed" if setup == "closed" else "free")
    if setup == "inactive_doctor":
        await sql("UPDATE users SET is_active = false WHERE id = :i", i=doctor.id)
    web_session(client, athlete)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": slot_id}, headers=HX)

    assert resp.status_code == 409
    assert message in element(resp.text, "div", "booking-result")


async def test_T5_unknown_slot_is_404_with_a_message(client, clock, athlete, web_session):
    web_session(client, athlete)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": 99999}, headers=HX)

    assert resp.status_code == 404 and "Слот не найден" in resp.text


async def test_T5_garbage_slot_id_is_422(client, clock, athlete, web_session):
    web_session(client, athlete)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": "abc"}, headers=HX)

    assert resp.status_code == 422


# --------------------------------------------------------------------------- registrar: athlete search and booking


@pytest.fixture
async def many_ivanovs(make_user):
    """12 active Ivanovs (+ the ones from the shared fixtures are not created here), one inactive, one Petrov."""
    out = [await make_user(Role.ATHLETE, last_name="Иванов", first_name=f"Имя{n:02d}") for n in range(12)]
    await make_user(Role.ATHLETE, last_name="Иванов", first_name="Неактивный", is_active=False)
    await make_user(Role.ATHLETE, last_name="Петров", first_name="Пётр")
    return out


async def test_T6_search_returns_active_athletes_by_surname_prefix(
    client, registrar, athlete, athlete2, doctor, make_user, web_session
):
    inactive = await make_user(Role.ATHLETE, last_name="Иваненко", first_name="Выбыл", is_active=False)
    web_session(client, registrar)

    resp = await client.get("/cabinet/schedule/athletes", params={"q": "Ив"}, headers=HX)

    assert resp.status_code == 200 and is_fragment(resp.text)
    assert f'data-athlete-id="{athlete.id}"' in resp.text
    assert "Иванов Иван Иванович" in resp.text and "17.05.2003" in resp.text  # name and birth date as дд.мм.гггг
    assert f'data-athlete-id="{athlete2.id}"' not in resp.text  # Петров
    assert f'data-athlete-id="{doctor.id}"' not in resp.text  # a doctor with the same surname is not an athlete
    assert f'data-athlete-id="{inactive.id}"' not in resp.text
    assert "2003-05-17" not in resp.text


async def test_T6_search_is_case_insensitive_and_prefix_only(client, registrar, athlete, web_session):
    web_session(client, registrar)

    lower = await client.get("/cabinet/schedule/athletes", params={"q": "ива"}, headers=HX)
    infix = await client.get("/cabinet/schedule/athletes", params={"q": "ванов"}, headers=HX)

    assert f'data-athlete-id="{athlete.id}"' in lower.text
    assert f'data-athlete-id="{athlete.id}"' not in infix.text


async def test_T6_search_returns_at_most_ten(client, registrar, many_ivanovs, web_session):
    web_session(client, registrar)

    resp = await client.get("/cabinet/schedule/athletes", params={"q": "Иванов"}, headers=HX)

    assert resp.text.count("data-athlete-id=") == 10


@pytest.mark.parametrize("q", ["", "И", " ", "  И "])
async def test_T6_short_query_gives_an_empty_result(client, registrar, athlete, web_session, q):
    web_session(client, registrar)

    resp = await client.get("/cabinet/schedule/athletes", params={"q": q}, headers=HX)

    assert resp.status_code == 200 and "data-athlete-id=" not in resp.text


async def test_T6_search_without_the_parameter_is_empty_not_an_error(client, registrar, athlete, web_session):
    web_session(client, registrar)

    resp = await client.get("/cabinet/schedule/athletes", headers=HX)

    assert resp.status_code == 200 and "data-athlete-id=" not in resp.text


async def test_T6_search_matches_do_not_leak_contacts(client, registrar, athlete, web_session):
    web_session(client, registrar)

    resp = await client.get("/cabinet/schedule/athletes", params={"q": "Ив"}, headers=HX)

    assert athlete.email not in resp.text and "+79990000000" not in resp.text


@pytest.mark.parametrize("role", [Role.ATHLETE, Role.DOCTOR, Role.COACH])
async def test_T6_search_is_forbidden_for_other_roles(client, users_by_role, web_session, role):
    web_session(client, users_by_role[role])

    resp = await client.get("/cabinet/schedule/athletes", params={"q": "Ив"}, headers=HX)

    assert resp.status_code == 403
    assert "data-athlete-id=" not in resp.text


async def test_T6_admin_may_search(client, admin, athlete, web_session):
    web_session(client, admin)

    resp = await client.get("/cabinet/schedule/athletes", params={"q": "Ив"}, headers=HX)

    assert resp.status_code == 200 and f'data-athlete-id="{athlete.id}"' in resp.text


@pytest.mark.parametrize("role", [Role.REGISTRAR, Role.ADMIN])
async def test_T6_staff_page_has_the_search_field_and_a_hidden_athlete_id(
    client, clock, users_by_role, doctor, make_slot, web_session, role
):
    slot_id = await make_slot(doctor, at(10))
    web_session(client, users_by_role[role])

    html = (await client.get(URL)).text

    assert 'name="q"' in input_tag(html, "athlete-search")
    assert 'hx-get="/cabinet/schedule/athletes"' in input_tag(html, "athlete-search")
    assert 'type="hidden"' in input_tag(html, "athlete-id") and 'name="athlete_id"' in input_tag(html, "athlete-id")
    assert has_element(html, "selected-athlete") and "Записаться" in row(html, f"slot-{slot_id}")


async def test_T6_registrar_books_for_the_selected_athlete(
    client, clock, registrar, athlete, doctor, make_slot, web_session, sql
):
    slot_id = await make_slot(doctor, at(10))
    web_session(client, registrar)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": slot_id, "athlete_id": athlete.id}, headers=HX)

    assert resp.status_code == 200
    assert "Записано: 03.11.2026 в 10:00" in resp.text
    [appointment] = await sql("SELECT athlete_id, created_by FROM appointments")
    assert appointment == {"athlete_id": athlete.id, "created_by": registrar.id}


async def test_T6_booking_without_a_selected_athlete_is_422(
    client, clock, registrar, doctor, make_slot, web_session, sql
):
    slot_id = await make_slot(doctor, at(10))
    web_session(client, registrar)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": slot_id}, headers=HX)

    assert resp.status_code == 422 and "Выберите спортсмена" in element(resp.text, "div", "booking-result")
    assert await sql("SELECT id FROM appointments") == []


async def test_T6_overlap_of_the_athlete_has_its_own_text(
    client, clock, registrar, athlete, doctor, doctor2, make_slot, make_booking, web_session
):
    await make_booking(await make_slot(doctor, at(10)), athlete)
    other = await make_slot(doctor2, at(10))
    web_session(client, registrar)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": other, "athlete_id": athlete.id}, headers=HX)

    assert resp.status_code == 409
    assert "У спортсмена уже есть запись на это время" in element(resp.text, "div", "booking-result")


async def test_T6_athlete_cannot_book_for_someone_else_through_the_form(
    client, clock, athlete, athlete2, doctor, make_slot, web_session, sql
):
    slot_id = await make_slot(doctor, at(10))
    web_session(client, athlete)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": slot_id, "athlete_id": athlete2.id}, headers=HX)

    assert resp.status_code == 403
    assert await sql("SELECT id FROM appointments") == []


async def test_page_values_never_expose_other_peoples_contacts(client, clock, athlete, doctor2, make_slot, web_session):
    await make_slot(doctor2, at(10))
    web_session(client, athlete)

    html = (await client.get(URL)).text

    assert doctor2.email not in html and "+79990000000" not in html
