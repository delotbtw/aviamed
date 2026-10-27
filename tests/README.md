# Tests

Integration tests against a real PostgreSQL and fakeredis. Spec: `docs/stages/stage-1-auth-users.md`, section 6
(test names carry the criterion id: `test_A1_...`, `test_H7_...`).

## Run

```bash
# 1. throwaway Postgres 17 on port 55432 (tmpfs, removed on stop): one command
docker run -d --rm --name medcenter-test-pg -p 55432:5432 -e POSTGRES_USER=medcenter -e POSTGRES_PASSWORD=medcenter \
  -e POSTGRES_DB=medcenter_test --tmpfs /var/lib/postgresql/data postgres:17-alpine

# 2. tests
uv run pytest
```

Another database: `TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/some_test_db uv run pytest`.
The database name must contain `test` (the schema is dropped and recreated at session start).
Stop Postgres: `docker stop medcenter-test-pg`.

## Design

- `conftest.py` sets `DATABASE_URL`, `SECRET_KEY`, `DEBUG=false` in the environment before importing the app.
- Schema: `Base.metadata.create_all` once per session; `TRUNCATE ... RESTART IDENTITY` after every test
  (services commit for real, so rollback isolation would hide the "audit survives a failed request" criteria).
- Redis: fakeredis installed into `app.core.redis._redis`, flushed per test. Chosen over a second real Redis: no extra
  service, TTL support, and `redis_down()` simulates an outage via `FakeServer.connected = False`.
- One event loop for the whole run (`asyncio_default_*_loop_scope = "session"` in pyproject).
- Client base URL is `https://test` so `Secure` auth cookies are kept in the cookie jar.
- Fixtures: `admin registrar doctor coach athlete users_by_role make_user sport specialty`, `sql` (fresh-connection
  queries), `audit`, `redis`, `redis_down`, `login`, `web_session`, `expired_token`.

## Layout

- `auth/` - blocks A, B, C (login/rate limit, refresh/logout, change password)
- `users/` - blocks D, E, F, G (create user, register athlete, PATCH /users/me, deactivate)
- `pages/` - block H (pages, cookies, session, CSRF, forms)
- `test_cli.py` - block I (`python -m app.cli create-admin`, password via `ADMIN_PASSWORD` env)
