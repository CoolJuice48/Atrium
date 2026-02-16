"""User PDF upload + ingest as background job with progress streaming and cancel."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# Job states
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

# Phases
UPLOADING = "uploading"
EXTRACTING = "extracting"
CHUNKING = "chunking"
INDEXING = "indexing"
FINALIZING = "finalizing"

# Rate limit: in-memory per user (beta)
_user_upload_counts: Dict[str, int] = {}
_user_upload_timestamps: Dict[str, list] = {}


@dataclass
class UploadJob:
    job_id: str
    user_id: str
    filename: str
    display_title: Optional[str] = None
    status: str = QUEUED
    phase: str = ""
    message: str = ""
    current: int = 0
    total: int = 0
    error: Optional[str] = None
    cancelled: bool = False
    result: Optional[Dict[str, Any]] = None  # book_id, display_title, chunk_count


_jobs: Dict[str, UploadJob] = {}


def create_job(user_id: str, filename: str, display_title: Optional[str] = None) -> UploadJob:
    job_id = str(uuid.uuid4())
    job = UploadJob(
        job_id=job_id,
        user_id=user_id,
        filename=filename,
        display_title=display_title or Path(filename).stem,
    )
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[UploadJob]:
    return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if not job:
        return False
    if job.status in (COMPLETED, FAILED, CANCELLED):
        return False
    job.cancelled = True
    return True


def _check_cancelled(job: UploadJob) -> bool:
    return job.cancelled


def _check_rate_limit(user_id: str, limit: int) -> Optional[str]:
    """Return error message if over limit, else None."""
    now = time.time()
    # Prune old timestamps (older than 1 hour)
    if user_id in _user_upload_timestamps:
        _user_upload_timestamps[user_id] = [
            t for t in _user_upload_timestamps[user_id]
            if now - t < 3600
        ]
    count = len(_user_upload_timestamps.get(user_id, []))
    if count >= limit:
        return f"Upload rate limit: max {limit} uploads per hour"
    return None


def _record_upload(user_id: str) -> None:
    now = time.time()
    if user_id not in _user_upload_timestamps:
        _user_upload_timestamps[user_id] = []
    _user_upload_timestamps[user_id].append(now)


def run_upload_job(
    job_id: str,
    pdf_path: Path,
    index_root: Path,
    uploads_root: Path,
    display_title: Optional[str],
    owner_id: str,
) -> None:
    """Run upload ingest synchronously. Updates job state. Call from thread."""
    job = _jobs.get(job_id)
    if not job or job.status != QUEUED:
        return

    job.status = RUNNING

    def emit(phase: str, message: str, current: int = 0, total: int = 0):
        if job:
            job.phase = phase
            job.message = message
            job.current = current
            job.total = max(total, 1)

    try:
        # Get page count for progress (fast)
        page_count = 0
        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            page_count = len(doc)
            doc.close()
        except Exception:
            pass

        emit(EXTRACTING, f"Extracting text from PDF...", 0, page_count or 1)
        if _check_cancelled(job):
            job.status = CANCELLED
            job.message = "Cancelled"
            return

        from pdf_to_jsonl import convert_pdf

        base_name = pdf_path.stem
        out_dir_name = (display_title or base_name).replace(" ", "_")[:80]
        _doc_id, output_dir = convert_pdf(
            pdf_path,
            output_dir_name=out_dir_name,
            auto_chunk=True,
            backend="pymupdf",
            pymupdf_mode="text",
        )

        if _check_cancelled(job):
            job.status = CANCELLED
            job.message = "Cancelled"
            return

        chunked_file = output_dir / f"{base_name}_SectionsWithText_Chunked.jsonl"
        plain_file = output_dir / f"{base_name}_SectionsWithText.jsonl"
        sections_file = chunked_file if chunked_file.exists() else plain_file

        if not sections_file.exists():
            job.status = FAILED
            job.error = "No sections file produced"
            return

        # Chunking
        from scripts.ingest_library import (
            _atomic_write,
            _sha256_file,
            _sections_to_chunks_jsonl,
        )

        book_id = _sha256_file(pdf_path)
        index_root = Path(index_root).resolve()
        books_dir = index_root / "books"
        book_dir = books_dir / book_id
        book_dir.mkdir(parents=True, exist_ok=True)

        chunks = _sections_to_chunks_jsonl(sections_file, base_name)
        total_chunks = len(chunks)
        emit(CHUNKING, f"Creating {total_chunks} chunks...", 0, total_chunks)

        if _check_cancelled(job):
            job.status = CANCELLED
            job.message = "Cancelled"
            return

        for i, c in enumerate(chunks):
            c["book_id"] = book_id
            if (i + 1) % 10 == 0 or i == total_chunks - 1:
                emit(CHUNKING, f"Chunking...", i + 1, total_chunks)

        chunks_path = book_dir / "chunks.jsonl"
        lines = [json.dumps(c, ensure_ascii=False) + "\n" for c in chunks]
        _atomic_write(chunks_path, "".join(lines))

        # Copy source
        tmp_pdf = book_dir / "source.pdf.tmp"
        shutil.copy2(pdf_path, tmp_pdf)
        tmp_pdf.replace(book_dir / "source.pdf")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        title = display_title or base_name
        book_meta = {
            "book_id": book_id,
            "filename": pdf_path.name,
            "title": title,
            "sha256": book_id,
            "added_at": now,
            "updated_at": now,
            "chunk_count": len(chunks),
            "status": "ready",
            "ingest_ms": 0,
            "owner_id": owner_id,
        }
        book_path = book_dir / "book.json"
        _atomic_write(book_path, json.dumps(book_meta, ensure_ascii=False, indent=2))

        emit(INDEXING, "Updating search index...", 0, 1)
        if _check_cancelled(job):
            job.status = CANCELLED
            job.message = "Cancelled"
            return

        # Update library.json with owner_id
        library_path = index_root / "library.json"
        if library_path.exists():
            with open(library_path, "r", encoding="utf-8") as f:
                lib = json.load(f)
        else:
            lib = {
                "version": "0.2",
                "created_at": now,
                "updated_at": now,
                "books": [],
            }

        existing = next((b for b in lib["books"] if b.get("book_id") == book_id), None)
        if existing:
            existing["status"] = "ready"
            existing["chunk_count"] = len(chunks)
            existing["owner_id"] = owner_id
            existing["title"] = title
            existing["updated_at"] = now
        else:
            lib["books"].append({
                "book_id": book_id,
                "filename": pdf_path.name,
                "title": title,
                "sha256": book_id,
                "added_at": now,
                "updated_at": now,
                "chunk_count": len(chunks),
                "status": "ready",
                "ingest_ms": 0,
                "owner_id": owner_id,
            })
        lib["updated_at"] = now
        _atomic_write(library_path, json.dumps(lib, ensure_ascii=False, indent=2))

        # Rebuild search index
        from scripts.ingest_library import rebuild_search_index
        rebuild_search_index(index_root)

        if _check_cancelled(job):
            job.status = CANCELLED
            job.message = "Cancelled"
            return

        emit(FINALIZING, "Done", 1, 1)

        from server.services.query_service import invalidate_searcher_cache
        from server.library import invalidate_verify_cache
        invalidate_searcher_cache(str(index_root))
        invalidate_verify_cache(index_root)

        job.status = COMPLETED
        job.phase = "done"
        job.message = f"Indexed {title}"
        job.result = {
            "book_id": book_id,
            "display_title": title,
            "chunk_count": len(chunks),
        }
        _record_upload(owner_id)

    except Exception as e:
        job.status = FAILED
        job.error = str(e)
        job.message = str(e)
