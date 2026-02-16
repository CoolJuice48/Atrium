"""Pack install as background job with progress streaming and cancel."""

from __future__ import annotations

import asyncio
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# Job states
PENDING = "pending"
DOWNLOADING = "downloading"
EXTRACTING = "extracting"
INGESTING = "ingesting"
REBUILDING = "rebuilding"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"


@dataclass
class PackInstallJob:
    job_id: str
    pack_id: str
    pack_title: str
    status: str = PENDING
    phase: str = ""
    message: str = ""
    current: int = 0
    total: int = 0
    error: Optional[str] = None
    cancelled: bool = False
    result: Optional[Dict[str, Any]] = None


_jobs: Dict[str, PackInstallJob] = {}


def create_job(pack_id: str, pack_title: str) -> PackInstallJob:
    job_id = str(uuid.uuid4())
    job = PackInstallJob(job_id=job_id, pack_id=pack_id, pack_title=pack_title)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[PackInstallJob]:
    return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if not job:
        return False
    if job.status in (COMPLETED, FAILED, CANCELLED):
        return False
    job.cancelled = True
    return True


def _check_cancelled(job: PackInstallJob) -> bool:
    return job.cancelled


def run_install_job(
    job_id: str,
    download_url: str,
    packs_dist_path: Path,
    index_root: Path,
) -> None:
    """Run pack install synchronously. Updates job state. Call from thread."""
    job = _jobs.get(job_id)
    if not job or job.status != PENDING:
        return

    def emit(phase: str, message: str, current: int = 0, total: int = 0):
        if job:
            job.phase = phase
            job.message = message
            job.current = current
            job.total = total
            if phase == DOWNLOADING:
                job.status = DOWNLOADING
            elif phase == EXTRACTING:
                job.status = EXTRACTING
            elif phase == INGESTING:
                job.status = INGESTING
            elif phase == REBUILDING:
                job.status = REBUILDING

    try:
        # Resolve download: local file or URL
        local_zip = packs_dist_path / download_url.lstrip("/")
        if local_zip.exists():
            zip_path = Path(tempfile.gettempdir()) / f"atrium_pack_{job_id}.zip"
            emit(DOWNLOADING, "Copying pack...")
            if _check_cancelled(job):
                job.status = CANCELLED
                job.message = "Cancelled"
                return
            import shutil
            shutil.copy2(local_zip, zip_path)
        else:
            zip_url = download_url if download_url.startswith("http") else f"{packs_dist_path.as_uri().rstrip('/')}/{download_url.lstrip('/')}"
            emit(DOWNLOADING, "Downloading pack...")
            if _check_cancelled(job):
                job.status = CANCELLED
                job.message = "Cancelled"
                return
            import urllib.request
            zip_path = Path(tempfile.gettempdir()) / f"atrium_pack_{job_id}.zip"
            urllib.request.urlretrieve(zip_url, str(zip_path))

        if _check_cancelled(job):
            zip_path.unlink(missing_ok=True)
            job.status = CANCELLED
            job.message = "Cancelled"
            return

        # Extract
        emit(EXTRACTING, "Extracting...")
        extract_dir = Path(tempfile.mkdtemp(prefix="atrium_pack_"))
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
            zip_path.unlink(missing_ok=True)

            if _check_cancelled(job):
                import shutil
                shutil.rmtree(extract_dir, ignore_errors=True)
                job.status = CANCELLED
                job.message = "Cancelled"
                return

            # PDFs are in sources/
            pdf_dir = extract_dir / "sources"
            if not pdf_dir.exists():
                pdf_dir = extract_dir
            pdfs = sorted(pdf_dir.glob("*.pdf"))
            if not pdfs:
                job.status = FAILED
                job.error = "No PDFs found in pack"
                return

            # Ingest with progress
            emit(INGESTING, f"Ingesting {len(pdfs)} book(s)...", 0, len(pdfs))

            from scripts.ingest_library import ingest_pdfs_incremental, rebuild_search_index

            def progress_cb(i: int, total_pdfs: int, filename: str):
                emit(INGESTING, f"Ingesting {filename}...", i + 1, total_pdfs)

            # We need to add progress to ingest - use a wrapper that calls ingest_one_pdf in a loop
            # ingest_pdfs_incremental doesn't have progress_callback - we'll add it
            report = _ingest_with_progress(pdf_dir, index_root, job, progress_cb)

            if _check_cancelled(job):
                job.status = CANCELLED
                job.message = "Cancelled"
                return

            # Rebuild search index
            if report.get("rebuilt_search_index"):
                emit(REBUILDING, "Rebuilding search index...")
                rebuild_search_index(index_root)

            job.status = COMPLETED
            job.phase = "done"
            job.message = f"Installed {len(report.get('ingested', []))} book(s)"
            job.result = {
                "ingested": report.get("ingested", []),
                "skipped": report.get("skipped", []),
                "failed": report.get("failed", []),
            }
        finally:
            import shutil
            shutil.rmtree(extract_dir, ignore_errors=True)

    except Exception as e:
        job.status = FAILED
        job.error = str(e)
        job.message = str(e)


def _ingest_with_progress(
    pdf_dir: Path,
    index_root: Path,
    job: PackInstallJob,
    progress_cb: Callable[[int, int, str], None],
) -> Dict[str, Any]:
    """Ingest PDFs with progress callback and cancel check."""
    from scripts.ingest_library import (
        _atomic_write,
        _family_key,
        _sha256_file,
        ingest_one_pdf,
    )
    from scripts.ingest_library import rebuild_search_index
    import json
    import time

    pdf_dir = Path(pdf_dir).resolve()
    index_root = Path(index_root).resolve()
    library_path = index_root / "library.json"
    books_dir = index_root / "books"
    books_dir.mkdir(parents=True, exist_ok=True)

    if library_path.exists():
        with open(library_path, "r", encoding="utf-8") as f:
            lib = json.load(f)
    else:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lib = {"version": "0.2", "created_at": now, "updated_at": now, "books": []}

    existing_by_id = {b["book_id"]: b for b in lib["books"]}
    family_to_books: Dict[str, list] = {}
    for b in lib["books"]:
        fk = _family_key(b.get("filename", ""))
        if fk not in family_to_books:
            family_to_books[fk] = []
        family_to_books[fk].append(b)

    ingested = []
    skipped = []
    failed = []
    ingest_times = []
    any_status_changed = False
    pdfs = sorted(pdf_dir.glob("*.pdf"))

    for i, pdf_path in enumerate(pdfs):
        if job.cancelled:
            break
        progress_cb(i, len(pdfs), pdf_path.name)

        book_id = _sha256_file(pdf_path)
        filename = pdf_path.name
        existing = existing_by_id.get(book_id)

        if existing and existing.get("status") == "ready":
            skipped.append({"filename": filename, "reason": "duplicate_hash"})
            continue

        if existing:
            existing["status"] = "processing"
            existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        else:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            rec = {
                "book_id": book_id, "filename": filename, "sha256": book_id,
                "added_at": now, "updated_at": now, "chunk_count": 0,
                "status": "processing", "supersedes": [], "superseded_by": [], "ingest_ms": 0,
            }
            lib["books"].append(rec)
            existing_by_id[book_id] = rec
            fk = _family_key(filename)
            if fk not in family_to_books:
                family_to_books[fk] = []
            family_to_books[fk].append(rec)

        _atomic_write(library_path, json.dumps(lib, ensure_ascii=False, indent=2))

        book_id, chunk_count, ingest_ms, status, error_message = ingest_one_pdf(
            pdf_path, index_root, copy_source=True
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
            fk = _family_key(filename)
            supersedes = []
            if fk in family_to_books:
                for old in family_to_books[fk]:
                    if old["book_id"] != book_id and old.get("status") == "ready":
                        supersedes.append(old["book_id"])
                        old.setdefault("superseded_by", []).append(book_id)
            rec["supersedes"] = supersedes
            ingested.append({
                "book_id": book_id, "filename": filename,
                "title": rec.get("title", Path(filename).stem),
                "chunk_count": chunk_count, "ingest_ms": ingest_ms, "status": status,
            })
            any_status_changed = True

        _atomic_write(library_path, json.dumps(lib, ensure_ascii=False, indent=2))

    lib["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if ingest_times:
        lib["avg_ingest_ms"] = sum(ingest_times) // len(ingest_times)
    lib.setdefault("consistency", {"ok": True, "issues": []})
    _atomic_write(library_path, json.dumps(lib, ensure_ascii=False, indent=2))

    ready_ingested = [x for x in ingested if x.get("status") == "ready"]
    return {
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
        "rebuilt_search_index": len(ready_ingested) > 0,
        "any_status_changed": any_status_changed,
        "avg_ingest_ms": sum(ingest_times) // len(ingest_times) if ingest_times else 0,
    }
