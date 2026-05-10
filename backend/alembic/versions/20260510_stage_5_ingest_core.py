"""stage 5 ingest core

Revision ID: stage_5_ingest_core
Revises: stage_4_knowledge_base
Create Date: 2026-05-10 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "stage_5_ingest_core"
down_revision: str | None = "stage_4_knowledge_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON()


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("uploader_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("doc_kind", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("scheme_type", sa.String(length=64), nullable=True),
        sa.Column("is_standard_clause", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_documents_kb_status_created",
        "documents",
        ["knowledge_base_id", "status", "created_at"],
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "document_parse_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("ocr_session_id", sa.String(length=128), nullable=True),
        sa.Column("markdown_path", sa.String(length=1024), nullable=False),
        sa.Column("markdown_sha256", sa.String(length=64), nullable=False),
        sa.Column("outline_json", _json_type(), nullable=False),
        sa.Column("stats_json", _json_type(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )

    op.create_table(
        "document_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("bbox_json", _json_type(), nullable=True),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("caption", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_assets_document_id", "document_assets", ["document_id"])

    op.create_table(
        "document_ingest_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_ingest_jobs_available_status",
        "document_ingest_jobs",
        ["available_at", "status"],
    )
    op.create_index("ix_document_ingest_jobs_document_id", "document_ingest_jobs", ["document_id"])

    op.create_table(
        "ingest_step_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", _json_type(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["job_id"], ["document_ingest_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_ingest_step_receipts_job_step", "ingest_step_receipts", ["job_id", "step"])
    op.create_index("ix_ingest_step_receipts_key", "ingest_step_receipts", ["idempotency_key"])

    op.create_table(
        "ingest_callback_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("payload_json", _json_type(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )

    op.create_table(
        "knowledge_chunks_v2",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("section_path", _json_type(), nullable=False),
        sa.Column("section_id", sa.String(length=64), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("bbox_json", _json_type(), nullable=True),
        sa.Column("content_type", sa.String(length=32), nullable=False, server_default="paragraph"),
        sa.Column("doc_kind", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("scheme_type", sa.String(length=64), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("vector", _json_type(), nullable=True),
        sa.Column("sparse", _json_type(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kchunks_v2_kb_kind_scheme",
        "knowledge_chunks_v2",
        ["knowledge_base_id", "doc_kind", "scheme_type"],
    )
    op.create_index(
        "ix_kchunks_v2_doc_section", "knowledge_chunks_v2", ["document_id", "section_id"]
    )
    op.create_index("ix_kchunks_v2_document_id", "knowledge_chunks_v2", ["document_id"])
    if not _is_sqlite():
        op.execute("ALTER TABLE knowledge_chunks_v2 MODIFY COLUMN vector VECTOR(1024)")
        op.execute("ALTER TABLE knowledge_chunks_v2 MODIFY COLUMN sparse SPARSE_VECTOR")
        op.execute(
            "CREATE VECTOR INDEX ix_kchunks_v2_vector "
            "ON knowledge_chunks_v2(vector) WITH (distance=cosine, type=hnsw)"
        )
        op.execute("CREATE SPARSE VECTOR INDEX ix_kchunks_v2_sparse ON knowledge_chunks_v2(sparse)")

    op.create_table(
        "knowledge_page_index_v2",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("section_map_json", _json_type(), nullable=False),
        sa.Column("block_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kpage_index_v2_doc_page",
        "knowledge_page_index_v2",
        ["document_id", "page_no"],
    )
    op.create_index("ix_kpage_index_v2_document_id", "knowledge_page_index_v2", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_kpage_index_v2_document_id", table_name="knowledge_page_index_v2")
    op.drop_index("ix_kpage_index_v2_doc_page", table_name="knowledge_page_index_v2")
    op.drop_table("knowledge_page_index_v2")
    if not _is_sqlite():
        op.execute("DROP INDEX ix_kchunks_v2_sparse ON knowledge_chunks_v2")
        op.execute("DROP INDEX ix_kchunks_v2_vector ON knowledge_chunks_v2")
    op.drop_index("ix_kchunks_v2_document_id", table_name="knowledge_chunks_v2")
    op.drop_index("ix_kchunks_v2_doc_section", table_name="knowledge_chunks_v2")
    op.drop_index("ix_kchunks_v2_kb_kind_scheme", table_name="knowledge_chunks_v2")
    op.drop_table("knowledge_chunks_v2")
    op.drop_table("ingest_callback_receipts")
    op.drop_index("ix_ingest_step_receipts_key", table_name="ingest_step_receipts")
    op.drop_index("ix_ingest_step_receipts_job_step", table_name="ingest_step_receipts")
    op.drop_table("ingest_step_receipts")
    op.drop_index("ix_document_ingest_jobs_document_id", table_name="document_ingest_jobs")
    op.drop_index("ix_document_ingest_jobs_available_status", table_name="document_ingest_jobs")
    op.drop_table("document_ingest_jobs")
    op.drop_index("ix_document_assets_document_id", table_name="document_assets")
    op.drop_table("document_assets")
    op.drop_table("document_parse_results")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_kb_status_created", table_name="documents")
    op.drop_table("documents")
