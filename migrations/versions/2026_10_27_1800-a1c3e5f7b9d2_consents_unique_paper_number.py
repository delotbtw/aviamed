"""unique active consent paper number

Revision ID: a1c3e5f7b9d2
Revises: 378a416b2f4b
Create Date: 2026-10-27 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1c3e5f7b9d2"
down_revision: Union[str, Sequence[str], None] = "378a416b2f4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "uq_consents_type_paper_number_active",
        "consents",
        ["consent_type", "paper_number"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_consents_type_paper_number_active",
        table_name="consents",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
