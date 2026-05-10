from __future__ import annotations

from app.services.ingest.chunker import chunk_outline, count_tokens
from app.services.ingest.outline_parser import parse_outline


def test_chunks_do_not_cross_sections() -> None:
    parsed = parse_outline("# A\n甲\n# B\n乙")
    chunks = chunk_outline(parsed, max_tokens=10, overlap_tokens=0)
    assert {tuple(chunk.section_path) for chunk in chunks} == {("A",), ("B",)}


def test_length_constraint() -> None:
    parsed = parse_outline("# A\n" + "字" * 40)
    chunks = chunk_outline(parsed, max_tokens=10, overlap_tokens=0)
    assert len(chunks) >= 2


def test_semantic_split_by_blank_line() -> None:
    parsed = parse_outline("# A\n第一段\n\n第二段")
    chunks = chunk_outline(parsed, max_tokens=20, overlap_tokens=0)
    assert chunks[0].content == "第一段\n\n第二段"


def test_overlap_keeps_tail() -> None:
    parsed = parse_outline("# A\n第一段很长。\n\n第二段很长。\n\n第三段很长。")
    chunks = chunk_outline(parsed, max_tokens=10, overlap_tokens=4)
    assert len(chunks) >= 2


def test_count_tokens_mixed_text() -> None:
    assert count_tokens("abc 中美 RAG") >= 4


def test_empty_section_has_no_chunks() -> None:
    parsed = parse_outline("# A\n")
    assert chunk_outline(parsed) == []
