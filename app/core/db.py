from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


class Database:
    """Engine and session factory. The engine object is created by the first `get_database()` call (app assembly)
    and opens no connection until first use; it is disposed on shutdown (lifespan)."""

    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()


@lru_cache
def get_database() -> Database:
    return Database(get_settings().database_url)


async def dispose_database() -> None:
    """Shutdown hook: only disposes if the database was ever used."""
    if get_database.cache_info().currsize:
        await get_database().dispose()
        get_database.cache_clear()


async def get_session(db: Annotated[Database, Depends(get_database)]) -> AsyncIterator[AsyncSession]:
    """One session (and one transaction) per request; services decide when to commit."""
    async with db.sessions() as session:
        yield session
