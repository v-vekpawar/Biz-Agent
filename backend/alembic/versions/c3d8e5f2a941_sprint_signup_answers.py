"""Structured answers on sprint signups: one page can ask up to three questions.

Revision ID: c3d8e5f2a941
Revises: b1f4d2c8a610
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c3d8e5f2a941"
down_revision = "b1f4d2c8a610"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sprint_signups", sa.Column("answers", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sprint_signups", "answers")
