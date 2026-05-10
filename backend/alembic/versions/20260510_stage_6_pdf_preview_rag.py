"""stage 6 pdf preview and rag metadata

Revision ID: stage_6_pdf_preview_rag
Revises: stage_5_ingest_core
Create Date: 2026-05-10 00:00:00.000000
"""

from __future__ import annotations

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from alembic import op

# revision identifiers, used by Alembic.
revision = "stage_6_pdf_preview_rag"
down_revision = "stage_5_ingest_core"
branch_labels = None
depends_on = None


def _is_sqlite() -> bool:
    bind: Connection = op.get_bind()
    return bind.dialect.name == "sqlite"


def upgrade() -> None:
    if not _is_sqlite():
        _try_execute(
            "CREATE FULLTEXT INDEX ix_kchunks_v2_content_ft ON knowledge_chunks_v2(content)"
        )
        _try_execute(
            "CREATE FULLTEXT INDEX kcv_content_ngram ON knowledge_chunks_v2(content) "
            "WITH PARSER NGRAM PARSER_PROPERTIES=(ngram_token_size=2)"
        )


def downgrade() -> None:
    if not _is_sqlite():
        _try_execute("DROP INDEX kcv_content_ngram ON knowledge_chunks_v2")
        _try_execute("DROP INDEX ix_kchunks_v2_content_ft ON knowledge_chunks_v2")


def _try_execute(sql: str) -> None:
    try:
        op.execute(sql)
    except SQLAlchemyError:
        return
