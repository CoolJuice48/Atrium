"""
Book outline: hierarchical chapter/section structure for scope selection.

Derives outline from chunks.jsonl (chapter_number, section_number, page_start, page_end).
Persists as outline.json in book dir. Falls back to page-based segmentation if no structure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class OutlineItem:
    """Single outline node (chapter or section)."""
    id: str
    title: str
    level: int  # 1=chapter, 2=section
    start_page: int
    end_page: int
    parent_id: Optional[str] = None


def _load_chunks(book_dir: Path) -> List[Dict[str, Any]]:
    """Load chunks from book_dir/chunks.jsonl."""
    path = book_dir / "chunks.jsonl"
    if not path.exists():
        return []
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return chunks


def _parse_page(val: Any) -> int:
    """Parse page number from chunk metadata."""
    if val is None:
        return 0
    if isinstance(val, int):
        return max(0, val)
    try:
        return max(0, int(val))
    except (ValueError, TypeError):
        return 0


def _build_outline_from_chunks(chunks: List[Dict[str, Any]]) -> List[OutlineItem]:
    """
    Build hierarchical outline from chunks with chapter/section metadata.
    Groups by (chapter_number, section_number) and computes page ranges.
    """
    # Aggregate page ranges per (chapter, section)
    ranges: Dict[Tuple[str, str], Tuple[int, int, str]] = {}  # (ch, sec) -> (min_p, max_p, title)
    for c in chunks:
        ch = str(c.get("chapter_number", "unknown")).strip()
        sec = str(c.get("section_number", "")).strip()
        title = str(c.get("section_title", "")).strip()
        ps = _parse_page(c.get("page_start"))
        pe = _parse_page(c.get("page_end"))
        if ps == 0 and pe == 0:
            continue
        key = (ch, sec)
        if key not in ranges:
            ranges[key] = (ps, pe, title)
        else:
            lo, hi, t = ranges[key]
            ranges[key] = (min(lo, ps), max(hi, pe), t or title)

    if not ranges:
        return []

    # Build chapter-level items
    ch_pages: Dict[str, Tuple[int, int, str]] = {}
    for (ch, sec), (lo, hi, title) in ranges.items():
        if ch not in ch_pages:
            ch_pages[ch] = (lo, hi, f"Chapter {ch}")
        else:
            clo, chi, _ = ch_pages[ch]
            ch_pages[ch] = (min(clo, lo), max(chi, hi), f"Chapter {ch}")

    items: List[OutlineItem] = []
    seen_chapters: set = set()

    def _sort_key(x):
        (ch, sec), (lo, hi, _) = x
        return (lo, hi)

    for (ch, sec), (lo, hi, title) in sorted(ranges.items(), key=_sort_key):
        ch_id = f"ch_{ch}"
        if ch not in seen_chapters:
            seen_chapters.add(ch)
            clo, chi, ch_title = ch_pages.get(ch, (lo, hi, f"Chapter {ch}"))
            items.append(OutlineItem(
                id=ch_id,
                title=ch_title,
                level=1,
                start_page=clo,
                end_page=chi,
                parent_id=None,
            ))
        if sec:
            sec_id = f"ch_{ch}_sec_{sec.replace('.', '_')}"
            items.append(OutlineItem(
                id=sec_id,
                title=title or f"Section {ch}.{sec}",
                level=2,
                start_page=lo,
                end_page=hi,
                parent_id=ch_id,
            ))

    return items


def _fallback_outline(chunks: List[Dict[str, Any]], page_chunk_size: int = 20) -> List[OutlineItem]:
    """Fallback: segment by every N pages with generic labels."""
    if not chunks:
        return []
    all_pages: List[int] = []
    for c in chunks:
        ps = _parse_page(c.get("page_start"))
        pe = _parse_page(c.get("page_end"))
        if ps > 0:
            all_pages.append(ps)
        if pe > 0:
            all_pages.append(pe)
    if not all_pages:
        return []
    min_p = min(all_pages)
    max_p = max(all_pages)
    items = []
    start = min_p
    idx = 0
    while start <= max_p:
        end = min(start + page_chunk_size - 1, max_p)
        items.append(OutlineItem(
            id=f"pages_{start}_{end}",
            title=f"Pages {start}–{end}",
            level=1,
            start_page=start,
            end_page=end,
            parent_id=None,
        ))
        start = end + 1
        idx += 1
    return items


def compute_outline_id(items: List[OutlineItem]) -> str:
    """Stable hash of outline structure for invalidation."""
    parts = []
    for it in items:
        parts.append(f"{it.id}:{it.title}:{it.start_page}-{it.end_page}")
    h = hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()
    return h[:16]


def build_outline(book_dir: Path) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Build outline from chunks. Returns (outline_id, items_as_dicts).
    Uses chapter/section structure if present, else page-based fallback.
    """
    chunks = _load_chunks(book_dir)
    if not chunks:
        return ("", [])

    items = _build_outline_from_chunks(chunks)
    if not items:
        items = _fallback_outline(chunks)

    outline_id = compute_outline_id(items)
    dicts = [
        {
            "id": it.id,
            "title": it.title,
            "level": it.level,
            "start_page": it.start_page,
            "end_page": it.end_page,
            "parent_id": it.parent_id,
        }
        for it in items
    ]
    return outline_id, dicts


def load_outline(book_dir: Path) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Load persisted outline from book_dir/outline.json. Returns None if missing."""
    path = book_dir / "outline.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data.get("outline_id", ""), data.get("items", []))
    except (json.JSONDecodeError, OSError):
        return None


def save_outline(book_dir: Path, outline_id: str, items: List[Dict[str, Any]]) -> None:
    """Persist outline to book_dir/outline.json."""
    book_dir.mkdir(parents=True, exist_ok=True)
    path = book_dir / "outline.json"
    data = {"outline_id": outline_id, "items": items}
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def get_or_build_outline(book_dir: Path) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Get outline: load from outline.json if present and still valid,
    else build from chunks and persist.
    """
    outline_id, items = build_outline(book_dir)
    if not items:
        return ("", [])
    save_outline(book_dir, outline_id, items)
    return outline_id, items


def resolve_scope_to_page_ranges(
    items: List[Dict[str, Any]],
    item_ids: List[str],
) -> List[Tuple[int, int]]:
    """Resolve selected item_ids to list of (start_page, end_page) ranges."""
    id_to_item = {it["id"]: it for it in items}
    ranges = []
    for iid in item_ids:
        if iid not in id_to_item:
            continue
        it = id_to_item[iid]
        ranges.append((it["start_page"], it["end_page"]))
    return sorted(ranges, key=lambda r: r[0])


def filter_chunks_by_page_ranges(
    chunks: List[Dict[str, Any]],
    ranges: List[Tuple[int, int]],
) -> List[Dict[str, Any]]:
    """Keep only chunks whose page range overlaps any of the given ranges."""
    if not ranges:
        return []
    result = []
    for c in chunks:
        ps = _parse_page(c.get("page_start"))
        pe = _parse_page(c.get("page_end"))
        if ps == 0 and pe == 0:
            continue
        chunk_lo = ps or pe
        chunk_hi = pe or ps
        for (rlo, rhi) in ranges:
            if chunk_hi >= rlo and chunk_lo <= rhi:
                result.append(c)
                break
    return result
