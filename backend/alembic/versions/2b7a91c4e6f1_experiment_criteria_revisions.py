"""immutable experiment criteria revisions

Revision ID: 2b7a91c4e6f1
Revises: 0f50037cca0a
"""
from alembic import op
import sqlalchemy as sa
revision = "2b7a91c4e6f1"
down_revision = "0f50037cca0a"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("experiment_criteria_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("success_criteria", sa.Text()),
        sa.Column("failure_criteria", sa.Text()),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("experiment_id", "version", name="uq_experiment_criteria_version"))
    op.create_index("ix_experiment_criteria_revisions_experiment_id", "experiment_criteria_revisions", ["experiment_id"])
def downgrade():
    op.drop_index("ix_experiment_criteria_revisions_experiment_id", table_name="experiment_criteria_revisions")
    op.drop_table("experiment_criteria_revisions")
