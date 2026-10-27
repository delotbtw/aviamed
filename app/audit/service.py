from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import AuditLog
from app.repositories.system import AuditLogRepository


class AuditService:
    """Only identifiers go to the log, never the data itself."""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = AuditLogRepository(session)

    async def log(
        self,
        *,
        user_id: int | None,
        action: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        ip: str | None = None,
    ) -> None:
        # Written in the caller's transaction. TODO: log reads of medical data too.
        await self.repo.add(
            AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, ip=ip)
        )

    async def recent(self, limit: int = 100, offset: int = 0) -> list[AuditLog]:
        return await self.repo.list_recent(limit=limit, offset=offset)
