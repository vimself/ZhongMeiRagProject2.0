from __future__ import annotations

from app.services.ingest.chunker import ChunkCandidate
from app.services.ingest.track_b_indexer import build_page_index_text, truncate_utf8


def _chunk(index: int, content: str) -> ChunkCandidate:
    return ChunkCandidate(
        chunk_index=index,
        content=content,
        section_path=["A"],
        section_id="s1",
        page_start=1,
        page_end=1,
        content_type="paragraph",
        tokens=len(content),
        sha256=f"sha-{index}",
    )


def test_truncate_utf8_respects_byte_limit_with_chinese_text() -> None:
    result = truncate_utf8("城市综合地下管线" * 100, max_bytes=80)

    assert len(result.encode("utf-8")) <= 80
    assert result.endswith("[page_index_text_truncated]")


def test_build_page_index_text_deduplicates_and_truncates() -> None:
    chunks = [
        _chunk(1, "重复内容"),
        _chunk(1, "重复内容"),
        _chunk(2, "城市综合地下管线" * 100),
    ]

    result = build_page_index_text(chunks, max_bytes=120)

    assert result.count("重复内容") == 1
    assert len(result.encode("utf-8")) <= 120
    assert result.endswith("[page_index_text_truncated]")
