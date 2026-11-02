"""schedule: one active appointment per slot, no overlapping slots of a doctor, free-slot index

Revision ID: b7d2f4a6c8e1
Revises: a1c3e5f7b9d2
Create Date: 2026-10-28 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7d2f4a6c8e1"
down_revision: Union[str, Sequence[str], None] = "a1c3e5f7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. A cancelled appointment stays as history and must not block the slot: unique only among non-cancelled ones.
    op.drop_constraint("uq_appointments_slot_id", "appointments", type_="unique")
    op.create_index(
        "uq_appointments_slot_active",
        "appointments",
        ["slot_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )

    # 2. Slots of one doctor do not overlap. CREATE EXTENSION needs a role allowed to do it (the DB owner).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_check_constraint(op.f("ck_slots_end_after_start"), "slots", "end_at > start_at")
    op.create_exclude_constraint(
        "ex_slots_no_overlap",
        "slots",
        ("doctor_id", "="),
        (sa.literal_column("tstzrange(start_at, end_at, '[)')"), "&&"),
        using="gist",
    )
    # uq_slots_doctor_id is redundant now: equal starts of positive-length slots overlap, which the exclusion constraint
    # rejects (and its error is the one reported). Keeping both would leave the reported constraint to index order.
    op.drop_constraint("uq_slots_doctor_id", "slots", type_="unique")

    # 3. Free-slot list.
    op.create_index(
        "ix_slots_free_start_at", "slots", ["start_at"], unique=False, postgresql_where=sa.text("status = 'free'")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_slots_free_start_at", table_name="slots", postgresql_where=sa.text("status = 'free'"))
    op.create_unique_constraint(op.f("uq_slots_doctor_id"), "slots", ["doctor_id", "start_at"])
    op.drop_constraint("ex_slots_no_overlap", "slots")  # type_ "exclude" is unknown to Alembic
    op.drop_constraint(op.f("ck_slots_end_after_start"), "slots", type_="check")
    # btree_gist stays: other objects may rely on it and dropping an extension is not part of reverting this schema.

    # The full unique index cannot come back while a slot has several appointments (cancelled history + a new one).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM appointments GROUP BY slot_id HAVING count(*) > 1) THEN
                RAISE EXCEPTION 'Cannot downgrade: some slots have several appointments (cancelled history). '
                    'Remove the cancelled duplicates first.';
            END IF;
        END $$
        """
    )
    op.drop_index(
        "uq_appointments_slot_active", table_name="appointments", postgresql_where=sa.text("status <> 'cancelled'")
    )
    op.create_unique_constraint("uq_appointments_slot_id", "appointments", ["slot_id"])
