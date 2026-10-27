"""Round 3: a lost race on a form is a 409 form, not a 500 (the session is rolled back and stays usable)."""

import asyncio

from app.repositories.system import ConsentRepository
from tests.helpers import athlete_payload


async def submit(client, n: int, number: str = "WEB-RACE-1"):
    payload = athlete_payload(email=f"web-race{n}@example.com", consent_paper_number=number)
    return await client.post("/cabinet/athletes/new", data=payload, headers={"HX-Request": "true"})


async def test_parallel_form_submissions_with_same_consent_number(client, registrar, web_session, sql):
    web_session(client, registrar)

    resps = await asyncio.gather(*(submit(client, n) for n in range(4)))

    assert sorted(r.status_code for r in resps) == [200, 409, 409, 409]
    assert len(await sql("SELECT id FROM consents")) == 1
    loser = next(r for r in resps if r.status_code == 409)
    assert "alert" in loser.text and registrar.email not in loser.text


async def test_lost_race_at_the_unique_index_renders_409_form(client, registrar, web_session, sql, monkeypatch):
    web_session(client, registrar)
    assert (await submit(client, 1)).status_code == 200

    async def never_taken(self, consent_type, paper_number):  # skip the friendly pre-check: the index must decide
        return False

    monkeypatch.setattr(ConsentRepository, "paper_number_taken", never_taken)
    resp = await submit(client, 2)

    assert resp.status_code == 409
    assert "Иванов" in resp.text or "alert" in resp.text  # the page rendered with the (reloaded) actor
    assert len(await sql("SELECT id FROM users WHERE role = 'athlete'")) == 1
    assert len(await sql("SELECT id FROM consents")) == 1
