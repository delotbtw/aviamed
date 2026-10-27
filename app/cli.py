"""Management commands (password comes from an env variable or a prompt, never from argv):

python -m app.cli create-admin --email ...      # ADMIN_PASSWORD
python -m app.cli seed-demo                     # DEMO_PASSWORD (optional), demo data only
"""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Awaitable, Callable

import app.models  # noqa: F401  (register all mappers)
from app.core.config import get_settings
from app.core.db import Database
from app.core.exceptions import Conflict
from app.core.rbac import Role
from app.core.security import Argon2PasswordHasher
from app.core.uow import SqlAlchemyUnitOfWork
from app.core.validators import check_password_policy, normalize_email
from app.models.user import StaffProfile
from app.repositories.reference import SpecialtyRepository, SportRepository
from app.repositories.system import ConsentRepository
from app.repositories.user import (
    AthleteProfileRepository,
    CoachProfileRepository,
    DoctorProfileRepository,
    StaffProfileRepository,
    UserRepository,
)
from app.seed import DEMO_PASSWORD, DemoLogin, DemoSeeder
from app.users.accounts import AccountCreator


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


async def seed_demo(db: Database, password: str = DEMO_PASSWORD) -> list[DemoLogin]:
    async with db.sessions() as session:
        users = UserRepository(session)
        seeder = DemoSeeder(
            AccountCreator(users, Argon2PasswordHasher(), SqlAlchemyUnitOfWork(session)),
            users,
            SportRepository(session),
            SpecialtyRepository(session),
            DoctorProfileRepository(session),
            CoachProfileRepository(session),
            StaffProfileRepository(session),
            AthleteProfileRepository(session),
            ConsentRepository(session),
            password,
        )
        logins = await seeder.seed()
        await session.commit()
        return logins


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
    custom_password = os.environ.get("DEMO_PASSWORD")
    password = custom_password or DEMO_PASSWORD
    try:
        check_password_policy(password)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    logins = asyncio.run(run_with_database(lambda db: seed_demo(db, password)))
    print("Demo accounts (for local demos only):")
    for login in logins:
        shown = "(from DEMO_PASSWORD)" if custom_password else login.password  # only the public default is printed
        print(f"  {login.role.value:<10} {login.email:<28} {shown}  {'created' if login.created else 'exists'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create the first administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--last-name", default="Администратор")
    admin.add_argument("--first-name", default="Системный")
    admin.set_defaults(handler=_cmd_create_admin)
    seed = sub.add_parser("seed-demo", help="idempotently create demo reference data and one user per role")
    seed.add_argument("--force", action="store_true", help="allow running with DEBUG=false (local stands only)")
    seed.set_defaults(handler=_cmd_seed_demo)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
