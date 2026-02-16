"""
Study Artifacts v0.1: per-book question/card storage under books/<book_id>/study/.

Schema:
  study/cards.jsonl     - append-only card records
  study/progress.json  - per-card review state
  study/study_meta.json - summary counts, last_generated_at, avg_grade
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


def _atomic_write(path: Path, content: str) -> None:
    """Write to .tmp then rename for atomicity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _atomic_append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    """Append a JSONL line atomically (write full file for simplicity)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if path.exists():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines.append(json.dumps(record, ensure_ascii=False))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def study_dir(book_dir: Path) -> Path:
    """Return study/ path under book folder."""
    return Path(book_dir).resolve() / "study"


def cards_path(book_dir: Path) -> Path:
    return study_dir(book_dir) / "cards.jsonl"


def progress_path(book_dir: Path) -> Path:
    return study_dir(book_dir) / "progress.json"


def study_meta_path(book_dir: Path) -> Path:
    return study_dir(book_dir) / "study_meta.json"


def verify_study(index_root: Path, book_id: str) -> bool:
    """
    Ensure study folder and files exist for a book. Create if missing.
    Returns True if study artifacts are ready.
    """
    index_root = Path(index_root).resolve()
    book_dir = index_root / "books" / book_id
    if not book_dir.exists():
        return False
    sd = study_dir(book_dir)
    sd.mkdir(parents=True, exist_ok=True)
    if not cards_path(book_dir).exists():
        cards_path(book_dir).write_text("", encoding="utf-8")
    if not progress_path(book_dir).exists():
        _atomic_write(progress_path(book_dir), json.dumps({}, indent=2))
    if not study_meta_path(book_dir).exists():
        _atomic_write(
            study_meta_path(book_dir),
            json.dumps({
                "card_count": 0,
                "due_count": 0,
                "last_generated_at": None,
                "avg_grade": None,
            }, indent=2),
        )
    return True


def load_cards(book_dir: Path) -> List[Dict[str, Any]]:
    """Load all card records from cards.jsonl."""
    p = cards_path(book_dir)
    if not p.exists():
        return []
    cards = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cards.append(json.loads(line))
    return cards


def load_progress(book_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load progress.json keyed by card_id."""
    p = progress_path(book_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_study_meta(book_dir: Path) -> Dict[str, Any]:
    """Load study_meta.json."""
    p = study_meta_path(book_dir)
    if not p.exists():
        return {"card_count": 0, "due_count": 0, "last_generated_at": None, "avg_grade": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"card_count": 0, "due_count": 0, "last_generated_at": None, "avg_grade": None}


def get_study_stats(book_dir: Path) -> Dict[str, Any]:
    """Return study stats for a book (card_count, due_count, last_generated_at, avg_grade)."""
    meta = load_study_meta(book_dir)
    cards = load_cards(book_dir)
    meta["card_count"] = len(cards)
    meta["due_count"] = _count_due(book_dir)
    return meta


def save_progress(book_dir: Path, progress: Dict[str, Dict[str, Any]]) -> None:
    """Atomically write progress.json."""
    _atomic_write(progress_path(book_dir), json.dumps(progress, indent=2, ensure_ascii=False))


def save_study_meta(book_dir: Path, meta: Dict[str, Any]) -> None:
    """Atomically write study_meta.json."""
    _atomic_write(study_meta_path(book_dir), json.dumps(meta, indent=2, ensure_ascii=False))


def append_card(book_dir: Path, card: Dict[str, Any]) -> None:
    """Append a card record to cards.jsonl atomically."""
    _atomic_append_jsonl(cards_path(book_dir), card)


def get_existing_chunk_ids(book_dir: Path) -> set:
    """Return set of chunk_ids that already have cards."""
    cards = load_cards(book_dir)
    return {c.get("chunk_id") for c in cards if c.get("chunk_id")}


def _chunk_id(book_id: str, chunk_index: int) -> str:
    """Stable chunk identifier."""
    return f"{book_id}_{chunk_index}"


def _naive_keywords(text: str, top_n: int = 3) -> List[str]:
    """Extract simple keywords (longer words, non-stop)."""
    stop = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "must", "shall", "can", "need", "dare",
            "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
            "into", "through", "during", "before", "after", "above", "below"}
    words = re.findall(r"[a-zA-Z]{4,}", text)
    counts: Dict[str, int] = {}
    for w in words:
        wl = w.lower()
        if wl not in stop:
            counts[wl] = counts.get(wl, 0) + 1
    sorted_w = sorted(counts.items(), key=lambda x: -x[1])
    return [w for w, _ in sorted_w[:top_n]]


def _generate_question_answer(chunk: Dict[str, Any], strategy: str) -> tuple:
    """
    Heuristic card generation (no LLM).
    Returns (question, answer).
    """
    text = chunk.get("text", "").strip()
    if not text:
        return ("Summarize this chunk.", text[:200] if text else "")
    if strategy == "coverage":
        keywords = _naive_keywords(text)
        if keywords:
            term = keywords[0].capitalize()
            return (f"Define key term: {term}", text[:400] + ("..." if len(text) > 400 else ""))
    return ("Summarize this chunk.", text[:400] + ("..." if len(text) > 400 else ""))


def generate_cards_for_book(
    index_root: Path,
    book_id: str,
    max_cards: int = 20,
    strategy: str = "coverage",
) -> Dict[str, Any]:
    """
    Generate new cards for a book from chunks. Dedupes by chunk_id.
    Returns {generated_count, skipped_count, elapsed_ms}.
    """
    index_root = Path(index_root).resolve()
    book_dir = index_root / "books" / book_id
    chunks_path = book_dir / "chunks.jsonl"
    if not chunks_path.exists():
        return {"generated_count": 0, "skipped_count": 0, "elapsed_ms": 0}

    verify_study(index_root, book_id)
    existing = get_existing_chunk_ids(book_dir)
    cards = load_cards(book_dir)
    progress = load_progress(book_dir)
    meta = load_study_meta(book_dir)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    chunks: List[Dict[str, Any]] = []
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        chunks.append(json.loads(line))

    generated = 0
    skipped = 0
    t0 = time.perf_counter()

    for i, chunk in enumerate(chunks):
        if generated >= max_cards:
            break
        chunk_idx = chunk.get("chunk_index", i)
        cid = _chunk_id(book_id, chunk_idx)
        if cid in existing:
            skipped += 1
            continue
        question, answer = _generate_question_answer(chunk, strategy)
        card_id = str(uuid.uuid4())
        page = chunk.get("page_start") or chunk.get("page_end")
        section = chunk.get("section_title") or chunk.get("section_number") or None
        card_rec = {
            "card_id": card_id,
            "book_id": book_id,
            "chunk_id": cid,
            "question": question,
            "answer": answer,
            "created_at": now,
            "source": {"page": page, "section": section},
        }
        append_card(book_dir, card_rec)
        progress[card_id] = {
            "ease": 2.5,
            "interval_days": 0.0,
            "due_at": now,
            "last_reviewed_at": None,
            "reviews": 0,
        }
        existing.add(cid)
        generated += 1

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    save_progress(book_dir, progress)
    meta["card_count"] = len(cards) + generated
    meta["due_count"] = _count_due(book_dir, now)
    meta["last_generated_at"] = now
    save_study_meta(book_dir, meta)

    return {"generated_count": generated, "skipped_count": skipped, "elapsed_ms": elapsed_ms}


def _count_due(book_dir: Path, as_of: Optional[str] = None) -> int:
    """Count cards with due_at <= as_of (only for cards that exist)."""
    if as_of is None:
        as_of = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cards = load_cards(book_dir)
    progress = load_progress(book_dir)
    card_ids = {c["card_id"] for c in cards}
    count = 0
    for cid in card_ids:
        pid = progress.get(cid, {})
        due_at = pid.get("due_at")
        if due_at and due_at <= as_of:
            count += 1
    return count


def get_due_cards(book_dir: Path, limit: int = 20, as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return cards with due_at <= as_of, with question and minimal source."""
    if as_of is None:
        as_of = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cards = load_cards(book_dir)
    progress = load_progress(book_dir)
    due = []
    for c in cards:
        pid = progress.get(c["card_id"], {})
        due_at = pid.get("due_at")
        if due_at and due_at <= as_of:
            due.append({
                "card_id": c["card_id"],
                "question": c.get("question", ""),
                "answer": c.get("answer", ""),
                "source": c.get("source", {}),
            })
    due.sort(key=lambda x: progress.get(x["card_id"], {}).get("due_at", ""))
    return due[:limit]


def review_card(
    book_dir: Path,
    card_id: str,
    grade: int,
) -> Dict[str, Any]:
    """
    Update progress using SM-2 style. grade 0-5.
    Returns updated scheduling fields.
    """
    if not (0 <= grade <= 5):
        raise ValueError("grade must be 0-5")
    cards = load_cards(book_dir)
    card = next((c for c in cards if c["card_id"] == card_id), None)
    if not card:
        raise KeyError(f"Card not found: {card_id}")
    progress = load_progress(book_dir)
    rec = progress.get(card_id, {"ease": 2.5, "interval_days": 0.0, "reviews": 0})
    ease = float(rec.get("ease", 2.5))
    interval = float(rec.get("interval_days", 0.0))
    reviews = int(rec.get("reviews", 0))

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if grade < 3:
        new_interval = 0.0
        new_ease = max(1.3, ease - 0.2)
        new_reviews = 0
        due_at = now
    else:
        if reviews == 0:
            new_interval = 1.0
        elif reviews == 1:
            new_interval = 6.0
        else:
            new_interval = round(interval * ease, 1)
        new_ease = ease + (0.1 - (5 - grade) * 0.02)
        new_ease = max(1.3, round(new_ease, 2))
        new_reviews = reviews + 1
        import datetime
        from datetime import timedelta
        dt = datetime.datetime.fromisoformat(now.replace("Z", "+00:00"))
        due_dt = dt + timedelta(days=new_interval)
        due_at = due_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    progress[card_id] = {
        "ease": new_ease,
        "interval_days": new_interval,
        "due_at": due_at,
        "last_reviewed_at": now,
        "reviews": new_reviews,
    }
    save_progress(book_dir, progress)

    meta = load_study_meta(book_dir)
    grades = meta.get("grades", [])
    grades.append(grade)
    meta["grades"] = grades[-100:]
    meta["avg_grade"] = round(sum(grades) / len(grades), 2) if grades else None
    save_study_meta(book_dir, meta)

    return {
        "ease": new_ease,
        "interval_days": new_interval,
        "due_at": due_at,
        "last_reviewed_at": now,
    }
