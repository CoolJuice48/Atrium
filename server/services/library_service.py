"""Multi-tenant library: global (file-based) + user-owned (DB)."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from server.db.models import LibraryBook
from server.library import load_library
from study import artifacts as study_artifacts


def get_global_books_from_index(index_root: Path) -> List[Dict[str, Any]]:
    """Return ready books from library.json (file-based index)."""
    index_root = Path(index_root).resolve()
    lib = load_library(index_root)
    if not lib:
        return []
    books_dir = index_root / "books"
    result = []
    for b in lib.get("books", []):
        if b.get("status") != "ready" or b.get("owner_id"):
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


def get_user_books_from_library(index_root: Path, user_id: str) -> List[Dict[str, Any]]:
    """Return user-owned books from library.json (owner_id=user_id)."""
    index_root = Path(index_root).resolve()
    lib = load_library(index_root)
    if not lib:
        return []
    books_dir = index_root / "books"
    result = []
    for b in lib.get("books", []):
        if b.get("status") != "ready":
            continue
        if b.get("owner_id") != user_id:
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


def get_user_books_from_db(db: DBSession, user_id: str) -> List[Dict[str, Any]]:
    """Return user-owned books from library_books with study stats from study_cards/progress."""
    rows = db.query(LibraryBook).filter(
        LibraryBook.owner_type == "user",
        LibraryBook.owner_id == user_id,
        LibraryBook.status == "ready",
    ).all()
    result = []
    for row in rows:
        # Study stats from study_cards: count cards for this book_row_id and user
        from server.db.models import StudyCard, StudyProgress
        card_count = db.query(StudyCard).filter(
            StudyCard.user_id == user_id,
            StudyCard.book_row_id == row.id,
        ).count()
        # Due count: cards with due_at <= now in study_progress for this book
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        card_ids_for_book = [
            c.card_id for c in db.query(StudyCard.card_id).filter(
                StudyCard.user_id == user_id,
                StudyCard.book_row_id == row.id,
            ).all()
        ]
        if card_ids_for_book:
            due_count = db.query(StudyProgress).filter(
                StudyProgress.user_id == user_id,
                StudyProgress.due_at <= now,
                StudyProgress.card_id.in_(card_ids_for_book),
            ).count()
        else:
            due_count = 0
        result.append({
            "book_id": row.book_id,
            "title": row.display_title or row.title,
            "chunk_count": row.chunk_count,
            "study": {
                "card_count": card_count,
                "due_count": due_count,
                "last_generated_at": None,
                "avg_grade": None,
            },
        })
    return result


def get_books_union(
    index_root: Path,
    db: DBSession,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Return union of global (index) + user-owned (library + DB) books."""
    global_books = get_global_books_from_index(index_root)
    user_lib_books = get_user_books_from_library(index_root, user_id)
    user_db_books = get_user_books_from_db(db, user_id)
    seen = {b["book_id"] for b in global_books}
    result = list(global_books)
    for b in user_lib_books + user_db_books:
        if b["book_id"] not in seen:
            seen.add(b["book_id"])
            result.append(b)
    return result


def update_user_book_metadata(
    index_root: Path,
    user_id: str,
    book_id: str,
    display_title: Optional[str] = None,
    subject_tags: Optional[List[str]] = None,
    course_tags: Optional[List[str]] = None,
) -> bool:
    """Update metadata for user-owned book in library.json. Returns True if updated."""
    index_root = Path(index_root).resolve()
    lib = load_library(index_root)
    if not lib:
        return False
    for b in lib.get("books", []):
        if b.get("book_id") != book_id or b.get("owner_id") != user_id:
            continue
        if display_title is not None:
            b["title"] = display_title
            b["display_title"] = display_title
        if subject_tags is not None:
            b["subject_tags"] = subject_tags
        if course_tags is not None:
            b["course_tags"] = course_tags
        import time as _time
        b["updated_at"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
        from server.library import save_library
        save_library(index_root, lib)
        return True
    return False
