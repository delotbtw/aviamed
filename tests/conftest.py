"""Test infrastructure: real PostgreSQL, fakeredis, async httpx client, user factories.

Environment is forced BEFORE importing the app, because `get_settings()` is cached on first use.
"""

import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://medcenter:medcenter@localhost:55432/medcenter_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # must never be used: Redis is replaced by fakeredis
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-0123456789"
os.environ["DEBUG"] = "false"

import itertools  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import UTC, date, datetime, timedelta  # noqa: E402

import fakeredis  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import make_url, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import app.core.redis as redis_module  # noqa: E402
from app.core.access_tokens import AccessTokenService, JwtCodec  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.rbac import Role  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.enums import Sex  # noqa: E402
from app.models.reference import Specialty, Sport  # noqa: E402
from app.models.user import AthleteProfile, CoachProfile, DoctorProfile, StaffProfile, User  # noqa: E402

DEFAULT_PASSWORD = "Passw0rd-Test"
BASE_URL = "https://test"  # https: auth cookies are Secure (debug=false) and httpx drops them on plain http

_hash_cache: dict[str, str] = {}
_argon2 = PasswordHasher()


def cached_hash(password: str) -> str:
    """argon2 is slow by design; hash each distinct password once per run."""
    if password not in _hash_cache:
        _hash_cache[password] = _argon2.hash(password)
    return _hash_cache[password]


@dataclass
class UserInfo:
    id: int
    email: str
    password: str
    role: Role

    @property
    def token(self) -> str:
        s = get_settings()
        tokens = AccessTokenService(JwtCodec(s.secret_key, s.jwt_algorithm), timedelta(minutes=s.access_token_ttl_min))
        return tokens.issue(self.id, self.role.value)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


# --------------------------------------------------------------------------- database


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    url = make_url(TEST_DATABASE_URL)
    # The schema is dropped below: refuse to run against anything that is not obviously a test database.
    assert url.database and "test" in url.database, f"refusing to use non-test database {url.database!r}"
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def clean_db(db_engine):
    """Truncate everything after each test (services commit for real, so rollback isolation is impossible)."""
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TRIGGER IF EXISTS test_fail ON consents"))
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def session_factory(db_engine, clean_db):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory):
    """ORM session for arranging data / calling repositories. For assertions prefer `sql` (always fresh)."""
    async with session_factory() as session:
        yield session


@pytest.fixture
def sql(db_engine, clean_db):
    """`await sql("SELECT ... WHERE id = :id", id=1)` -> list of dict rows, every call in a fresh connection."""

    async def run(query: str, **params) -> list[dict]:
        async with db_engine.begin() as conn:
            result = await conn.execute(text(query), params)
            return [dict(r) for r in result.mappings()] if result.returns_rows else []

    return run


@pytest.fixture
def audit(sql):
    """`await audit("login_failed")` -> audit_log rows of that action (all rows when no action given)."""

    async def run(action: str | None = None) -> list[dict]:
        if action is None:
            return await sql("SELECT * FROM audit_log ORDER BY id")
        return await sql("SELECT * FROM audit_log WHERE action = :a ORDER BY id", a=action)

    return run


# --------------------------------------------------------------------------- redis

# Choice: fakeredis, not a second real Redis. It supports TTL/EXPIRE/pipelines, needs no extra service, and
# `FakeServer.connected = False` simulates an outage (A-8, B-5) without monkeypatching app code.
# The app reads the client from `app.core.redis._redis` (lazy singleton), so we install ours there.


@pytest_asyncio.fixture
async def redis_server():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    previous = redis_module._redis
    redis_module._redis = client
    yield server
    server.connected = True
    await client.flushall()
    await client.aclose()
    redis_module._redis = previous


@pytest.fixture
def redis(redis_server):
    """The very client the app uses (inspect keys / TTL, `flushall()` simulates window expiry)."""
    return redis_module.get_redis()


@pytest.fixture
def redis_down(redis_server):
    """Call `redis_down()` inside a test to simulate an unavailable Redis from that moment on."""

    def go() -> None:
        redis_server.connected = False

    return go


# --------------------------------------------------------------------------- http client


@pytest_asyncio.fixture
async def client(db_engine, clean_db, redis_server):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
        yield c


# --------------------------------------------------------------------------- factories

_counter = itertools.count(1)


@pytest_asyncio.fixture
async def sport(session_factory) -> int:
    async with session_factory() as s:
        obj = Sport(name="Плавание")
        s.add(obj)
        await s.commit()
        return obj.id


@pytest_asyncio.fixture
async def other_sport(session_factory) -> int:
    async with session_factory() as s:
        obj = Sport(name="Бокс")
        s.add(obj)
        await s.commit()
        return obj.id


@pytest_asyncio.fixture
async def specialty(session_factory) -> int:
    async with session_factory() as s:
        obj = Specialty(name="Спортивная медицина")
        s.add(obj)
        await s.commit()
        return obj.id


@pytest_asyncio.fixture
async def make_user(session_factory, specialty, sport):
    """`await make_user(Role.DOCTOR, is_active=False, coach_id=..., ...)` -> UserInfo. Creates the role profile too."""

    async def make(
        role: Role,
        *,
        email: str | None = None,
        password: str = DEFAULT_PASSWORD,
        is_active: bool = True,
        coach_id: int | None = None,
        can_issue_conclusion: bool = False,
    ) -> UserInfo:
        n = next(_counter)
        email = email or f"{role.value}{n}@example.com"
        async with session_factory() as s:
            user = User(
                email=email,
                password_hash=cached_hash(password),
                role=role,
                last_name="Иванов",
                first_name="Иван",
                middle_name="Иванович",
                phone="+79990000000",
                is_active=is_active,
            )
            s.add(user)
            await s.flush()
            match role:
                case Role.DOCTOR:
                    s.add(
                        DoctorProfile(
                            user_id=user.id, specialty_id=specialty, can_issue_conclusion=can_issue_conclusion
                        )
                    )
                case Role.COACH:
                    s.add(CoachProfile(user_id=user.id, sport_id=sport))
                case Role.ATHLETE:
                    s.add(
                        AthleteProfile(
                            user_id=user.id,
                            birth_date=date(2003, 5, 17),
                            sex=Sex.MALE,
                            sport_id=sport,
                            coach_id=coach_id,
                        )
                    )
                case Role.ADMIN | Role.REGISTRAR:
                    s.add(StaffProfile(user_id=user.id, position="Сотрудник"))
            await s.commit()
            return UserInfo(user.id, email, password, role)

    return make


@pytest_asyncio.fixture
async def admin(make_user):
    return await make_user(Role.ADMIN)


@pytest_asyncio.fixture
async def registrar(make_user):
    return await make_user(Role.REGISTRAR)


@pytest_asyncio.fixture
async def doctor(make_user):
    return await make_user(Role.DOCTOR)


@pytest_asyncio.fixture
async def coach(make_user):
    return await make_user(Role.COACH)


@pytest_asyncio.fixture
async def athlete(make_user, coach):
    """Athlete assigned to `coach`."""
    return await make_user(Role.ATHLETE, coach_id=coach.id)


@pytest_asyncio.fixture
async def users_by_role(admin, registrar, doctor, coach, athlete) -> dict[Role, UserInfo]:
    return {Role.ADMIN: admin, Role.REGISTRAR: registrar, Role.DOCTOR: doctor, Role.COACH: coach, Role.ATHLETE: athlete}


# --------------------------------------------------------------------------- login helpers


async def api_login(client: AsyncClient, user: UserInfo, user_agent: str = "pytest-agent/1.0") -> dict:
    """JSON login -> TokenPair dict. Fails loudly if login does not work."""
    resp = await client.post(
        "/auth/login", json={"email": user.email, "password": user.password}, headers={"User-Agent": user_agent}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def login():
    return api_login


def set_auth_cookies(client: AsyncClient, *, access: str | None = None, refresh: str | None = None) -> None:
    """Install page-auth cookies directly (no login round-trip). Refresh cookie is scoped to /auth like the app's."""
    client.cookies.clear()
    if access:
        client.cookies.set("access_token", access, path="/")
    if refresh:
        client.cookies.set("refresh_token", refresh, path="/auth")


@pytest.fixture
def web_session():
    """`web_session(client, user)` -> client now carries a valid access cookie for `user`."""

    def go(client: AsyncClient, user: UserInfo) -> AsyncClient:
        set_auth_cookies(client, access=user.token)
        return client

    return go


def expired_access_token(user: UserInfo, seconds_ago: int = 60) -> str:

    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "type": "access",
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(seconds=seconds_ago),
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


@pytest.fixture
def expired_token():
    return expired_access_token
