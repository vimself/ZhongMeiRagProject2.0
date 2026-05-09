"""stage 2 auth core

Revision ID: stage_2_auth_core
Revises:
Create Date: 2026-05-09 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "stage_2_auth_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("require_password_change", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "login_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_jti", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("refresh_token_jti", name="uq_login_records_refresh_token_jti"),
    )
    op.create_index("ix_login_records_user_id", "login_records", ["user_id"])

    op.create_table(
        "auth_login_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_auth_login_attempts_subject_ip_created",
        "auth_login_attempts",
        ["subject", "ip_address", "created_at"],
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", "created_at"])
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_auth_login_attempts_subject_ip_created", table_name="auth_login_attempts")
    op.drop_table("auth_login_attempts")
    op.drop_index("ix_login_records_user_id", table_name="login_records")
    op.drop_table("login_records")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_table("users")
