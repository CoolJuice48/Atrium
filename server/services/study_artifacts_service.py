"""Study Artifacts v0.1: per-book card generation and review."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.library import load_library
from study import artifacts as study_artifacts
from study.card_generator import generate_practice_exam


def get_books(index_root: Path) -> List[Dict[str, Any]]:
    """
    Return list of ready books from library.json with study stats.
    Each book: book_id, title, chunk_count, study: {card_count, due_count, last_generated_at}
    """
    index_root = Path(index_root).resolve()
    lib = load_library(index_root)
    if not lib:
        return []
    books_dir = index_root / "books"
    result = []
    for b in lib.get("books", []):
        if b.get("status") != "ready":
            continue
        book_id = b.get("book_id")
        if not book_id:
            continue
        book_dir = books_dir / book_id
        if not book_dir.exists():
            continue
        study_stats = study_artifacts.get_study_stats(book_dir)
        result.append({
            "book_id": book_id,
            "title": b.get("title") or b.get("filename", book_id).replace(".pdf", ""),
            "chunk_count": b.get("chunk_count", 0),
            "study": {
                "card_count": study_stats.get("card_count", 0),
                "due_count": study_stats.get("due_count", 0),
                "last_generated_at": study_stats.get("last_generated_at"),
                "avg_grade": study_stats.get("avg_grade"),
            },
        })
    return result


def generate_cards(
    index_root: Path,
    book_id: str,
    max_cards: int = 20,
    strategy: str = "coverage",
) -> Dict[str, Any]:
    """Generate cards for a book. Returns {generated_count, skipped_count, elapsed_ms}."""
    index_root = Path(index_root).resolve()
    book_dir = index_root / "books" / book_id
    if not book_dir.exists():
        raise ValueError(f"Book {book_id} not found")
    if not (book_dir / "chunks.jsonl").exists():
        raise ValueError(f"Book {book_id} has no chunks")
    study_artifacts.verify_study(index_root, book_id)
    return study_artifacts.generate_cards_for_book(index_root, book_id, max_cards, strategy)


def get_due_cards(index_root: Path, book_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Return due cards for a book."""
    index_root = Path(index_root).resolve()
    book_dir = index_root / "books" / book_id
    if not book_dir.exists():
        raise ValueError(f"Book {book_id} not found")
    study_artifacts.verify_study(index_root, book_id)
    return study_artifacts.get_due_cards(book_dir, limit=limit)


def review_card(index_root: Path, book_id: str, card_id: str, grade: int) -> Dict[str, Any]:
    """Submit review for a card. Returns updated scheduling fields."""
    index_root = Path(index_root).resolve()
    book_dir = index_root / "books" / book_id
    if not book_dir.exists():
        raise ValueError(f"Book {book_id} not found")
    study_artifacts.verify_study(index_root, book_id)
    return study_artifacts.review_card(book_dir, card_id, grade)


class NoTextExtractedError(ValueError):
    """Raised when book has no chunks with extractable text."""


def generate_exam(
    index_root: Path,
    book_id: str,
    exam_size: int = 20,
    blueprint: Optional[Dict[str, int]] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Generate a practice exam for a book from its chunks.
    Works for global pack books and user uploads; uses same chunk structure as Q&A.
    Returns {ok, book_id, title, exam: {questions}, meta}. Questions are ephemeral.
    """
    index_root = Path(index_root).resolve()
    book_dir = index_root / "books" / book_id
    if not book_dir.exists():
        raise ValueError(f"Book {book_id} not found")
    chunks_path = book_dir / "chunks.jsonl"
    if not chunks_path.exists():
        raise ValueError(f"Book {book_id} has no chunks")

    lib = load_library(index_root)
    book_title = book_id
    if lib:
        for b in lib.get("books", []):
            if b.get("book_id") == book_id:
                book_title = b.get("title") or b.get("filename", book_id)
                if isinstance(book_title, str) and book_title.endswith(".pdf"):
                    book_title = book_title[:-4]
                break

    chunks: List[Dict[str, Any]] = []
    for i, line in enumerate(chunks_path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        text = rec.get("text", "").strip()
        meta = {
            "chunk_id": rec.get("chunk_id", f"{book_id}|i{i}"),
            "book_id": book_id,
            "book": book_title,
            "book_name": rec.get("book_name", book_title),
            "chapter_number": rec.get("chapter_number", ""),
            "section_number": rec.get("section_number", ""),
            "section_title": rec.get("section_title", ""),
            "page_start": rec.get("page_start"),
            "page_end": rec.get("page_end"),
            "chunk_index": rec.get("chunk_index", i),
        }
        chunks.append({"text": text, "metadata": meta})

    valid_chunks = [c for c in chunks if c.get("text")]
    if not valid_chunks:
        raise NoTextExtractedError("No text extracted; scanned PDF?")

    exam = generate_practice_exam(
        valid_chunks,
        exam_size=exam_size,
        blueprint=blueprint,
        seed=seed,
    )

    questions_serialized = []
    for c in exam["questions"]:
        q = {
            "card_id": c.card_id,
            "prompt": c.prompt,
            "answer": c.answer,
            "card_type": c.card_type,
            "book_name": c.book_name,
            "tags": list(c.tags),
            "citations": [{"chunk_id": cit.chunk_id, "chapter": cit.chapter, "section": cit.section, "pages": cit.pages} for cit in c.citations],
        }
        questions_serialized.append(q)

    return {
        "ok": True,
        "book_id": book_id,
        "title": exam["title"],
        "exam": {"questions": questions_serialized},
        "meta": exam["meta"],
    }
