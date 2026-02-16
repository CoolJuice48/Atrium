"""
Atrium Library v0.2: per-book content-addressed storage with metadata.

Schema under INDEX_ROOT:
  library.json     - metadata, source of truth
  books/<book_id>/ - source.pdf, chunks.jsonl, book.json
  search/tfidf/    - global artifacts (stubbed)
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LIBRARY_VERSION = "0.2"

# Verify cache: (index_root, library.json mtime) -> (ok, issues, valid_book_ids, timestamp)
_verify_cache: Dict[Tuple[str, float], Tuple[bool, List[str], List[str], float]] = {}
_VERIFY_CACHE_TTL_SEC = 3.0


def invalidate_verify_cache(index_root: Optional[Path] = None) -> None:
    """Clear verify cache for index_root or all."""
    global _verify_cache
    if index_root is None:
        _verify_cache.clear()
        return
    key_prefix = str(Path(index_root).resolve())
    _verify_cache = {k: v for k, v in _verify_cache.items() if k[0] != key_prefix}


def _family_key(filename: str) -> str:
    """Normalize filename for family grouping: lowercase, strip extension, collapse whitespace."""
    stem = Path(filename).stem.lower()
    return re.sub(r"\s+", " ", stem).strip()


def _sha256_file(path: Path) -> str:
    """Compute sha256 hash of file bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_library(index_root: Path) -> Optional[Dict[str, Any]]:
    """Load library.json if it exists. Returns None if missing."""
    path = Path(index_root).resolve() / "library.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_library(index_root: Path, data: Dict[str, Any]) -> None:
    """Write library.json atomically."""
    path = Path(index_root).resolve() / "library.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def verify_library(index_root: Path, lib: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """
    Quick consistency check for library.
    Returns (ok, issues, valid_book_ids).
    valid_book_ids: list of book_ids that pass all checks.
    """
    index_root = Path(index_root).resolve()
    books_dir = index_root / "books"
    issues: List[str] = []
    valid_book_ids: List[str] = []

    for rec in lib.get("books", []):
        if rec.get("status") != "ready":
            continue
        book_id = rec.get("book_id")
        if not book_id:
            issues.append("Book record missing book_id")
            continue
        book_dir = books_dir / book_id
        if not book_dir.exists():
            issues.append(f"Book {book_id}: folder missing")
            continue
        chunks_file = book_dir / "chunks.jsonl"
        if not chunks_file.exists():
            issues.append(f"Book {book_id}: chunks.jsonl missing")
            continue
        if chunks_file.stat().st_size == 0:
            issues.append(f"Book {book_id}: chunks.jsonl empty")
            continue
        book_json = book_dir / "book.json"
        if not book_json.exists():
            issues.append(f"Book {book_id}: book.json missing")
            continue
        valid_book_ids.append(book_id)

    return (len(issues) == 0, issues, valid_book_ids)


def verify_library_cached(index_root: Path, lib: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """
    Cached verify_library. Cache key: (index_root, library.json mtime).
    TTL: 3 seconds to avoid hammering FS on frequent queries.
    """
    path = Path(index_root).resolve() / "library.json"
    if not path.exists():
        return verify_library(index_root, lib)

    mtime = path.stat().st_mtime
    key = (str(index_root.resolve()), mtime)
    now = _time.perf_counter()
    if key in _verify_cache:
        ok, issues, valid, ts = _verify_cache[key]
        if now - ts < _VERIFY_CACHE_TTL_SEC:
            return (ok, issues, valid)
    result = verify_library(index_root, lib)
    _verify_cache[key] = (*result, now)
    return result


def get_status_from_library(
    index_root: Path,
    pdf_dir: Path,
) -> Dict[str, Any]:
    """
    Cheap status from library.json only.
    index_exists: library.json exists
    index_ready: library.json exists AND total chunk_count > 0 AND at least one book status ready
    """
    index_root = Path(index_root).resolve()
    pdf_dir = Path(pdf_dir).resolve()
    lib = load_library(index_root)

    index_exists = lib is not None
    index_ready = False
    chunk_count = 0
    book_counts: List[Dict[str, Any]] = []
    consistency = {"ok": True, "issues": []}

    if lib:
        consistency_ok, consistency_issues, _ = verify_library_cached(index_root, lib)
        consistency = {"ok": consistency_ok, "issues": consistency_issues}

        ready_books = [b for b in lib.get("books", []) if b.get("status") == "ready"]
        if ready_books:
            chunk_count = sum(b.get("chunk_count", 0) for b in ready_books)
            index_ready = chunk_count > 0

        for b in lib.get("books", []):
            book_counts.append({
                "book": b.get("filename", b.get("book_id", "unknown")),
                "chunks": b.get("chunk_count", 0),
                "book_id": b.get("book_id"),
                "status": b.get("status", "unknown"),
                **({"superseded_by": b["superseded_by"]} if b.get("superseded_by") else {}),
            })

    return {
        "ok": True,
        "index_root": str(index_root),
        "pdf_dir": str(pdf_dir),
        "index_exists": index_exists,
        "index_ready": index_ready,
        "chunk_count": chunk_count,
        "book_counts": book_counts,
        "consistency": consistency,
    }


def get_book_metadata_map(lib: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return map of book_id -> {title, superseded, supersedes, superseded_by}."""
    out: Dict[str, Dict[str, Any]] = {}
    for b in lib.get("books", []):
        bid = b.get("book_id")
        if not bid:
            continue
        fn = b.get("filename", "")
        title = (b.get("title") or fn).replace(".pdf", "") if fn else bid
        out[bid] = {
            "title": title,
            "superseded": bool(b.get("superseded_by")),
            "supersedes": b.get("supersedes", []),
            "superseded_by": b.get("superseded_by", []),
        }
    return out


def select_candidate_books(
    question: str,
    index_root: Path,
    lib: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    Placeholder: select which books to search for a question.
    Simple heuristic: keyword match on filename/title in library.json; else return all.
    Returns list of book_ids.
    """
    if lib is None:
        lib = load_library(index_root)
    if lib is None:
        return []

    ready = [b for b in lib.get("books", []) if b.get("status") == "ready"]
    if not ready:
        return []

    q_lower = question.lower()
    words = set(re.findall(r"[a-z0-9]+", q_lower))
    if not words:
        return [b["book_id"] for b in ready]

    candidates = []
    for b in ready:
        filename = (b.get("filename") or "").lower()
        title = (b.get("title") or filename).lower()
        combined = f"{filename} {title}"
        if any(w in combined for w in words):
            candidates.append(b["book_id"])

    return candidates if candidates else [b["book_id"] for b in ready]
