from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def enum_col(enum_cls: type[StrEnum], name: str) -> Enum:
    """Enum stored as VARCHAR + CHECK constraint (docs/04 section 7), values not names."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class IdMixin:
    id: Mapped[int] = mapped_column(primary_key=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UpdatedByMixin:
    """Authorship of the last change (docs/04 section 7). Nullable: system actions have no user."""

    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class AuthorshipMixin(UpdatedByMixin):
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
