"""Management commands (password comes from an env variable or a prompt, never from argv):

python -m app.cli create-admin --email ...      # ADMIN_PASSWORD
python -m app.cli seed-demo                     # DEMO_PASSWORD (optional), demo data only
"""

import argparse
import asyncio
import getpass
import os
import sys
from collections import Counter
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select

import app.models  # noqa: F401  (register all mappers)
from app.audit.service import AuditService
from app.core.clock import SystemClock
from app.core.config import get_settings
from app.core.db import Database
from app.core.exceptions import Conflict
from app.core.local_time import LocalCalendar
from app.core.rbac import Role
from app.core.security import Argon2PasswordHasher
from app.core.uow import SqlAlchemyUnitOfWork
from app.core.validators import check_password_policy, normalize_email
from app.models.user import StaffProfile, User
from app.repositories.reference import SpecialtyRepository, SportRepository
from app.repositories.schedule import AppointmentRepository, SlotRepository
from app.repositories.system import AuditLogRepository, ConsentRepository, StatusHistoryRepository
from app.repositories.user import (
    AthleteProfileRepository,
    CoachProfileRepository,
    DoctorProfileRepository,
    StaffProfileRepository,
    UserRepository,
)
from app.seed import (
    DEMO_DOMAIN,
    DEMO_PASSWORD,
    CachedHasher,
    DemoLogin,
    DemoReference,
    DemoResult,
    DemoSeeder,
    DemoUsers,
)
from app.seed_schedule import DemoAppointments, DemoSlots
from app.services.status import StatusChanger
from app.users.accounts import AccountCreator

ATHLETES_SHOWN = 3


async def run_with_database[T](action: Callable[[Database], Awaitable[T]]) -> T:
    """Composition root for commands: own Database, disposed at the end."""
    db = Database(get_settings().database_url)
    try:
        return await action(db)
    finally:
        await db.dispose()


def _read_password() -> str:
    password = os.environ.get("ADMIN_PASSWORD")
    if password:
        return password
    if not sys.stdin.isatty():
        raise SystemExit("Set ADMIN_PASSWORD or run the command in a terminal")
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    return password


async def create_admin(db: Database, email: str, password: str, last_name: str, first_name: str) -> None:
    async with db.sessions() as session:
        accounts = AccountCreator(UserRepository(session), Argon2PasswordHasher(), SqlAlchemyUnitOfWork(session))
        user = await accounts.create(
            email=email,
            password=password,
            role=Role.ADMIN,
            last_name=last_name,
            first_name=first_name,
            middle_name=None,
            phone=None,
        )
        await StaffProfileRepository(session).add(StaffProfile(user_id=user.id))
        await session.commit()


class ForeignDatabase(Exception):
    """The database holds real (non-demo) users."""


async def seed_demo_full(db: Database, password: str = DEMO_PASSWORD) -> DemoResult:
    """Composition root of the demo seed: one session, blocks committed by `DemoSeeder`."""
    async with db.sessions() as session:
        foreign = await session.scalar(
            select(func.count()).select_from(User).where(~User.email.like(f"%@{DEMO_DOMAIN}"))
        )
    if foreign:
        raise ForeignDatabase
    settings = get_settings()
    clock = SystemClock()
    calendar = LocalCalendar(settings.schedule_timezone)
    async with db.sessions() as session:
        uow = SqlAlchemyUnitOfWork(session)
        users = UserRepository(session)
        slots = SlotRepository(session)
        status = StatusChanger(StatusHistoryRepository(session))
        audit = AuditService(AuditLogRepository(session))
        accounts = AccountCreator(users, CachedHasher(Argon2PasswordHasher()), uow)
        seeder = DemoSeeder(
            uow,
            DemoReference(SportRepository(session), SpecialtyRepository(session)),
            DemoUsers(
                accounts,
                users,
                DoctorProfileRepository(session),
                CoachProfileRepository(session),
                StaffProfileRepository(session),
                AthleteProfileRepository(session),
                ConsentRepository(session),
                clock,
                calendar,
                password,
            ),
            DemoSlots(uow, slots, status, audit, clock, calendar),
            DemoAppointments(uow, slots, AppointmentRepository(session), status, audit, clock, calendar, settings),
        )
        return await seeder.seed()


async def seed_demo(db: Database, password: str = DEMO_PASSWORD) -> list[DemoLogin]:
    return (await seed_demo_full(db, password)).logins


def _cmd_create_admin(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    try:
        password = _read_password()
        check_password_policy(password, email)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    try:
        asyncio.run(run_with_database(lambda db: create_admin(db, email, password, args.last_name, args.first_name)))
    except Conflict as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Administrator {email} created")
    return 0


def _cmd_seed_demo(args: argparse.Namespace) -> int:
    if not get_settings().debug and not args.force:
        print(
            "Error: seed-demo creates accounts with a publicly known password; it runs only with DEBUG=true "
            "or an explicit --force (local/demo stands only).",
            file=sys.stderr,
        )
        return 1
    if os.environ.get("ALLOW_DEMO_SEED") != "1":
        print(
            "Error: seed-demo also needs the environment variable ALLOW_DEMO_SEED=1 (it is absent from a production "
            ".env on purpose).",
            file=sys.stderr,
        )
        return 1
    custom_password = os.environ.get("DEMO_PASSWORD")
    password = custom_password or DEMO_PASSWORD
    try:
        check_password_policy(password)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    try:
        result = asyncio.run(run_with_database(lambda db: seed_demo_full(db, password)))
    except ForeignDatabase:
        print(
            f"Error: в БД есть пользователи не на @{DEMO_DOMAIN}, похоже на боевую БД: демо-данные не создаются.",
            file=sys.stderr,
        )
        return 1
    _print_summary(result, custom_password=bool(custom_password))
    return 0


def _print_summary(result: DemoResult, *, custom_password: bool) -> None:
    print("Demo accounts (for local demos only):")
    athletes = [login for login in result.logins if login.role is Role.ATHLETE]
    shown_logins = [login for login in result.logins if login.role is not Role.ATHLETE] + athletes[:ATHLETES_SHOWN]
    for login in shown_logins:
        shown = "(from DEMO_PASSWORD)" if custom_password else login.password  # only the public default is printed
        print(f"  {login.role.value:<10} {login.email:<34} {shown}  {'created' if login.created else 'exists'}")
    if len(athletes) > ATHLETES_SHOWN:
        print(f"  ... и ещё {len(athletes) - ATHLETES_SHOWN} спортсменов (demo-athlete-N@example.com)")
    by_role = Counter(login.role.value for login in result.logins)
    created = sum(login.created for login in result.logins)
    print(f"Created now: users {created}, slots {result.slots_created}, appointments {_appts(result)}")
    print("Totals by role: " + ", ".join(f"{role} {n}" for role, n in by_role.items()))


def _appts(result: DemoResult) -> str:
    total = sum(result.appointments_created.values())
    if not total:
        return "0"
    return f"{total} ({', '.join(f'{k} {v}' for k, v in sorted(result.appointments_created.items()))})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create the first administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--last-name", default="Администратор")
    admin.add_argument("--first-name", default="Системный")
    admin.set_defaults(handler=_cmd_create_admin)
    seed = sub.add_parser("seed-demo", help="idempotently create demo users, slots and appointments")
    seed.add_argument("--force", action="store_true", help="allow running with DEBUG=false (local stands only)")
    seed.set_defaults(handler=_cmd_seed_demo)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
