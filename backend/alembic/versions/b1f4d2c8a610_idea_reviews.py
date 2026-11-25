"""Idea reviews: the pre-scan AI analysis of the idea write-up.

Revision ID: b1f4d2c8a610
Revises: 7e2c4a1b9d30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b1f4d2c8a610"
down_revision = "7e2c4a1b9d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idea_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "business_case_id",
            sa.Integer(),
            sa.ForeignKey("business_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_idea_reviews_business_case_id", "idea_reviews", ["business_case_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_idea_reviews_business_case_id", table_name="idea_reviews")
    op.drop_table("idea_reviews")
