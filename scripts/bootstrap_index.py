#!/usr/bin/env python3
"""
Non-interactive index bootstrap: convert PDFs in pdf_dir and build the TF-IDF
search index at index_root. Used by `make index` / `make run` so the app works
out of the box when PDFs are present.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run from repo root so imports and paths resolve correctly
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def index_exists(index_root: Path) -> bool:
    """Check if the TF-IDF index is already built (data.json present)."""
    return (index_root / "data.json").exists()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap search index from PDFs (non-interactive)"
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=REPO_ROOT / "pdfs",
        help="Directory containing PDF files",
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        default=REPO_ROOT / "textbook_index",
        help="Output directory for the search index",
    )
    args = parser.parse_args()
    pdf_dir = args.pdf_dir.resolve()
    index_root = args.index_root.resolve()

    if index_exists(index_root):
        print(f"Index present: {index_root}")
        return 0

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {pdf_dir}. Add PDFs then run `make index` or `make run`.")
        return 1

    from pdf_to_jsonl import convert_pdf
    from legacy.textbook_search_offline import TextbookSearchOffline
    from run_pipeline import embed_textbook

    index_root.mkdir(parents=True, exist_ok=True)
    search = TextbookSearchOffline(db_path=str(index_root))

    for pdf_path in pdfs:
        try:
            _doc_id, output_dir = convert_pdf(
                pdf_path,
                output_dir_name=pdf_path.stem,
                auto_chunk=True,
                backend="pymupdf",
                pymupdf_mode="text",
            )
            if embed_textbook(pdf_path.stem, output_dir, search):
                print(f"  ✓ Indexed: {pdf_path.name}")
            else:
                print(f"  ⚠ Skipped (no sections): {pdf_path.name}")
        except Exception as e:
            print(f"  ✗ Failed {pdf_path.name}: {e}")
            return 1

    print(f"Index built: {index_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
