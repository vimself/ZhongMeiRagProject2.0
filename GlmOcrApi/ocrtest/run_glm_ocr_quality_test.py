from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import fitz


TEST_DIR = Path(__file__).resolve().parent
API_ROOT = TEST_DIR.parent
DEFAULT_PDF = TEST_DIR / "泵站设计标准.pdf"
DEFAULT_OUTPUT = TEST_DIR / "output"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GLM-OCR quality regression cases.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="PDF path.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="Output root.")
    parser.add_argument("--case-name", default="", help="Output subdirectory name.")
    parser.add_argument("--page", type=int, default=16, help="1-based single page to test. Use 0 to disable.")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit PDF pages when --page=0.")
    parser.add_argument("--no-repair", action="store_true", help="Disable text line repair.")
    parser.add_argument("--layout-vis", action="store_true", help="Save layout visualization.")
    return parser.parse_args()


def extract_single_page(pdf_path: Path, page_no: int, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"source_page_{page_no}.pdf"
    with fitz.open(pdf_path) as src:
        if page_no < 1 or page_no > src.page_count:
            raise ValueError(f"page must be between 1 and {src.page_count}, got {page_no}")
        dst = fitz.open()
        dst.insert_pdf(src, from_page=page_no - 1, to_page=page_no - 1)
        dst.save(target)
        dst.close()
    return target


def main() -> None:
    args = parse_args()
    output_root = args.output_dir.resolve()
    case_name = args.case_name or (f"quality_page_{args.page}" if args.page else "quality_limited")
    case_dir = output_root / case_name
    case_dir.mkdir(parents=True, exist_ok=True)

    if args.max_pages > 0:
        os.environ["GLM_PDF_MAX_PAGES"] = str(args.max_pages)
    if args.no_repair:
        os.environ["GLM_TEXT_LINE_REPAIR_ENABLED"] = "0"
    os.environ["GLM_SAVE_LAYOUT_VIS"] = "1" if args.layout_vis else "0"

    source_pdf = args.pdf.resolve()
    if args.page:
        source_pdf = extract_single_page(source_pdf, args.page, case_dir)

    sys.path.insert(0, str(API_ROOT))
    from glm_processor import GlmOCRProcessor

    processor = GlmOCRProcessor()
    try:
        result = processor.process_pdf(str(source_pdf), str(case_dir))
    finally:
        processor.close()

    report = result.get("quality_report") or {}
    print(f"output_dir={case_dir}")
    print(f"page_count={result.get('page_count')} markdown_chars={len(result.get('markdown') or '')}")
    print(f"quality_repair_count={report.get('repair_count', 0)}")
    print((result.get("markdown") or "")[:1200])


if __name__ == "__main__":
    main()
