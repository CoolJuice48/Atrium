"""Scoped summary generation: outline + page-range filtering."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from server.outline import (
    filter_chunks_by_page_ranges,
    get_or_build_outline,
    load_outline,
    resolve_scope_to_page_ranges,
)
from server.outline import _load_chunks as load_chunks


# Configurable caps
DEFAULT_MAX_PAGES = 80
DEFAULT_MAX_CHUNKS = 200
DEFAULT_BULLETS_TARGET = 10


def generate_scoped_summary(
    index_root: Path,
    book_id: str,
    outline_id: str,
    item_ids: List[str],
    *,
    bullets_target: int = DEFAULT_BULLETS_TARGET,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> Dict[str, Any]:
    """
    Generate summary for selected scope. Returns summary_markdown, bullets, citations, key_terms.
    Raises ValueError for validation errors (outline mismatch, no scope, etc.).
    """
    index_root = Path(index_root).resolve()
    book_dir = index_root / "books" / book_id
    if not book_dir.exists():
        raise ValueError("Book not found")

    # Load or build outline
    current_id, items = get_or_build_outline(book_dir)
    if not items:
        raise ValueError("No outline available for this book")

    if current_id != outline_id:
        raise ValueError(
            "Outline has changed. Please refresh and select your scope again."
        )

    if not item_ids:
        raise ValueError("No sections selected. Please select at least one chapter or section.")

    ranges = resolve_scope_to_page_ranges(items, item_ids)
    if not ranges:
        raise ValueError("Selected items could not be resolved to page ranges.")

    # Cap total pages
    total_pages = sum(hi - lo + 1 for lo, hi in ranges)
    if total_pages > max_pages:
        raise ValueError(
            f"Selected scope is too large ({total_pages} pages). "
            f"Please select fewer sections (max {max_pages} pages)."
        )

    chunks = load_chunks(book_dir)
    if not chunks:
        raise ValueError("No chunks available for this book")

    filtered = filter_chunks_by_page_ranges(chunks, ranges)
    if not filtered:
        raise ValueError("No content found in the selected page range")

    # Cap chunks
    if len(filtered) > DEFAULT_MAX_CHUNKS:
        filtered = filtered[:DEFAULT_MAX_CHUNKS]

    # Convert to format expected by compose_summary_from_chunks
    chunk_dicts = []
    for c in filtered:
        meta = {
            "book": c.get("book_name", ""),
            "book_id": book_id,
            "chapter": str(c.get("chapter_number", "")),
            "section": str(c.get("section_number", "")),
            "section_title": c.get("section_title", ""),
            "pages": f"{c.get('page_start', '')}-{c.get('page_end', '')}",
            "page_start": c.get("page_start"),
            "page_end": c.get("page_end"),
        }
        chunk_dicts.append({"text": c.get("text", ""), "metadata": meta})

    from server.services.concepts import get_section_title_terms_for_scope
    from server.services.summary_compose import compose_summary_from_chunks

    section_title_terms = get_section_title_terms_for_scope(items, item_ids, chunk_dicts)

    result = compose_summary_from_chunks(
        chunk_dicts,
        "Summarize the main ideas and key concepts.",
        max_chunks=min(12, len(chunk_dicts)),
        max_bullets=bullets_target,
        section_title_terms=section_title_terms,
    )

    return {
        "summary_markdown": result["answer"],
        "bullets": result["key_points"],
        "citations": result["citations"],
        "key_terms": _extract_key_terms_from_result(result),
    }


def _extract_key_terms_from_result(result: Dict[str, Any]) -> List[str]:
    """Extract key terms from compose result answer (### Key terms section)."""
    answer = result.get("answer", "")
    terms = []
    in_section = False
    for line in answer.split("\n"):
        if "### Key terms" in line:
            in_section = True
            continue
        if in_section and line.strip() and not line.strip().startswith("-"):
            parts = [p.strip() for p in line.split(",") if p.strip()]
            terms.extend(p for p in parts if len(p) >= 4)
            break
    return terms[:8]
