"""stage 4 knowledge base

Revision ID: stage_4_knowledge_base
Revises: stage_3_user_admin
Create Date: 2026-05-09 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "stage_4_knowledge_base"
down_revision: str | None = "stage_3_user_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("creator_id", sa.String(length=36), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
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
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_bases_creator_id", "knowledge_bases", ["creator_id"])
    op.create_index("ix_knowledge_bases_is_active", "knowledge_bases", ["is_active"])

    op.create_table(
        "knowledge_base_permissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
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
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_base_id", "user_id", name="uq_kb_permission_user"),
    )
    op.create_index("ix_kb_permissions_user_id", "knowledge_base_permissions", ["user_id"])
    op.create_index("ix_kb_permissions_kb_id", "knowledge_base_permissions", ["knowledge_base_id"])


def downgrade() -> None:
    op.drop_index("ix_kb_permissions_kb_id", table_name="knowledge_base_permissions")
    op.drop_index("ix_kb_permissions_user_id", table_name="knowledge_base_permissions")
    op.drop_table("knowledge_base_permissions")
    op.drop_index("ix_knowledge_bases_is_active", table_name="knowledge_bases")
    op.drop_index("ix_knowledge_bases_creator_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
