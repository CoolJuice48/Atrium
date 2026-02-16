#!/usr/bin/env python3
"""
Non-interactive index bootstrap: incremental ingest from pdf_dir into the library.

Uses Atrium Library v0.2: per-book content-addressed storage under INDEX_ROOT.
Skips already-ingested PDFs (hash-based). Rebuilds global TF-IDF search index.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def index_exists(index_root: Path) -> bool:
    """Check if library is present (library.json exists with at least one ready book)."""
    lib_path = index_root / "library.json"
    if not lib_path.exists():
        return False
    import json
    try:
        with open(lib_path, "r") as f:
            lib = json.load(f)
        ready = [b for b in lib.get("books", []) if b.get("status") == "ready"]
        return len(ready) > 0
    except (json.JSONDecodeError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Incremental ingest: build library from PDFs (non-interactive)"
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
        help="Output directory for the library",
    )
    args = parser.parse_args()
    pdf_dir = args.pdf_dir.resolve()
    index_root = args.index_root.resolve()

    if index_exists(index_root):
        pdfs = list(pdf_dir.glob("*.pdf"))
        if not pdfs:
            print(f"Index present: {index_root}")
            return 0
        # Run incremental anyway - will skip already-ingested
        print(f"Incremental ingest (index present, checking {len(pdfs)} PDFs)...")
    else:
        pdfs = sorted(pdf_dir.glob("*.pdf"))
        if not pdfs:
            print(f"No PDFs found in {pdf_dir}. Add PDFs then run `make index` or `make run-bootstrap`.")
            return 1

    from scripts.ingest_library import ingest_pdfs_incremental, rebuild_search_index

    report = ingest_pdfs_incremental(pdf_dir, index_root, copy_source=True)
    if report.get("rebuilt_search_index"):
        rebuild_search_index(index_root)

    ingested = report.get("ingested", [])
    skipped = report.get("skipped", [])
    failed = report.get("failed", [])
    print(f"  ✓ Ingested: {len(ingested)}, skipped: {len(skipped)}, failed: {len(failed)}")
    print(f"  ✓ Elapsed: {report.get('elapsed_ms', 0)}ms, avg ingest: {report.get('avg_ingest_ms', 0)}ms")
    print(f"Index built: {index_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
