from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.auth import User
from app.models.document import Document, KnowledgeChunkV2
from app.models.knowledge_base import KnowledgeBase
from app.security.password import hash_password
from app.services.ingest.chunker import ChunkCandidate
from app.services.ingest.track_a_indexer import TrackAIndexer


@pytest.fixture(autouse=True)
def reset_database() -> None:
    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_reset())


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(text))] for text in texts]


class FakeCache:
    def __init__(self, initial: dict[str, list[float]] | None = None) -> None:
        self.values = {
            f"embedding:{key}": json.dumps(value) for key, value in (initial or {}).items()
        }

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.values[key] = value


def _chunk(index: int, text: str = "内容") -> ChunkCandidate:
    return ChunkCandidate(
        chunk_index=index,
        content=f"{text}-{index}",
        section_path=["A"],
        section_id="section-a",
        page_start=1,
        page_end=1,
        content_type="paragraph",
        tokens=3,
        sha256=f"sha-{index}",
    )


async def _seed_document() -> tuple[str, str]:
    async with AsyncSessionLocal() as session:
        user = User(
            id="user-1",
            username="u",
            display_name="用户",
            role="admin",
            password_hash=hash_password("pass"),
        )
        kb = KnowledgeBase(id="kb-1", name="KB", description="", creator_id=user.id)
        doc = Document(
            id="doc-1",
            knowledge_base_id=kb.id,
            uploader_id=user.id,
            title="文档",
            filename="a.pdf",
            mime="application/pdf",
            size_bytes=10,
            sha256="doc-sha",
            storage_path="a.pdf",
        )
        session.add_all([user, kb, doc])
        await session.commit()
        return kb.id, doc.id


@pytest.mark.asyncio
async def test_embed_batch_uses_configured_batch_size() -> None:
    fake = FakeEmbeddingClient()
    indexer = TrackAIndexer(embedding_client=fake, batch_size=25)
    vectors = await indexer.embed_chunks([_chunk(i) for i in range(26)])
    assert len(vectors) == 26
    assert [len(call) for call in fake.calls] == [25, 1]


@pytest.mark.asyncio
async def test_embed_cache_hit_skips_dashscope() -> None:
    fake = FakeEmbeddingClient()
    cache = FakeCache({"sha-0": [1.0, 2.0]})
    indexer = TrackAIndexer(embedding_client=fake, cache=cache)
    vectors = await indexer.embed_chunks([_chunk(0)])
    assert vectors == [[1.0, 2.0]]
    assert fake.calls == []


@pytest.mark.asyncio
async def test_write_chunks_replaces_existing_rows() -> None:
    kb_id, doc_id = await _seed_document()
    async with AsyncSessionLocal() as session:
        session.add(
            KnowledgeChunkV2(
                knowledge_base_id=kb_id,
                document_id=doc_id,
                chunk_index=99,
                content="旧内容",
                section_path=["old"],
                section_id="old",
                content_type="paragraph",
                doc_kind="other",
                tokens=1,
                sha256="old",
            )
        )
        await session.commit()
    indexer = TrackAIndexer(embedding_client=FakeEmbeddingClient())
    async with AsyncSessionLocal() as session:
        count = await indexer.write_chunks(
            session,
            knowledge_base_id=kb_id,
            document_id=doc_id,
            doc_kind="plan",
            scheme_type=None,
            chunks=[_chunk(0)],
            vectors=[[0.1]],
        )
        await session.commit()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(KnowledgeChunkV2))).scalars().all()
    assert count == 1
    assert len(rows) == 1
    assert rows[0].content == "内容-0"
    assert rows[0].vector == [0.1]
    assert rows[0].vector_native == "[0.1]"
    assert rows[0].sparse
    assert rows[0].sparse_native and rows[0].sparse_native.startswith("{")


@pytest.mark.asyncio
async def test_embedding_failure_does_not_write_rows() -> None:
    class FailingClient:
        async def embed_batch(self, _texts: list[str]) -> list[list[float]]:
            raise RuntimeError("dashscope failed")

    kb_id, doc_id = await _seed_document()
    indexer = TrackAIndexer(embedding_client=FailingClient())
    with pytest.raises(RuntimeError):
        await indexer.embed_chunks([_chunk(0)])
    async with AsyncSessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(KnowledgeChunkV2).where(KnowledgeChunkV2.document_id == doc_id)
                )
            )
            .scalars()
            .all()
        )
    assert kb_id
    assert rows == []
