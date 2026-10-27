# Tests

Integration tests against a real PostgreSQL and fakeredis. Spec: `docs/stages/stage-1-auth-users.md`, section 6
(test names carry the criterion id: `test_A1_...`, `test_H7_...`).

## Run

```bash
make test        # starts postgres-test (compose profile `test`) and runs pytest
# or step by step:
make test-db     # docker compose --profile test up -d --wait postgres-test
uv run pytest
make test-db-stop  # remove only the test DB; `make down` stops everything incl. the test DB
```

The test Postgres 17 is the `postgres-test` service in `docker-compose.yml` (project `med_center`): published on
`127.0.0.1:55432` only, data on tmpfs, user/password `medcenter`, database `medcenter_test`. `make status` shows it.

Another database: `TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/some_test_db uv run pytest`.
The database name must contain `test` (the schema is dropped and recreated at session start).

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
