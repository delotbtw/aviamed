"""Hostile or stale input on the schedule pages, a busy row lock, history restore, caching headers, athlete lookup."""

import pytest

from app.core.exceptions import LockTimeout
from app.core.rbac import Role
from app.models.user import User
from app.repositories.schedule import ScheduleReadRepository
from app.schedule.queries import ScheduleDirectory
from tests.schedule.support import HX, at, element, has_element, is_fragment

pytestmark = pytest.mark.usefixtures("schedule_invariants")

RANGE_ERROR = "Введите дату с 2000 по 2100 год"


@pytest.mark.parametrize(
    ("url", "params", "field"),
    [
        ("/cabinet/schedule", {"date_from": "01.01.1999"}, "e-date_from"),
        ("/cabinet/schedule", {"date_to": "02.01.2100"}, "e-date_to"),
        ("/cabinet/appointments", {"date": "01.01.0001"}, "e-date"),
        ("/cabinet/slots", {"date": "31.12.9999"}, "e-date"),
    ],
)
async def test_dates_outside_the_api_range_are_a_field_error_not_a_500(
    client, clock, admin, web_session, url, params, field
):
    web_session(client, admin)

    resp = await client.get(url, params=params)

    assert resp.status_code == 422 and RANGE_ERROR in element(resp.text, "small", field)


async def test_huge_offset_is_ignored(client, clock, athlete, web_session):
    web_session(client, athlete)

    assert (await client.get("/cabinet/schedule", params={"offset": 200000})).status_code == 200


async def test_slot_form_date_outside_the_range_is_a_field_error(client, clock, registrar, web_session, sql):
    web_session(client, registrar)
    data = {"slot_date": "01.01.0001", "start_time": "09:00", "end_time": "10:00"}

    resp = await client.post("/cabinet/slots/new", data=data, headers=HX)

    assert resp.status_code == 422 and RANGE_ERROR in element(resp.text, "small", "e-slot_date")
    assert await sql("SELECT id FROM slots") == []


async def test_booking_conflict_survives_garbage_filters(
    client, clock, athlete, athlete2, doctor, make_slot, make_booking, web_session
):
    taken = await make_slot(doctor, at(10))
    await make_booking(taken, athlete2)
    web_session(client, athlete)

    resp = await client.post("/cabinet/schedule/book", data={"slot_id": taken, "date_from": "01.01.0001"}, headers=HX)

    assert resp.status_code == 409 and has_element(resp.text, "slots-results")


async def test_filter_errors_keep_the_table_and_the_address(client, clock, athlete, web_session):
    web_session(client, athlete)

    resp = await client.get("/cabinet/schedule", params={"date_from": "31.02.2026"}, headers=HX)

    assert resp.status_code == 422 and resp.headers["HX-Reswap"] == "none" and resp.headers["HX-Push-Url"] == "false"
    assert 'hx-swap-oob="true"' in resp.text


async def test_filter_errors_do_not_say_there_are_no_slots(client, clock, athlete, web_session):
    web_session(client, athlete)

    html = (await client.get("/cabinet/schedule", params={"date_from": "31.02.2026"})).text

    assert "Свободных слотов нет" not in html


async def test_busy_row_lock_is_503_with_retry_after_and_a_message(
    client, clock, athlete, doctor, make_slot, make_booking, web_session, monkeypatch
):
    appointment_id = await make_booking(await make_slot(doctor, at(10)), athlete)

    async def busy(*args, **kwargs):
        raise LockTimeout

    monkeypatch.setattr("app.schedule.booking.BookingService.cancel", busy)
    web_session(client, athlete)

    resp = await client.post(f"/cabinet/appointments/{appointment_id}/cancel", headers=HX)

    assert resp.status_code == 503 and resp.headers["Retry-After"] == "1"
    assert "Запись занята другим действием, повторите через секунду" in resp.text
    assert has_element(resp.text, f"appt-{appointment_id}")


@pytest.mark.parametrize("url", ["/cabinet/schedule", "/cabinet/appointments", "/cabinet/slots"])
async def test_history_restore_gets_the_whole_page(client, clock, admin, web_session, url):
    web_session(client, admin)

    restored = await client.get(url, headers={**HX, "HX-History-Restore-Request": "true"})
    fragment = await client.get(url, headers=HX)

    assert "<html" in restored.text and is_fragment(fragment.text)


@pytest.mark.parametrize("url", ["/cabinet/schedule", "/cabinet/appointments", "/cabinet/slots"])
async def test_pages_are_not_cached_and_vary_on_hx_request(client, clock, admin, web_session, url):
    web_session(client, admin)

    resp = await client.get(url)

    assert resp.headers["Cache-Control"] == "no-store" and "HX-Request" in resp.headers["Vary"]


async def test_queue_shows_the_chosen_athlete_by_id_and_has_no_label_field(
    client, clock, registrar, athlete, web_session
):
    web_session(client, registrar)

    html = (await client.get("/cabinet/appointments", params={"athlete_id": athlete.id})).text

    assert "Иванов Иван Иванович" in element(html, "p", "selected-athlete") and "athlete_label" not in html


async def test_queue_ignores_an_unknown_or_broken_athlete(client, clock, registrar, web_session):
    web_session(client, registrar)

    unknown = await client.get("/cabinet/appointments", params={"athlete_id": 99999})
    broken = await client.get("/cabinet/appointments", params={"athlete_id": "x"})

    assert unknown.status_code == broken.status_code == 200
    assert "Спортсмен не выбран" in element(broken.text, "p", "selected-athlete")


async def test_directory_names_an_athlete_only_for_staff(db, athlete, registrar, doctor, make_user):
    inactive = await make_user(Role.ATHLETE, is_active=False)
    directory = ScheduleDirectory(ScheduleReadRepository(db))
    staff = await db.get(User, registrar.id)
    outsider = await db.get(User, doctor.id)

    assert await directory.athlete(athlete.id, staff) == "Иванов Иван Иванович"
    assert await directory.athlete(inactive.id, staff) is None
    assert await directory.athlete(doctor.id, staff) is None  # not an athlete
    assert await directory.athlete(athlete.id, outsider) is None  # only registrar and admin look athletes up
