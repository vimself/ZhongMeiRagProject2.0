"""normalize business timestamps to Beijing time

Revision ID: beijing_time_records
Revises: stage_8_search_dashboard
Create Date: 2026-05-13 01:10:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "beijing_time_records"
down_revision: str | None = "stage_8_search_dashboard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


BUSINESS_TIME_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("users", ("last_login_at", "created_at", "updated_at")),
    ("login_records", ("revoked_at", "created_at")),
    ("auth_login_attempts", ("created_at",)),
    ("audit_logs", ("created_at",)),
    ("knowledge_bases", ("created_at", "updated_at")),
    ("knowledge_base_permissions", ("created_at", "updated_at")),
    ("documents", ("created_at", "updated_at")),
    ("document_parse_results", ("created_at",)),
    ("document_assets", ("created_at",)),
    ("document_ingest_jobs", ("available_at", "created_at", "updated_at")),
    ("ingest_step_receipts", ("created_at",)),
    ("ingest_callback_receipts", ("received_at",)),
    ("knowledge_chunks_v2", ("created_at",)),
    ("knowledge_page_index_v2", ("created_at",)),
    ("chat_sessions", ("created_at", "updated_at")),
    ("chat_messages", ("created_at",)),
    ("chat_message_citations", ("created_at",)),
    ("rag_eval_runs", ("created_at",)),
    ("search_export_jobs", ("created_at", "updated_at", "expires_at")),
)


def _shift_expression(dialect_name: str, column: str, hours: int) -> str:
    if dialect_name == "sqlite":
        sign = "+" if hours >= 0 else ""
        return f"datetime({column}, '{sign}{hours} hours')"
    if hours >= 0:
        return f"DATE_ADD({column}, INTERVAL {hours} HOUR)"
    return f"DATE_SUB({column}, INTERVAL {abs(hours)} HOUR)"


def _shift_business_columns(hours: int) -> None:
    dialect_name = op.get_bind().dialect.name
    for table_name, columns in BUSINESS_TIME_COLUMNS:
        for column in columns:
            expression = _shift_expression(dialect_name, column, hours)
            op.execute(
                f"UPDATE {table_name} SET {column} = {expression} WHERE {column} IS NOT NULL"
            )


def upgrade() -> None:
    _shift_business_columns(8)


def downgrade() -> None:
    _shift_business_columns(-8)
