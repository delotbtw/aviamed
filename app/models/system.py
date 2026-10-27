from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuthorshipMixin, Base, IdMixin, TimestampMixin


class Consent(IdMixin, TimestampMixin, AuthorshipMixin, Base):
    """Paper consent registry: only number and dates, no scans (docs/08)."""

    __tablename__ = "consents"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    consent_type: Mapped[str] = mapped_column(String(64))
    paper_number: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[date] = mapped_column(Date)
    revoked_at: Mapped[date | None] = mapped_column(Date)


class StatusHistory(IdMixin, Base):
    __tablename__ = "status_history"

    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[int] = mapped_column(index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    comment: Mapped[str | None] = mapped_column(Text)


class AuditLog(IdMixin, Base):
    """Only identifiers, never the data itself (GOST R ISO 27789)."""

    __tablename__ = "audit_log"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[int | None]
    ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RefreshToken(IdMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
