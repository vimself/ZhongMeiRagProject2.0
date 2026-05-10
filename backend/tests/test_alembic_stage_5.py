from __future__ import annotations

import asyncio

import pytest

from app.db.base import Base
from app.db.session import engine


@pytest.fixture(autouse=True)
def reset_database() -> None:
    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_reset())


def test_stage_5_tables_exist_after_metadata_upgrade() -> None:
    async def _check() -> dict[str, bool]:
        async with engine.begin() as conn:
            names = [
                "documents",
                "document_parse_results",
                "document_assets",
                "document_ingest_jobs",
                "ingest_step_receipts",
                "ingest_callback_receipts",
                "knowledge_chunks_v2",
                "knowledge_page_index_v2",
            ]
            result = {}
            for name in names:
                result[name] = await conn.run_sync(
                    lambda sync_conn, table_name=name: sync_conn.dialect.has_table(
                        sync_conn, table_name
                    )
                )
            return result

    assert all(asyncio.run(_check()).values())
