"""
Backend dispatcher for PDF → PageRecords extraction.

Provides a single entry point so the pipeline can switch backends
via a string flag without touching internals.

Supported backends:
  - "pymupdf"  : PyMuPDF backend with text/blocks modes (default)
  - "legacy"   : original words_to_text() logic from pdf_to_jsonl.py

Usage:
  from pdf_backends import extract_pagerecords

  for record in extract_pagerecords(pdf_path, book_id, backend="pymupdf",
                                    pymupdf_mode="blocks"):
      ...
"""

from pathlib import Path
from typing import Iterator, Dict, Any

import fitz

from id_factory import IDFactory
from pdf_to_jsonl import words_to_text, to_jsonable, group_sections_per_page, PageRecord


def _current_backend(pdf_path: Path, book_id: str, **kwargs) -> Iterator[Dict[str, Any]]:
    """
    Existing extraction logic: get_text("words") with gap-based reconstruction.

    This mirrors the loop in convert_pdf() but yields dicts instead of writing
    directly, so it can be used through the unified interface.
    """
    with fitz.open(pdf_path) as doc:
        for page_idx in range(len(doc)):
            page_record: PageRecord = words_to_text(doc[page_idx], book_id=book_id)

            # Add section heuristics (same as convert_pdf does)
            sections = group_sections_per_page(page_record)
            page_record.section_ids = {s for s in sections if s is not None}

            yield to_jsonable(page_record)


def _pymupdf_backend(pdf_path: Path, book_id: str, **kwargs) -> Iterator[Dict[str, Any]]:
    """
    New PyMuPDF backend with text/blocks modes.
    """
    from extractors.pymupdf_backend import extract_pages

    mode = kwargs.get("pymupdf_mode", "text")

    for record in extract_pages(pdf_path, book_id, mode=mode):
        # Run the same section-heuristic pass on the extracted text
        # so section_ids are populated consistently
        temp = PageRecord(
            id=record["id"],
            book_id=record["book_id"],
            pdf_page_number=record["pdf_page_number"],
            text=record["text"],
            word_count=record["word_count"],
            has_chapter=record["has_chapter"],
            has_section=record["has_section"],
            has_question=record["has_question"],
            has_answer=record["has_answer"],
        )
        sections = group_sections_per_page(temp)
        record["section_ids"] = sorted(s for s in sections if s is not None)

        yield record


_BACKENDS = {
    "pymupdf": _pymupdf_backend,
    "legacy": _current_backend,
}


def extract_pagerecords(
    pdf_path: Path,
    book_id: str,
    *,
    backend: str = "pymupdf",
    **kwargs,
) -> Iterator[Dict[str, Any]]:
    """
    Unified entry point for page extraction.

    Args:
        pdf_path:  Path to the PDF.
        book_id:   Deterministic book UUID.
        backend:   "pymupdf" (default) or "legacy".
        **kwargs:  Passed to the chosen backend (e.g. pymupdf_mode="blocks").

    Yields:
        dict — one PageRecord per page, JSON-serialisable.
    """
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown backend: {backend!r}. "
            f"Choose from: {', '.join(sorted(_BACKENDS))}"
        )
    yield from _BACKENDS[backend](pdf_path, book_id, **kwargs)
