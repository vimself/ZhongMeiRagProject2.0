"""stage 3 user admin

Revision ID: stage_3_user_admin
Revises: stage_2_auth_core
Create Date: 2026-05-09 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "stage_3_user_admin"
down_revision: str | None = "stage_2_auth_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("avatar_path", sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("avatar_path")
