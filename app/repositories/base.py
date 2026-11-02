from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.exceptions import ConcurrentUpdate, LockTimeout

# lock_timeout expired / the database chose this transaction as a deadlock victim: the client may retry.
RETRYABLE_SQLSTATES = frozenset({"55P03", "40P01"})


def _driver_error(error: DBAPIError) -> Any:
    return getattr(error.orig, "__cause__", None) or error.orig


@contextmanager
def domain_errors() -> Iterator[None]:
    """Lock waits that ended badly and optimistic-lock failures become domain errors for the services."""
    try:
        yield
    except DBAPIError as e:
        if getattr(_driver_error(e), "sqlstate", None) in RETRYABLE_SQLSTATES:
            raise LockTimeout from None
        raise
    except StaleDataError:
        raise ConcurrentUpdate from None


class BaseRepository[T](ABC):
    """Generic CRUD. All queries live in repositories; no business rules here.

    Subclasses must set `model`. Repositories never commit: the service owns the transaction.
    """

    @property
    @abstractmethod
    def model(self) -> type[T]: ...

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: Any) -> T | None:
        return await self.session.get(self.model, id_)

    async def get_for_update(self, id_: Any) -> T | None:
        """Row lock for the duration of a status transition.

        FOR NO KEY UPDATE, not FOR UPDATE: it still serializes writers of the row, but does not conflict with the
        FOR KEY SHARE that foreign-key checks (e.g. audit_log.user_id) take on the same row, so two actors who lock
        each other's rows cannot deadlock through their own audit inserts.
        """
        with domain_errors():
            return await self.session.get(self.model, id_, with_for_update={"key_share": True}, populate_existing=True)

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[T]:
        result = await self.session.scalars(select(self.model).limit(limit).offset(offset))
        return result.all()

    async def list_all(self) -> Sequence[T]:
        """Unpaginated; only for small reference tables (sports, specialties)."""
        return (await self.session.scalars(select(self.model))).all()

    async def add(self, obj: T) -> T:
        self.session.add(obj)
        with domain_errors():
            await self.session.flush()
        return obj

    async def delete(self, obj: T) -> None:
        await self.session.delete(obj)
        await self.session.flush()


def violated_constraint(error: IntegrityError) -> str | None:
    """Name of the constraint/index behind an IntegrityError (asyncpg), or None if unknown."""
    return getattr(_driver_error(error), "constraint_name", None)
