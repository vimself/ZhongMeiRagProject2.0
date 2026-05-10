from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

PAGE_SPLIT = "<--- Page Split --->"
HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
CHAPTER_RE = re.compile(r"^(第[一二三四五六七八九十百千万0-9]+[章节篇部])\s*(.*)$")
NUMBER_RE = re.compile(r"^(\d+(?:\.\d+){0,4})[、.\s]+(.+)$")


@dataclass(frozen=True)
class ParsedSection:
    title: str
    level: int
    section_path: list[str]
    section_id: str
    content: str
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True)
class OutlineParseResult:
    sections: list[ParsedSection]
    outline: list[dict[str, object]]
    page_count: int
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "sections": [asdict(section) for section in self.sections],
            "outline": self.outline,
            "page_count": self.page_count,
            "warnings": self.warnings,
        }


def parse_outline(markdown: str) -> OutlineParseResult:
    text = markdown.strip()
    if not text:
        section_id = _section_id(["未分章节"])
        section = ParsedSection(
            title="未分章节",
            level=1,
            section_path=["未分章节"],
            section_id=section_id,
            content="",
            page_start=None,
            page_end=None,
        )
        return OutlineParseResult(sections=[section], outline=[], page_count=0, warnings=["空文档"])

    page_no = 1
    warnings: list[str] = []
    current_title = "未分章节"
    current_level = 1
    current_path = [current_title]
    current_lines: list[str] = []
    current_start_page: int | None = 1
    sections: list[ParsedSection] = []
    path_stack: list[str] = []
    level_stack: list[int] = []
    outline: list[dict[str, object]] = []

    def flush(end_page: int | None) -> None:
        nonlocal current_lines
        content = "\n".join(current_lines).strip()
        if not content and current_title != "未分章节":
            return
        path = list(current_path)
        sections.append(
            ParsedSection(
                title=current_title,
                level=current_level,
                section_path=path,
                section_id=_section_id(path),
                content=content,
                page_start=current_start_page,
                page_end=end_page,
            )
        )
        current_lines = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line == PAGE_SPLIT:
            page_no += 1
            continue
        heading = _detect_heading(line)
        if heading is None:
            current_lines.append(raw_line)
            continue
        level, title = heading
        if level > current_level + 1 and sections:
            warnings.append(f"章节跳级：{title}")
        flush(page_no)
        while level_stack and level_stack[-1] >= level:
            level_stack.pop()
            path_stack.pop()
        level_stack.append(level)
        path_stack.append(title)
        current_title = title
        current_level = level
        current_path = list(path_stack)
        current_start_page = page_no
        outline.append(
            {
                "title": title,
                "level": level,
                "section_path": list(path_stack),
                "page_start": page_no,
            }
        )

    flush(page_no)
    if not sections:
        section_id = _section_id(["未分章节"])
        sections.append(
            ParsedSection(
                title="未分章节",
                level=1,
                section_path=["未分章节"],
                section_id=section_id,
                content=text,
                page_start=1,
                page_end=page_no,
            )
        )
    return OutlineParseResult(
        sections=sections,
        outline=outline,
        page_count=page_no,
        warnings=warnings,
    )


def _detect_heading(line: str) -> tuple[int, str] | None:
    if not line:
        return None
    if match := HEADING_RE.match(line):
        return len(match.group(1)), match.group(2).strip()
    if match := CHAPTER_RE.match(line):
        title = (match.group(1) + " " + match.group(2)).strip()
        level = 1 if match.group(1).endswith(("章", "篇", "部")) else 2
        return level, title
    if match := NUMBER_RE.match(line):
        number = match.group(1)
        title = f"{number} {match.group(2).strip()}"
        return number.count(".") + 1, title
    return None


def _section_id(path: list[str]) -> str:
    return hashlib.sha1(" / ".join(path).encode("utf-8")).hexdigest()
