"""Index status and build service for first-run UX."""

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _family_key(filename: str) -> str:
    """Normalize filename for family grouping."""
    stem = Path(filename).stem.lower()
    return re.sub(r"\s+", " ", stem).strip()


def get_index_status(index_root: Path, pdf_dir: Path) -> Dict[str, Any]:
    """
    Return index status. Cheap: reads library.json only when present,
    else falls back to data.json (legacy).
    """
    index_root = Path(index_root).resolve()
    pdf_dir = Path(pdf_dir).resolve()

    from server.library import get_status_from_library

    lib_status = get_status_from_library(index_root, pdf_dir)
    if lib_status["index_exists"]:
        return lib_status

    # Fallback: legacy data.json
    data_file = index_root / "data.json"
    index_exists = data_file.exists()
    index_ready = False
    chunk_count = 0
    book_counts: List[Dict[str, Any]] = []

    if index_exists:
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            documents = data.get("documents", [])
            metadatas = data.get("metadatas", [])
            chunk_count = len(documents)
            index_ready = chunk_count > 0

            counts: Dict[str, int] = {}
            for meta in metadatas:
                bk = meta.get("book", "unknown")
                counts[bk] = counts.get(bk, 0) + 1
            book_counts = [
                {"book": name, "chunks": count}
                for name, count in sorted(counts.items())
            ]
        except (json.JSONDecodeError, OSError):
            index_ready = False

    return {
        "ok": True,
        "index_root": str(index_root),
        "pdf_dir": str(pdf_dir),
        "index_exists": index_exists,
        "index_ready": index_ready,
        "chunk_count": chunk_count,
        "book_counts": book_counts,
        "consistency": {"ok": True, "issues": []},
    }


def build_index_from_pdfs(
    pdf_dir: Path,
    index_root: Path,
) -> Dict[str, Any]:
    """
    Incremental ingest from PDFs into library.
    Rebuilds search index only if at least one book ingested with status=ready.
    Returns report + stats. Raises ValueError if pdf_dir empty or no PDFs.
    """
    pdf_dir = Path(pdf_dir).resolve()
    index_root = Path(index_root).resolve()

    if not pdf_dir.exists():
        raise ValueError(f"PDF directory does not exist: {pdf_dir}")

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise ValueError(
            f"No PDFs found in {pdf_dir}. Add PDFs then try again."
        )

    from scripts.ingest_library import ingest_pdfs_incremental, rebuild_search_index

    t0 = time.perf_counter()
    report = ingest_pdfs_incremental(pdf_dir, index_root, copy_source=True)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    report["elapsed_ms"] = elapsed_ms

    rebuilt = report.get("rebuilt_search_index", False)
    if rebuilt:
        rebuild_search_index(index_root)

    # Stats: current /status-style summary
    stats = get_index_status(index_root, pdf_dir)

    return {
        "report": {
            "elapsed_ms": elapsed_ms,
            "ingested": report.get("ingested", []),
            "skipped": report.get("skipped", []),
            "failed": report.get("failed", []),
            "rebuilt_search_index": rebuilt,
            "avg_ingest_ms": report.get("avg_ingest_ms", 0),
        },
        "stats": {
            "chunk_count": stats.get("chunk_count", 0),
            "book_counts": stats.get("book_counts", []),
            "consistency": stats.get("consistency", {"ok": True, "issues": []}),
        },
        "rebuilt_search_index": rebuilt,
        "any_status_changed": report.get("any_status_changed", False),
    }


def _get_library_books(index_root: Path) -> List[Dict[str, Any]]:
    """Get ready books from library.json."""
    lib_path = Path(index_root).resolve() / "library.json"
    if not lib_path.exists():
        return []
    try:
        with open(lib_path, "r") as f:
            lib = json.load(f)
        return [b for b in lib.get("books", []) if b.get("status") == "ready"]
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write_library(index_root: Path, data: Dict[str, Any]) -> None:
    """Write library.json atomically via .tmp then rename."""
    path = Path(index_root).resolve() / "library.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _count_chunks_jsonl(path: Path) -> int:
    """Count non-empty lines in chunks.jsonl."""
    if not path.exists():
        return 0
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _atomic_write_book_json(path: Path, data: Dict[str, Any]) -> None:
    """Write book.json atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def repair_library(
    index_root: Path,
    pdf_dir: Optional[Path] = None,
    mode: str = "repair",
    rebuild_search_index: Optional[bool] = None,
    prune_tmp: bool = True,
) -> Dict[str, Any]:
    """
    Scan disk under books/, repair metadata, optionally rebuild search index.
    Returns report + stats. Does not require PDFs.
    """
    index_root = Path(index_root).resolve()
    books_dir = index_root / "books"
    t0 = time.perf_counter()

    pdf_dir = pdf_dir or index_root / "pdfs"

    # Legacy mode: no books/ → no-op
    if not books_dir.exists():
        stats = get_index_status(index_root, pdf_dir)
        return {
            "report": {
                "elapsed_ms": 0,
                "scanned_books": 0,
                "repaired_books": [],
                "error_books": [],
                "pruned_tmp_count": 0,
                "rebuilt_library_json": False,
                "rebuilt_search_index": False,
                "repairs_changed_state": False,
                "consistency": stats.get("consistency", {"ok": True, "issues": []}),
            },
            "stats": stats,
            "library_json_changed": False,
            "rebuilt_search_index": False,
        }

    # Load existing library if present (may be corrupt)
    old_lib = None
    lib_path = index_root / "library.json"
    if lib_path.exists():
        try:
            with open(lib_path, "r", encoding="utf-8") as f:
                old_lib = json.load(f)
        except (json.JSONDecodeError, OSError):
            old_lib = None

    old_by_id: Dict[str, Dict[str, Any]] = {}
    if old_lib:
        for b in old_lib.get("books", []):
            bid = b.get("book_id")
            if bid:
                old_by_id[bid] = dict(b)

    repaired_books: List[Dict[str, Any]] = []
    error_books: List[Dict[str, Any]] = []
    new_books: List[Dict[str, Any]] = []
    repairs_changed_state = False

    # Scan each book folder
    book_dirs = sorted([d for d in books_dir.iterdir() if d.is_dir()])
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for book_dir in book_dirs:
        book_id = book_dir.name
        chunks_path = book_dir / "chunks.jsonl"
        book_json_path = book_dir / "book.json"
        source_pdf_path = book_dir / "source.pdf"

        issues: List[str] = []
        actions: List[str] = []
        old_rec = old_by_id.get(book_id)

        # Check chunks
        chunk_count = _count_chunks_jsonl(chunks_path)
        chunks_ok = chunk_count > 0

        # Check book.json
        book_json_exists = book_json_path.exists()
        book_rec: Optional[Dict[str, Any]] = None

        if book_json_exists:
            try:
                with open(book_json_path, "r", encoding="utf-8") as f:
                    book_rec = json.load(f)
            except (json.JSONDecodeError, OSError):
                book_rec = None
                issues.append("book.json corrupt")

        if book_rec is None and book_json_exists:
            issues.append("book.json unreadable")
            error_books.append({"book_id": book_id, "issues": issues})
            continue

        if book_json_exists and not chunks_ok:
            issues.append("chunks.jsonl missing or empty")
            status = "error"
            error_message = "; ".join(issues)
            rec = (old_rec or {})
            rec.update({
                "book_id": book_id,
                "filename": rec.get("filename", f"{book_id}.pdf"),
                "title": rec.get("title", book_id),
                "chunk_count": 0,
                "status": status,
                "error_message": error_message,
                "updated_at": now,
            })
            new_books.append(rec)
            error_books.append({"book_id": book_id, "issues": issues})
            if old_rec and old_rec.get("status") != status:
                repairs_changed_state = True
            continue

        if not chunks_ok:
            continue

        if not book_json_exists or book_rec is None:
            # Reconstruct minimal book.json
            filename = (old_rec.get("filename") if old_rec else None) or f"{book_id}.pdf"
            title = (old_rec.get("title") if old_rec else None) or Path(filename).stem
            book_rec = {
                "book_id": book_id,
                "filename": filename,
                "title": title,
                "sha256": book_id,
                "added_at": old_rec.get("added_at", now) if old_rec else now,
                "updated_at": now,
                "chunk_count": chunk_count,
                "status": "ready",
                "supersedes": old_rec.get("supersedes", []) if old_rec else [],
                "superseded_by": old_rec.get("superseded_by", []) if old_rec else [],
                "ingest_ms": old_rec.get("ingest_ms", 0) if old_rec else 0,
            }
            book_rec.pop("error_message", None)
            if mode == "repair":
                _atomic_write_book_json(book_json_path, book_rec)
            actions.append("reconstructed book.json")
            repairs_changed_state = repairs_changed_state or (mode == "repair")
            repaired_books.append({"book_id": book_id, "actions": actions})
        else:
            book_rec = dict(book_rec)
            book_rec["chunk_count"] = chunk_count
            book_rec["status"] = "ready"
            book_rec.pop("error_message", None)
            book_rec["updated_at"] = now
            if old_rec and old_rec.get("status") == "error":
                actions.append("cleared error status")
                repairs_changed_state = True
                repaired_books.append({"book_id": book_id, "actions": actions})

        if not source_pdf_path.exists():
            issues.append("source.pdf missing")

        new_books.append(book_rec)

    # Infer supersedes/superseded_by by family_key if not present
    family_to_books: Dict[str, List[Dict[str, Any]]] = {}
    for b in new_books:
        if b.get("status") != "ready":
            continue
        fk = _family_key(b.get("filename", ""))
        if fk not in family_to_books:
            family_to_books[fk] = []
        family_to_books[fk].append(b)

    for b in new_books:
        if b.get("status") != "ready":
            continue
        if b.get("supersedes") or b.get("superseded_by"):
            continue
        fk = _family_key(b.get("filename", ""))
        same_family = [x for x in family_to_books.get(fk, []) if x["book_id"] != b["book_id"]]
        if not same_family:
            continue
        by_updated = sorted(same_family, key=lambda x: x.get("updated_at", ""), reverse=True)
        latest = by_updated[0]
        if latest["book_id"] == b["book_id"]:
            superseded = [x["book_id"] for x in by_updated[1:]]
            b["supersedes"] = superseded
            for x in by_updated[1:]:
                x.setdefault("superseded_by", []).append(b["book_id"])
        else:
            b["superseded_by"] = [latest["book_id"]]

    # In verify mode: don't write, just report
    if mode == "verify":
        lib = {"books": new_books} if new_books else (old_lib or {"books": []})
        from server.library import verify_library
        consistency_ok, consistency_issues, _ = verify_library(index_root, lib)
        consistency = {"ok": consistency_ok, "issues": consistency_issues}
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        stats = get_index_status(index_root, pdf_dir)
        return {
            "report": {
                "elapsed_ms": elapsed_ms,
                "scanned_books": len(book_dirs),
                "repaired_books": repaired_books,
                "error_books": error_books,
                "pruned_tmp_count": 0,
                "rebuilt_library_json": False,
                "rebuilt_search_index": False,
                "repairs_changed_state": False,
                "consistency": consistency,
            },
            "stats": stats,
            "library_json_changed": False,
            "rebuilt_search_index": False,
        }

    # Prune .tmp files
    pruned_tmp_count = 0
    if prune_tmp:
        for p in index_root.rglob("*.tmp"):
            try:
                p.unlink()
                pruned_tmp_count += 1
            except OSError:
                pass
        if pruned_tmp_count > 0:
            repairs_changed_state = True

    # Build new library.json
    lib = {
        "version": "0.2",
        "created_at": (old_lib.get("created_at", now) if old_lib else now),
        "updated_at": now,
        "books": new_books,
    }
    _atomic_write_library(index_root, lib)
    rebuilt_library_json = True

    # Verify
    from server.library import verify_library
    consistency_ok, consistency_issues, _ = verify_library(index_root, lib)
    consistency = {"ok": consistency_ok, "issues": consistency_issues}

    # Rebuild search index
    should_rebuild = (
        repairs_changed_state
        and (rebuild_search_index if rebuild_search_index is not None else True)
    )
    rebuilt_search = False
    if should_rebuild:
        try:
            from scripts.ingest_library import rebuild_search_index
            rebuild_search_index(index_root)
            rebuilt_search = True
        except Exception as e:
            consistency["issues"] = consistency.get("issues", []) + [
                f"Search index rebuild failed: {e!s}"
            ]
            consistency["ok"] = False

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    stats = get_index_status(index_root, pdf_dir)

    return {
        "report": {
            "elapsed_ms": elapsed_ms,
            "scanned_books": len(book_dirs),
            "repaired_books": repaired_books,
            "error_books": error_books,
            "pruned_tmp_count": pruned_tmp_count,
            "rebuilt_library_json": rebuilt_library_json,
            "rebuilt_search_index": rebuilt_search,
            "repairs_changed_state": repairs_changed_state,
            "consistency": consistency,
        },
        "stats": stats,
        "library_json_changed": True,
        "rebuilt_search_index": rebuilt_search,
    }


def clear_index(index_root: Path, project_root: Path) -> None:
    """
    Delete INDEX_ROOT contents (books/, search/, library.json, legacy artifacts).
    Guarded: index_root must be under project_root.
    """
    index_root = Path(index_root).resolve()
    project_root = Path(project_root).resolve()
    try:
        index_root.relative_to(project_root)
    except ValueError:
        raise ValueError(
            f"index_root {index_root} is not under project root {project_root}"
        )

    for name in ["books", "search", "logs"]:
        p = index_root / name
        if p.exists():
            import shutil
            shutil.rmtree(p)

    for name in [
        "library.json",
        "data.json",
        "vectorizer.pkl",
        "vectors.pkl",
        "study_cards.jsonl",
        "session_log.jsonl",
        "graph_registry.json",
        "_last_answer.json",
    ]:
        p = index_root / name
        if p.exists():
            p.unlink()
