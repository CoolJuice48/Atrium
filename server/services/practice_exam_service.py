"""Scoped practice exam generation: outline + page-range filtering + candidate pool."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.outline import (
    filter_chunks_by_page_ranges,
    get_or_build_outline,
    resolve_scope_to_page_ranges,
)
from server.outline import _load_chunks as load_chunks
from server.services.exam_candidates import build_candidate_pool
from server.services.exam_generation import generate_exam_questions


DEFAULT_MAX_PAGES = 40
DEFAULT_MAX_CHUNKS = 150
DEFAULT_TOTAL_QUESTIONS = 20


def _build_scope_label(items: List[Dict], item_ids: List[str]) -> str:
    """Build human-readable scope label from selected items."""
    id_to_item = {it["id"]: it for it in items}
    selected = [id_to_item[iid] for iid in item_ids if iid in id_to_item]
    if not selected:
        return "Selected scope"
    chapters = [s for s in selected if s.get("level") == 1]
    sections = [s for s in selected if s.get("level") == 2]
    parts = []
    if chapters:
        titles = [c.get("title", "") for c in chapters]
        parts.append(", ".join(titles[:3]))
        if len(chapters) > 3:
            parts[-1] += f" (+{len(chapters) - 3} more)"
    if sections:
        titles = [s.get("title", "") for s in sections]
        parts.append("Sections: " + ", ".join(titles[:3]))
        if len(sections) > 3:
            parts[-1] += f" (+{len(sections) - 3} more)"
    return " | ".join(parts) if parts else "Selected scope"


def generate_scoped_exam(
    index_root: Path,
    book_id: str,
    outline_id: str,
    item_ids: List[str],
    *,
    total_questions: int = DEFAULT_TOTAL_QUESTIONS,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    distribution: Optional[Dict[str, int]] = None,
    use_local_llm: bool = False,
    settings: Any = None,
) -> Dict[str, Any]:
    """
    Generate a scoped practice exam. Requires scope selection.
    Returns { exam_id, scope_label, resolved_ranges, questions, citations }.
    Raises ValueError for validation errors.
    """
    index_root = Path(index_root).resolve()
    book_dir = index_root / "books" / book_id
    if not book_dir.exists():
        raise ValueError("Book not found")

    if not item_ids:
        raise ValueError("Select at least one chapter or section.")

    current_id, items = get_or_build_outline(book_dir)
    if not items:
        raise ValueError("No outline available for this book")

    if current_id != outline_id:
        raise ValueError("Outline has changed. Please refresh and select your scope again.")

    ranges = resolve_scope_to_page_ranges(items, item_ids)
    if not ranges:
        raise ValueError("Selected items could not be resolved to page ranges.")

    total_pages = sum(hi - lo + 1 for lo, hi in ranges)
    if total_pages > max_pages:
        raise ValueError(
            f"Selected scope is too large ({total_pages} pages). "
            f"Please select fewer sections (max {max_pages} pages)."
        )

    chunks = load_chunks(book_dir)
    chunks = [c for c in chunks if c.get("text", "").strip()]
    if not chunks:
        raise ValueError("No chunks available for this book")

    filtered = filter_chunks_by_page_ranges(chunks, ranges)
    if not filtered:
        raise ValueError("No content found in the selected page range")

    if len(filtered) > max_chunks:
        raise ValueError(
            f"Selected scope has too many chunks ({len(filtered)}). "
            f"Please select fewer sections (max {max_chunks} chunks)."
        )

    pool = build_candidate_pool(filtered, max_sentences=4000)
    if len(pool) < 5:
        raise ValueError(
            "Too few quality sentences in the selected scope. "
            "Try selecting more sections or a different chapter."
        )

    _debug = (
        os.environ.get("DEBUG_EXAMS", "").lower() in ("1", "true", "yes")
        or os.environ.get("DEBUG_ARTIFACTS", "").lower() in ("1", "true", "yes")
    )
    artifact_stats = None
    if _debug:
        from server.services.exam_stats import ExamArtifactStats
        artifact_stats = ExamArtifactStats()

    questions = generate_exam_questions(
        pool,
        distribution=distribution,
        total=total_questions,
        artifact_stats=artifact_stats,
    )
    if use_local_llm and settings:
        from server.services.local_llm.exam_polish import polish_exam_questions_sync
        from server.services.local_llm.provider import get_provider
        provider = get_provider(settings)
        if provider:
            try:
                questions = polish_exam_questions_sync(
                    questions,
                    provider,
                    settings,
                    def_stats=artifact_stats.definition if artifact_stats else None,
                    fib_stats=artifact_stats.fill_blank if artifact_stats else None,
                )
            except Exception:
                pass

    if artifact_stats:
        logging.getLogger(__name__).info("Exam stats: %s", artifact_stats.to_log_dict())
    if not questions:
        raise ValueError(
            "Could not generate enough questions from the selected scope. "
            "Try selecting more sections."
        )

    scope_label = _build_scope_label(items, item_ids)
    exam_key = f"{book_id}|{outline_id}|{','.join(sorted(item_ids))}|{len(questions)}"
    exam_id = hashlib.sha256(exam_key.encode()).hexdigest()[:16]

    questions_serialized = []
    all_citations = []
    for q in questions:
        q_dict = {
            "q_type": q.q_type,
            "prompt": q.prompt,
            "answer": q.answer,
            "citations": q.citations,
        }
        questions_serialized.append(q_dict)
        all_citations.extend(q.citations)

    return {
        "exam_id": exam_id,
        "scope_label": scope_label,
        "resolved_ranges": [{"start": lo, "end": hi} for lo, hi in ranges],
        "questions": questions_serialized,
        "citations": list({c["chunk_id"]: c for c in all_citations}.values()),
    }
