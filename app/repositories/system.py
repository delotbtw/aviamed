from sqlalchemy import select

from app.models.system import AuditLog, Consent, RefreshToken, StatusHistory
from app.repositories.base import BaseRepository


class ConsentRepository(BaseRepository[Consent]):
    model = Consent


class StatusHistoryRepository(BaseRepository[StatusHistory]):
    model = StatusHistory

    async def list_for(self, entity_type: str, entity_id: int) -> list[StatusHistory]:
        stmt = (
            select(StatusHistory)
            .where(StatusHistory.entity_type == entity_type, StatusHistory.entity_id == entity_id)
            .order_by(StatusHistory.changed_at)
        )
        return list(await self.session.scalars(stmt))


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def list_recent(self, *, limit: int = 100, offset: int = 0) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return await self.session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
