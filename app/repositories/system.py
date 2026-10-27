from datetime import datetime

from sqlalchemy import select

from app.models.system import AuditLog, Consent, RefreshToken, StatusHistory
from app.repositories.base import BaseRepository


class ConsentRepository(BaseRepository[Consent]):
    model = Consent

    async def paper_number_taken(self, consent_type: str, paper_number: str) -> bool:
        stmt = select(Consent.id).where(
            Consent.consent_type == consent_type,
            Consent.paper_number == paper_number,
            Consent.revoked_at.is_(None),
        )
        return await self.session.scalar(stmt.limit(1)) is not None


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

    async def get_by_hash(self, token_hash: str, *, for_update: bool = False) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(stmt)

    async def revoke_all_for_user(self, user_id: int, now: datetime) -> list[RefreshToken]:
        """Mark every active token of the user as revoked; returns them (for the Redis blacklist)."""
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .with_for_update()
        )
        tokens = list(await self.session.scalars(stmt))
        for token in tokens:
            token.revoked_at = now
        await self.session.flush()
        return tokens
