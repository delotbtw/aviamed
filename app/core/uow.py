"""Transaction boundary seen by services: they commit through this abstraction, not through the ORM session."""

from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def set_lock_timeout(self, milliseconds: int) -> None:
        """Limit the wait for row locks in the current transaction."""
        ...


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def set_lock_timeout(self, milliseconds: int) -> None:
        await self.session.execute(text("SELECT set_config('lock_timeout', :ms, true)"), {"ms": str(milliseconds)})
