from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

from app.core.config import get_settings
from app.services.ingest.outline_parser import OutlineParseResult, ParsedSection

SENTENCE_RE = re.compile(r"(?<=[。！？；.!?;])\s+")


@dataclass(frozen=True)
class ChunkCandidate:
    chunk_index: int
    content: str
    section_path: list[str]
    section_id: str
    page_start: int | None
    page_end: int | None
    content_type: str
    tokens: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def chunk_outline(
    parsed: OutlineParseResult,
    *,
    max_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[ChunkCandidate]:
    settings = get_settings()
    limit = max_tokens or settings.chunk_tokens
    overlap = overlap_tokens if overlap_tokens is not None else settings.chunk_overlap
    chunks: list[ChunkCandidate] = []
    for section in parsed.sections:
        chunks.extend(
            _chunk_section(section, start_index=len(chunks), limit=limit, overlap=overlap)
        )
    return chunks


def count_tokens(text: str) -> int:
    ascii_words = re.findall(r"[A-Za-z0-9_]+", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    other_chars = max(0, len(text) - sum(len(word) for word in ascii_words) - len(chinese_chars))
    return len(ascii_words) + len(chinese_chars) + other_chars // 4


def _chunk_section(
    section: ParsedSection,
    *,
    start_index: int,
    limit: int,
    overlap: int,
) -> list[ChunkCandidate]:
    pieces = _semantic_pieces(section.content)
    if not pieces:
        return []
    result: list[ChunkCandidate] = []
    current: list[str] = []
    current_tokens = 0
    for piece in pieces:
        piece_tokens = count_tokens(piece)
        if current and current_tokens + piece_tokens > limit:
            result.append(_build_chunk(section, start_index + len(result), "\n\n".join(current)))
            current = _tail_overlap(current, overlap)
            current_tokens = count_tokens("\n\n".join(current))
        if piece_tokens > limit:
            for hard_piece in _hard_split(piece, limit):
                if current:
                    result.append(
                        _build_chunk(section, start_index + len(result), "\n\n".join(current))
                    )
                    current = _tail_overlap(current, overlap)
                result.append(_build_chunk(section, start_index + len(result), hard_piece))
                current = []
                current_tokens = 0
            continue
        current.append(piece)
        current_tokens += piece_tokens
    if current:
        result.append(_build_chunk(section, start_index + len(result), "\n\n".join(current)))
    return result


def _semantic_pieces(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        if count_tokens(paragraph) <= 256:
            pieces.append(paragraph)
        else:
            pieces.extend(part.strip() for part in SENTENCE_RE.split(paragraph) if part.strip())
    return pieces


def _hard_split(text: str, limit: int) -> list[str]:
    if limit <= 0:
        return [text]
    chars_per_chunk = max(1, limit)
    return [text[index : index + chars_per_chunk] for index in range(0, len(text), chars_per_chunk)]


def _tail_overlap(pieces: list[str], overlap_tokens: int) -> list[str]:
    if overlap_tokens <= 0:
        return []
    selected: list[str] = []
    total = 0
    for piece in reversed(pieces):
        selected.insert(0, piece)
        total += count_tokens(piece)
        if total >= overlap_tokens:
            break
    return selected


def _build_chunk(section: ParsedSection, chunk_index: int, content: str) -> ChunkCandidate:
    normalized = content.strip()
    return ChunkCandidate(
        chunk_index=chunk_index,
        content=normalized,
        section_path=section.section_path,
        section_id=section.section_id,
        page_start=section.page_start,
        page_end=section.page_end,
        content_type=_content_type(normalized),
        tokens=count_tokens(normalized),
        sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def _content_type(text: str) -> str:
    if text.lstrip().startswith("|"):
        return "table"
    if text.lstrip().startswith("![]("):
        return "image"
    if "$$" in text:
        return "formula"
    if re.search(r"^\s*[-*]\s+", text, flags=re.MULTILINE):
        return "list"
    return "paragraph"
