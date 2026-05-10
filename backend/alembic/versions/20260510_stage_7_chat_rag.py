"""stage 7 rag chat

Revision ID: stage_7_rag_chat
Revises: stage_6_pdf_preview_rag
Create Date: 2026-05-10 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from alembic import op

revision: str = "stage_7_rag_chat"
down_revision: str | None = "stage_6_pdf_preview_rag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON()


def upgrade() -> None:
    if not _is_sqlite():
        _try_execute("ALTER TABLE knowledge_chunks_v2 ADD COLUMN vector_native VECTOR(1024)")
        _try_execute("ALTER TABLE knowledge_chunks_v2 ADD COLUMN sparse_native SPARSEVECTOR")
        _try_execute(
            "CREATE VECTOR INDEX kcv_vec_native "
            "ON knowledge_chunks_v2(vector_native) WITH (distance=cosine, type=hnsw)"
        )
        _try_execute(
            "CREATE VECTOR INDEX kcv_sparse_native "
            "ON knowledge_chunks_v2(sparse_native) "
            "WITH (lib=vsag, type=sindi, distance=inner_product)"
        )
        _try_execute(
            "CREATE FULLTEXT INDEX kcv_content_ngram ON knowledge_chunks_v2(content) "
            "WITH PARSER NGRAM PARSER_PROPERTIES=(ngram_token_size=2)"
        )

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="新会话"),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_sessions_user_updated", "chat_sessions", ["user_id", "updated_at"])
    op.create_index("ix_chat_sessions_kb", "chat_sessions", ["knowledge_base_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("usage_json", _json_type(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
    )

    op.create_table(
        "chat_message_citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=True),
        sa.Column("document_title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("section_path_json", _json_type(), nullable=False),
        sa.Column("section_text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("bbox_json", _json_type(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_citations_message", "chat_message_citations", ["message_id"])
    op.create_index("ix_chat_citations_document", "chat_message_citations", ["document_id"])

    op.create_table(
        "rag_eval_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_key", sa.String(length=64), nullable=False),
        sa.Column("golden_file", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("summary_json", _json_type(), nullable=False),
        sa.Column("metrics_json", _json_type(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_eval_runs_run_key_created", "rag_eval_runs", ["run_key", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_rag_eval_runs_run_key_created", table_name="rag_eval_runs")
    op.drop_table("rag_eval_runs")
    op.drop_index("ix_chat_citations_document", table_name="chat_message_citations")
    op.drop_index("ix_chat_citations_message", table_name="chat_message_citations")
    op.drop_table("chat_message_citations")
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_kb", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_updated", table_name="chat_sessions")
    op.drop_table("chat_sessions")


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _try_execute(sql: str) -> None:
    try:
        op.execute(sql)
    except SQLAlchemyError:
        return
