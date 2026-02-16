"""
Incremental ingest for Atrium Library v0.2.

Ingests PDFs from pdf_dir into INDEX_ROOT/books/<book_id>/.
Uses sha256 of PDF bytes as book_id. Skips duplicates. Handles family versioning.
Atomic writes: temp file then rename. Idempotent. BuildReport for UI.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent


def _family_key(filename: str) -> str:
    """Normalize filename for family grouping."""
    stem = Path(filename).stem.lower()
    return re.sub(r"\s+", " ", stem).strip()


def _sha256_file(path: Path) -> str:
    """Compute sha256 hash of file bytes."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, content: str | bytes, mode: str = "w") -> None:
    """Write to .tmp then rename for atomicity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if mode == "wb":
        with open(tmp, "wb") as f:
            f.write(content)
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
    tmp.replace(path)


def _sections_to_chunks_jsonl(sections_path: Path, book_name: str) -> List[Dict[str, Any]]:
    """Read SectionsWithText JSONL and return list of chunk dicts for chunks.jsonl."""
    chunks = []
    with open(sections_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            chunks.append({
                "text": rec.get("text", ""),
                "book_name": rec.get("book_name", book_name),
                "chapter_number": rec.get("chapter_number", "unknown"),
                "section_number": rec.get("section_number", ""),
                "section_title": rec.get("section_title", ""),
                "page_start": rec.get("page_start", 0),
                "page_end": rec.get("page_end", 0),
                "chunk_index": rec.get("chunk_index", 0),
                "total_chunks": rec.get("total_chunks", 1),
                "word_count": rec.get("word_count", 0),
            })
    return chunks


def get_active_version_per_family(lib: Dict[str, Any]) -> Dict[str, str]:
    """Return family_key -> book_id of latest ready version (for UI)."""
    family_to_latest: Dict[str, Tuple[str, str]] = {}  # family -> (book_id, updated_at)
    for b in lib.get("books", []):
        if b.get("status") != "ready":
            continue
        fk = _family_key(b.get("filename", ""))
        updated = b.get("updated_at", "")
        if fk not in family_to_latest or updated > family_to_latest[fk][1]:
            family_to_latest[fk] = (b["book_id"], updated)
    return {fk: bid for fk, (bid, _) in family_to_latest.items()}


def ingest_one_pdf(
    pdf_path: Path,
    index_root: Path,
    copy_source: bool = True,
) -> Tuple[str, int, int, str, Optional[str]]:
    """
    Ingest a single PDF into the library. Atomic writes.
    Returns (book_id, chunk_count, ingest_ms, status, error_message).
    status is "ready" or "error".
    """
    index_root = Path(index_root).resolve()
    pdf_path = Path(pdf_path).resolve()

    book_id = _sha256_file(pdf_path)
    book_dir = index_root / "books" / book_id
    book_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    error_message: Optional[str] = None

    try:
        from pdf_to_jsonl import convert_pdf

        pdf_name = pdf_path.stem
        _doc_id, output_dir = convert_pdf(
            pdf_path,
            output_dir_name=pdf_name,
            auto_chunk=True,
            backend="pymupdf",
            pymupdf_mode="text",
        )

        chunked_file = output_dir / f"{pdf_name}_SectionsWithText_Chunked.jsonl"
        plain_file = output_dir / f"{pdf_name}_SectionsWithText.jsonl"
        sections_file = chunked_file if chunked_file.exists() else plain_file

        if not sections_file.exists():
            return (book_id, 0, int((time.perf_counter() - t0) * 1000), "error", "No sections file")

        chunks = _sections_to_chunks_jsonl(sections_file, pdf_name)
        if not chunks:
            return (book_id, 0, int((time.perf_counter() - t0) * 1000), "error", "No chunks")

        for c in chunks:
            c["book_id"] = book_id

        # Atomic write chunks.jsonl
        chunks_path = book_dir / "chunks.jsonl"
        lines = [json.dumps(c, ensure_ascii=False) + "\n" for c in chunks]
        _atomic_write(chunks_path, "".join(lines))

        # Atomic copy source.pdf
        if copy_source:
            tmp_pdf = book_dir / "source.pdf.tmp"
            shutil.copy2(pdf_path, tmp_pdf)
            tmp_pdf.replace(book_dir / "source.pdf")

        ingest_ms = int((time.perf_counter() - t0) * 1000)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        book_meta = {
            "book_id": book_id,
            "filename": pdf_path.name,
            "title": pdf_name,
            "sha256": book_id,
            "added_at": now,
            "updated_at": now,
            "chunk_count": len(chunks),
            "status": "ready",
            "ingest_ms": ingest_ms,
        }
        book_path = book_dir / "book.json"
        _atomic_write(book_path, json.dumps(book_meta, ensure_ascii=False, indent=2))

        return (book_id, len(chunks), ingest_ms, "ready", None)
    except Exception as e:
        error_message = str(e)
        return (book_id, 0, int((time.perf_counter() - t0) * 1000), "error", error_message)


def ingest_pdfs_incremental(
    pdf_dir: Path,
    index_root: Path,
    copy_source: bool = True,
) -> Dict[str, Any]:
    """
    Incrementally ingest all PDFs in pdf_dir into the library.
    Atomic library.json updates. Returns BuildReport-style dict.
    """
    pdf_dir = Path(pdf_dir).resolve()
    index_root = Path(index_root).resolve()

    library_path = index_root / "library.json"
    books_dir = index_root / "books"
    books_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()

    # Load or create library
    if library_path.exists():
        with open(library_path, "r", encoding="utf-8") as f:
            lib = json.load(f)
    else:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lib = {
            "version": "0.2",
            "created_at": now,
            "updated_at": now,
            "books": [],
        }

    existing_by_id = {b["book_id"]: b for b in lib["books"]}
    family_to_books: Dict[str, List[Dict]] = {}
    for b in lib["books"]:
        fk = _family_key(b.get("filename", ""))
        if fk not in family_to_books:
            family_to_books[fk] = []
        family_to_books[fk].append(b)

    ingested: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    ingest_times: List[int] = []
    any_status_changed = False

    pdfs = sorted(pdf_dir.glob("*.pdf"))

    for pdf_path in pdfs:
        book_id = _sha256_file(pdf_path)
        filename = pdf_path.name
        existing = existing_by_id.get(book_id)

        if existing and existing.get("status") == "ready":
            skipped.append({"filename": filename, "reason": "duplicate_hash"})
            continue

        # Add/update record with status=processing before ingest
        if existing:
            existing["status"] = "processing"
            existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        else:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            rec = {
                "book_id": book_id,
                "filename": filename,
                "sha256": book_id,
                "added_at": now,
                "updated_at": now,
                "chunk_count": 0,
                "status": "processing",
                "supersedes": [],
                "superseded_by": [],
                "ingest_ms": 0,
            }
            lib["books"].append(rec)
            existing_by_id[book_id] = rec
            family_key = _family_key(filename)
            if family_key not in family_to_books:
                family_to_books[family_key] = []
            family_to_books[family_key].append(rec)

        # Atomic write library.json after adding processing record (so crash leaves valid JSON)
        _atomic_write(library_path, json.dumps(lib, ensure_ascii=False, indent=2))

        book_id, chunk_count, ingest_ms, status, error_message = ingest_one_pdf(
            pdf_path, index_root, copy_source=copy_source
        )

        rec = existing_by_id[book_id]
        rec["status"] = status
        rec["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec["ingest_ms"] = ingest_ms
        if status == "error":
            rec["error_message"] = error_message or "Unknown error"
            failed.append({"filename": filename, "error": rec["error_message"]})
            any_status_changed = True
        else:
            rec["chunk_count"] = chunk_count
            ingest_times.append(ingest_ms)
            family_key = _family_key(filename)

            # Supersede only ready books (not error)
            supersedes: List[str] = []
            if family_key in family_to_books:
                for old in family_to_books[family_key]:
                    if old["book_id"] != book_id and old.get("status") == "ready":
                        supersedes.append(old["book_id"])
                        old.setdefault("superseded_by", []).append(book_id)
            rec["supersedes"] = supersedes

            ingested.append({
                "book_id": book_id,
                "filename": filename,
                "title": rec.get("title", Path(filename).stem),
                "chunk_count": chunk_count,
                "ingest_ms": ingest_ms,
                "status": status,
            })
            any_status_changed = True

        # Atomic write library.json after each book
        _atomic_write(library_path, json.dumps(lib, ensure_ascii=False, indent=2))

    lib["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if ingest_times:
        lib["avg_ingest_ms"] = sum(ingest_times) // len(ingest_times)
    lib.setdefault("consistency", {"ok": True, "issues": []})

    _atomic_write(library_path, json.dumps(lib, ensure_ascii=False, indent=2))

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    ready_ingested = [i for i in ingested if i.get("status") == "ready"]

    return {
        "elapsed_ms": elapsed_ms,
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
        "rebuilt_search_index": len(ready_ingested) > 0,
        "any_status_changed": any_status_changed,
        "avg_ingest_ms": sum(ingest_times) // len(ingest_times) if ingest_times else 0,
    }


def rebuild_search_index(index_root: Path) -> None:
    """
    Rebuild global TF-IDF search index (data.json, vectorizer.pkl, vectors.pkl)
    from all ready books in the library.
    """
    index_root = Path(index_root).resolve()
    lib_path = index_root / "library.json"
    if not lib_path.exists():
        return

    with open(lib_path, "r", encoding="utf-8") as f:
        lib = json.load(f)

    ready = [b for b in lib.get("books", []) if b.get("status") == "ready"]
    if not ready:
        return

    for name in ("data.json", "vectorizer.pkl", "vectors.pkl"):
        p = index_root / name
        if p.exists():
            p.unlink()

    from legacy.textbook_search_offline import TextbookSearchOffline

    search = TextbookSearchOffline(db_path=str(index_root))
    books_dir = index_root / "books"

    for b in ready:
        book_id = b["book_id"]
        chunks_file = books_dir / book_id / "chunks.jsonl"
        if not chunks_file.exists():
            continue
        display_name = b.get("filename", book_id)
        if display_name.endswith(".pdf"):
            display_name = display_name[:-4]
        search.load_textbook(chunks_file, book_name=display_name)
