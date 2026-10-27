from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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
        """Row lock for the duration of a status transition."""
        return await self.session.get(self.model, id_, with_for_update=True)

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[T]:
        result = await self.session.scalars(select(self.model).limit(limit).offset(offset))
        return result.all()

    async def add(self, obj: T) -> T:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def delete(self, obj: T) -> None:
        await self.session.delete(obj)
        await self.session.flush()
