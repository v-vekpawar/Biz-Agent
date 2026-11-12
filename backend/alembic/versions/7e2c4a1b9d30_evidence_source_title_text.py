"""Store evidence source titles without a 300-character ceiling.

Revision ID: 7e2c4a1b9d30
Revises: 2b7a91c4e6f1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "7e2c4a1b9d30"
down_revision = "2b7a91c4e6f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite ignores VARCHAR length limits, so no physical change is needed
    # there. PostgreSQL enforces VARCHAR(300), so widen it to TEXT.
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "evidence",
            "source_title",
            existing_type=sa.String(length=300),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Preserve downgrade safety if a later version stored titles longer than
    # the old limit. Truncation is explicit because VARCHAR(300) cannot hold
    # those values.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "UPDATE evidence SET source_title = left(source_title, 300) "
            "WHERE char_length(source_title) > 300"
        )
        op.alter_column(
            "evidence",
            "source_title",
            existing_type=sa.Text(),
            type_=sa.String(length=300),
            existing_nullable=False,
        )
