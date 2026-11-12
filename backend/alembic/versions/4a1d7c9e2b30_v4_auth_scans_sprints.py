"""v4: users + ownership, scan jobs, validation sprints; drop report snapshots

Revision ID: 4a1d7c9e2b30
Revises: 2b7a91c4e6f1
"""
from alembic import op
import sqlalchemy as sa

revision = "4a1d7c9e2b30"
down_revision = "2b7a91c4e6f1"
branch_labels = None
depends_on = None


def _ts(name="created_at", nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(300), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    with op.batch_alter_table("business_cases") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_business_cases_owner_id_users", "users", ["owner_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_business_cases_owner_id", ["owner_id"])

    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_case_id", sa.Integer(), sa.ForeignKey("business_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("step", sa.String(100)),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("log", sa.JSON()),
        sa.Column("warnings", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("result", sa.JSON()),
        _ts(),
        _ts("finished_at", nullable=True),
    )
    op.create_index("ix_scan_jobs_business_case_id", "scan_jobs", ["business_case_id"])
    op.create_index("ix_scan_jobs_status", "scan_jobs", ["status"])

    op.create_table(
        "sprints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_case_id", sa.Integer(), sa.ForeignKey("business_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hypothesis_id", sa.Integer(), sa.ForeignKey("hypotheses.id", ondelete="SET NULL")),
        sa.Column("slug", sa.String(32), nullable=False),
        sa.Column("dossier_token", sa.String(64), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("protocol", sa.JSON(), nullable=False),
        sa.Column("kit", sa.JSON()),
        sa.Column("protocol_hash", sa.String(64)),
        _ts("locked_at", nullable=True),
        _ts("concluded_at", nullable=True),
        sa.Column("dossier_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts(),
        _ts("updated_at"),
    )
    op.create_index("ix_sprints_business_case_id", "sprints", ["business_case_id"])
    op.create_index("ix_sprints_hypothesis_id", "sprints", ["hypothesis_id"])
    op.create_index("ix_sprints_slug", "sprints", ["slug"], unique=True)
    op.create_index("ix_sprints_dossier_token", "sprints", ["dossier_token"], unique=True)
    op.create_index("ix_sprints_status", "sprints", ["status"])

    op.create_table(
        "sprint_visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sprint_id", sa.Integer(), sa.ForeignKey("sprints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visitor_hash", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(50)),
        _ts(),
        sa.UniqueConstraint("sprint_id", "visitor_hash", name="uq_sprint_visit_visitor"),
    )
    op.create_index("ix_sprint_visits_sprint_id", "sprint_visits", ["sprint_id"])

    op.create_table(
        "sprint_signups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sprint_id", sa.Integer(), sa.ForeignKey("sprints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visitor_hash", sa.String(64), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("channel", sa.String(50)),
        _ts("excluded_at", nullable=True),
        sa.Column("excluded_reason", sa.String(300)),
        _ts(),
        sa.UniqueConstraint("sprint_id", "email", name="uq_sprint_signup_email"),
    )
    op.create_index("ix_sprint_signups_sprint_id", "sprint_signups", ["sprint_id"])

    op.create_table(
        "sprint_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sprint_id", sa.Integer(), sa.ForeignKey("sprints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("who", sa.String(200)),
        sa.Column("notes", sa.Text()),
        _ts("excluded_at", nullable=True),
        sa.Column("excluded_reason", sa.String(300)),
        _ts(),
    )
    op.create_index("ix_sprint_signals_sprint_id", "sprint_signals", ["sprint_id"])

    op.create_table(
        "sprint_verdicts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sprint_id", sa.Integer(), sa.ForeignKey("sprints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("protocol_hash", sa.String(64), nullable=False),
        sa.Column("evaluation", sa.JSON(), nullable=False),
        _ts(),
    )
    op.create_index("ix_sprint_verdicts_sprint_id", "sprint_verdicts", ["sprint_id"])

    # Report snapshots are retired: the decision brief PDF is generated on
    # demand and never stored.
    op.drop_table("reports")


def downgrade():
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_case_id", sa.Integer(), sa.ForeignKey("business_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(100), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for table in ("sprint_verdicts", "sprint_signals", "sprint_signups", "sprint_visits", "sprints", "scan_jobs"):
        op.drop_table(table)
    with op.batch_alter_table("business_cases") as batch:
        batch.drop_index("ix_business_cases_owner_id")
        batch.drop_constraint("fk_business_cases_owner_id_users", type_="foreignkey")
        batch.drop_column("owner_id")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
