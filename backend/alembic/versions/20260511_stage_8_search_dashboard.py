"""stage 8 search dashboard

Revision ID: stage_8_search_dashboard
Revises: stage_7_rag_chat
Create Date: 2026-05-11 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "stage_8_search_dashboard"
down_revision: str | None = "stage_7_rag_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON()


def upgrade() -> None:
    op.create_table(
        "search_export_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="json"),
        sa.Column("filters_json", _json_type(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sej_user_created", "search_export_jobs", ["user_id", "created_at"])
    op.create_index("ix_sej_status_created", "search_export_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_sej_status_created", table_name="search_export_jobs")
    op.drop_index("ix_sej_user_created", table_name="search_export_jobs")
    op.drop_table("search_export_jobs")
