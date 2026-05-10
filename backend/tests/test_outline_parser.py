from __future__ import annotations

from app.services.ingest.outline_parser import parse_outline


def test_parse_numbered_sections() -> None:
    result = parse_outline("1 总则\n内容\n1.1 范围\n范围内容")
    assert [section.title for section in result.sections][:2] == ["未分章节", "1 总则"]


def test_parse_chinese_chapter() -> None:
    result = parse_outline("第一章 总则\n这里是内容")
    assert result.sections[-1].section_path == ["第一章 总则"]


def test_parse_mixed_headings() -> None:
    result = parse_outline("# 总则\n内容\n2.1 条款\n条款内容")
    assert result.outline[0]["title"] == "总则"
    assert result.outline[1]["level"] == 2


def test_parse_markdown_levels() -> None:
    result = parse_outline("## 二级标题\n正文")
    assert result.sections[-1].level == 2


def test_no_heading_fallback() -> None:
    result = parse_outline("只有正文")
    assert result.sections[0].title == "未分章节"
    assert result.sections[0].content == "只有正文"


def test_nested_path() -> None:
    result = parse_outline("# A\n正文\n## B\n正文")
    assert result.sections[-1].section_path == ["A", "B"]


def test_jump_level_warning() -> None:
    result = parse_outline("# A\n### C\n正文")
    assert result.warnings


def test_empty_input() -> None:
    result = parse_outline("")
    assert result.page_count == 0
    assert result.sections[0].content == ""
