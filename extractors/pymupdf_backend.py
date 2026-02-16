"""
PyMuPDF Backend for PDF → PageRecords extraction.

Provides two extraction modes:
  - "text":   page.get_text("text")  — simple, fast, good for single-column
  - "blocks": page.get_text("blocks") — preserves reading order for multi-column

Emits PageRecords identical to the existing pipeline schema.

Optional metadata extraction:
  - PDF TOC (table of contents from document outline)
  - Page labels (logical page numbers from PDF metadata)

Usage:
  from pymupdf_backend import extract_pages, extract_toc, extract_page_labels

  for record in extract_pages(pdf_path, book_id, mode="text"):
      ...  # yields PageRecord dicts
"""

import json
import fitz
from pathlib import Path
from typing import Iterator, Dict, Any, List, Optional

from id_factory import IDFactory
from legacy.regex_parts import has_answer, has_question, has_chapter, has_section


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_text_mode(page: fitz.Page) -> str:
    """Simple text extraction via page.get_text('text')."""
    return page.get_text("text") or ""


def _extract_blocks_mode(page: fitz.Page) -> str:
    """
    Block-based extraction via page.get_text('blocks').

    Each block is (x0, y0, x1, y1, text_or_image, block_no, block_type).
    block_type 0 = text, 1 = image.

    Blocks are sorted top-to-bottom, then left-to-right to approximate
    reading order (handles simple multi-column layouts).
    """
    blocks = page.get_text("blocks") or []

    # Keep only text blocks (type 0)
    text_blocks = [b for b in blocks if b[6] == 0]

    # Sort: top-to-bottom (y0), then left-to-right (x0)
    text_blocks.sort(key=lambda b: (b[1], b[0]))

    parts = []
    for b in text_blocks:
        text = b[4].strip()
        if text:
            parts.append(text)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_pages(
    pdf_path: Path,
    book_id: str,
    *,
    mode: str = "text",
) -> Iterator[Dict[str, Any]]:
    """
    Yield one PageRecord dict per page from the PDF.

    Args:
        pdf_path:  Path to the PDF file.
        book_id:   Book UUID (from IDFactory or pipeline).
        mode:      "text" or "blocks".

    Yields:
        dict matching the PageRecord schema (JSON-serialisable).
    """
    if mode not in ("text", "blocks"):
        raise ValueError(f"Unknown pymupdf mode: {mode!r}. Use 'text' or 'blocks'.")

    extractor = _extract_text_mode if mode == "text" else _extract_blocks_mode

    with fitz.open(pdf_path) as doc:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            pdf_page_number = page_idx + 1  # 1-based

            text = extractor(page)
            word_count = len(text.split()) if text else 0

            yield {
                "id": IDFactory.page_id(book_id, pdf_page_number),
                "section_ids": [],
                "book_id": book_id,
                "pdf_page_number": pdf_page_number,
                "real_page_number": None,
                "text": text,
                "word_count": word_count,
                "has_chapter": has_chapter(text) if text else False,
                "has_section": has_section(text) if text else False,
                "has_question": has_question(text) if text else False,
                "has_answer": has_answer(text) if text else False,
                "text_embedding": None,
            }


# ---------------------------------------------------------------------------
# Optional metadata: TOC
# ---------------------------------------------------------------------------

def extract_toc(pdf_path: Path) -> List[Dict[str, Any]]:
    """
    Extract PDF outline / table-of-contents if present.

    Returns list of dicts:
      [{"level": 1, "title": "Chapter 1", "page": 5}, ...]

    Page numbers are 1-based to match pdf_page_number convention.
    """
    with fitz.open(pdf_path) as doc:
        raw_toc = doc.get_toc(simple=True)  # [(level, title, page), ...]
        return [
            {"level": lvl, "title": title, "page": page}
            for lvl, title, page in raw_toc
        ]


def save_toc(toc: List[Dict], output_path: Path) -> None:
    """Write TOC metadata as JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(toc, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Optional metadata: page labels
# ---------------------------------------------------------------------------

def extract_page_labels(pdf_path: Path) -> List[Dict[str, Any]]:
    """
    Extract page labels (logical page numbers) from PDF metadata.

    Returns list of dicts keyed by pdf_page_number (1-based):
      [{"pdf_page_number": 1, "label": "i"}, {"pdf_page_number": 2, "label": "ii"}, ...]
    """
    with fitz.open(pdf_path) as doc:
        labels = []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            label = page.get_label()  # returns str or ""
            labels.append({
                "pdf_page_number": page_idx + 1,
                "label": label if label else None,
            })
        return labels


def save_page_labels(labels: List[Dict], output_path: Path) -> None:
    """Write page labels metadata as JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)
