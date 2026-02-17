"""FastAPI application -- routes for the Atrium learning platform."""

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import asyncio
import json as _json
from fastapi import BackgroundTasks, Cookie, Depends, File, Form, FastAPI, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from server.config import Settings
from server.dependencies import get_card_store, get_graph, get_runtime, get_settings
from server.schemas import (
    BooksResponse,
    OutlineResponse,
    OutlineItemSchema,
    ScopedSummaryResponse,
    SummaryScopeRequest,
    LoginRequest,
    PlanGenerateRequest,
    PlanGenerateResponse,
    RegisterRequest,
    SyllabusUploadResponse,
    UserResponse,
    CardsFromLastAnswerRequest,
    CardsFromLastAnswerResponse,
    CatalogResponse,
    DueCardsResponse,
    EvalRequest,
    EvalResponse,
    IndexBuildRequest,
    IndexBuildResponse,
    IndexRepairRequest,
    IndexRepairResponse,
    ProgressResponse,
    QueryRequest,
    QueryResponse,
    ReviewRequest,
    ReviewResponse,
    StatusResponse,
    StudyDueResponse,
    StudyGenerateRequest,
    StudyGenerateResponse,
    StudyPlanRequest,
    StudyPlanResponse,
    StudyReviewRequest,
    StudyReviewResponse,
    ExamGenerateRequest,
    ExamGenerateResponse,
)
from server.services import (
    auth_service,
    eval_service,
    index_service,
    library_service,
    plan_service,
    query_service,
    study_service,
    study_artifacts_service,
    syllabus_service,
)
from server.services.query_service import LibraryUnavailableError
from server.__version__ import __version__
from server.auth import get_current_user
from study.storage import CardStore

logger = logging.getLogger("atrium")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan: init DB, no heavy work. Runtime/index built lazily on first request."""
    from server.db.session import init_db
    init_db(Settings())
    ts = datetime.utcnow().isoformat() + "Z"
    logger.info("[%s] Startup: begin (no index/engine load)", ts)
    print(f"[{ts}] Startup: begin (no index/engine load)")
    yield
    ts_end = datetime.utcnow().isoformat() + "Z"
    logger.info("[%s] Shutdown: complete", ts_end)
    print(f"[{ts_end}] Shutdown: complete")


app = FastAPI(title="Atrium", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Auth ----

SESSION_COOKIE = "atrium_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


@app.post("/auth/register", response_model=UserResponse)
def auth_register(body: RegisterRequest, response: Response, settings: Settings = Depends(get_settings)):
    from server.db.session import get_session_factory
    factory = get_session_factory(settings)
    db = factory()
    try:
        try:
            user = auth_service.register_user(db, body.email, body.password)
            token = auth_service.create_session(db, user.id)
            db.commit()
        except ValueError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=False,
            samesite="lax",
        )
        return {"id": user.id, "email": user.email}
    finally:
        db.close()


@app.post("/auth/login", response_model=UserResponse)
def auth_login(body: LoginRequest, response: Response, settings: Settings = Depends(get_settings)):
    from server.db.models import User
    from server.db.session import get_session_factory
    factory = get_session_factory(settings)
    db = factory()
    try:
        user = db.query(User).filter(User.email == body.email.lower().strip()).first()
        if not user or not auth_service.verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = auth_service.create_session(db, user.id)
        db.commit()
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=False,
            samesite="lax",
        )
        return {"id": user.id, "email": user.email}
    finally:
        db.close()


@app.post("/auth/logout")
def auth_logout(
    response: Response,
    atrium_session: str | None = Cookie(None, alias=SESSION_COOKIE),
    settings: Settings = Depends(get_settings),
):
    if atrium_session:
        from server.db.session import get_session_factory
        factory = get_session_factory(settings)
        db = factory()
        try:
            auth_service.logout_session(db, atrium_session)
            db.commit()
        finally:
            db.close()
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/auth/me", response_model=UserResponse)
def auth_me(user=Depends(get_current_user)):
    return {"id": user.id, "email": user.email}


# ---- Health (no dependencies, always fast) ----

@app.get("/health")
def health():
    """Minimal health check. No deps, no index load. Always returns immediately."""
    return {"ok": True}


# ---- Status (cheap: no full index load) ----

@app.get("/status", response_model=StatusResponse)
def status(settings: Settings = Depends(get_settings)):
    """Index status for first-run UX. Does not load full index."""
    return index_service.get_index_status(
        settings.index_root,
        settings.pdf_dir,
    )


# ---- Index build / clear ----

@app.post("/index/build", response_model=IndexBuildResponse)
def index_build(
    body: IndexBuildRequest,
    settings: Settings = Depends(get_settings),
):
    """Build index from PDFs. Synchronous. Invalidates cached searcher on success."""
    pdf_dir = Path(body.pdf_dir) if body.pdf_dir else settings.pdf_dir
    index_root = Path(body.index_root) if body.index_root else settings.index_root

    try:
        result = index_service.build_index_from_pdfs(pdf_dir, index_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    report = result.get("report", {})
    rebuilt = result.get("rebuilt_search_index", False)
    any_changed = result.get("any_status_changed", False)

    if rebuilt or any_changed:
        query_service.invalidate_searcher_cache(str(index_root))
        from server.library import invalidate_verify_cache
        invalidate_verify_cache(index_root)

    return {
        "ok": True,
        "index_root": str(index_root),
        "built": True,
        "report": report,
        "stats": result.get("stats", {}),
        "timings": {
            "elapsed_ms": report.get("elapsed_ms", 0),
            "avg_ingest_ms": report.get("avg_ingest_ms", 0),
        },
    }


@app.post("/index/repair", response_model=IndexRepairResponse)
def index_repair(
    body: IndexRepairRequest,
    settings: Settings = Depends(get_settings),
):
    """Repair library metadata from disk. Rebuild library.json, prune .tmp, optionally rebuild search index."""
    index_root = Path(body.index_root) if body.index_root else settings.index_root
    pdf_dir = settings.pdf_dir

    result = index_service.repair_library(
        index_root,
        pdf_dir=pdf_dir,
        mode=body.mode,
        rebuild_search_index=body.rebuild_search_index,
        prune_tmp=body.prune_tmp,
    )

    report = result.get("report", {})
    library_changed = result.get("library_json_changed", False)
    rebuilt = result.get("rebuilt_search_index", False)

    if library_changed or rebuilt:
        query_service.invalidate_searcher_cache(str(index_root))
        from server.library import invalidate_verify_cache
        invalidate_verify_cache(index_root)

    return {
        "ok": True,
        "index_root": str(index_root),
        "report": report,
        "stats": result.get("stats", {}),
    }


@app.post("/index/clear")
def index_clear(settings: Settings = Depends(get_settings)):
    """Delete index artifacts (dev only). Guarded to repo root."""
    project_root = Path(__file__).resolve().parent.parent
    try:
        index_service.clear_index(settings.index_root, project_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    from server.library import invalidate_verify_cache
    invalidate_verify_cache(settings.index_root)
    return {"ok": True}


# ---- Books & Study Artifacts (per-book) ----

@app.get("/books", response_model=BooksResponse)
def get_books(
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """List ready books: union of global (index) + user-owned (DB)."""
    from server.db.session import get_session_factory
    factory = get_session_factory(settings)
    db = factory()
    try:
        books = library_service.get_books_union(
            settings.index_root, db, user.id,
        )
        return {"books": books}
    finally:
        db.close()


@app.get("/books/global", response_model=BooksResponse)
def get_books_global(settings: Settings = Depends(get_settings)):
    """List global (shared) books from index. No auth required."""
    books = library_service.get_global_books_from_index(settings.index_root)
    return {"books": books}


@app.get("/books/mine", response_model=BooksResponse)
def get_books_mine(
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """List user-owned books from DB."""
    from server.db.session import get_session_factory
    factory = get_session_factory(settings)
    db = factory()
    try:
        books = library_service.get_user_books_from_db(db, user.id)
        return {"books": books}
    finally:
        db.close()


@app.post("/books/{book_id}/study/generate", response_model=StudyGenerateResponse)
def study_generate(
    book_id: str,
    body: StudyGenerateRequest,
    settings: Settings = Depends(get_settings),
):
    """Generate new cards for a book. Heuristic generator (no LLM)."""
    try:
        result = study_artifacts_service.generate_cards(
            settings.index_root,
            book_id,
            max_cards=body.max_cards,
            strategy=body.strategy,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/books/{book_id}/study/due", response_model=StudyDueResponse)
def study_due(
    book_id: str,
    limit: int = 20,
    settings: Settings = Depends(get_settings),
):
    """Get due cards for a book."""
    try:
        cards = study_artifacts_service.get_due_cards(
            settings.index_root,
            book_id,
            limit=limit,
        )
        return {"cards": cards}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/books/{book_id}/study/review", response_model=StudyReviewResponse)
def study_review(
    book_id: str,
    body: StudyReviewRequest,
    settings: Settings = Depends(get_settings),
):
    """Submit review (grade 0-5) for a card. Updates SM-2 scheduling."""
    try:
        result = study_artifacts_service.review_card(
            settings.index_root,
            book_id,
            body.card_id,
            body.grade,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/books/{book_id}/study/exam/generate", response_model=ExamGenerateResponse)
def study_exam_generate(
    book_id: str,
    body: ExamGenerateRequest,
    settings: Settings = Depends(get_settings),
):
    """Generate a practice exam from chunks. Ephemeral (not persisted)."""
    from server.services.study_artifacts_service import NoTextExtractedError

    try:
        result = study_artifacts_service.generate_exam(
            settings.index_root,
            book_id,
            exam_size=body.exam_size,
            blueprint=body.blueprint,
            seed=body.seed,
        )
        return result
    except NoTextExtractedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---- Syllabus (zero-knowledge) ----

@app.post("/syllabus/upload", response_model=SyllabusUploadResponse)
def syllabus_upload(
    file: UploadFile = File(...),
    filename: str = Form(...),
    mime: str = Form(...),
    size_bytes: int = Form(...),
    wrapped_udk: str = Form(...),
    kdf_params: str = Form("{}"),
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Store encrypted syllabus. Server never sees plaintext."""
    import base64
    import json
    from server.db.session import get_session_factory
    ciphertext = file.file.read()
    try:
        udk_bytes = base64.b64decode(wrapped_udk)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid wrapped_udk encoding")
    try:
        kdf = json.loads(kdf_params) if kdf_params else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid kdf_params JSON")
    factory = get_session_factory(settings)
    db = factory()
    try:
        syllabus_id = syllabus_service.store_syllabus(
            db, user.id, filename, mime, size_bytes,
            ciphertext, udk_bytes, kdf,
            settings.syllabus_storage_path,
        )
        db.commit()
        return {"syllabus_id": syllabus_id}
    finally:
        db.close()


@app.post("/plan/generate_from_features", response_model=PlanGenerateResponse)
def plan_generate_from_features(
    body: PlanGenerateRequest,
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Generate learning plan from syllabus features. No syllabus content accessed."""
    from server.db.session import get_session_factory
    factory = get_session_factory(settings)
    db = factory()
    try:
        meta = syllabus_service.get_syllabus_meta(db, body.syllabus_id, user.id)
        if not meta:
            raise HTTPException(status_code=404, detail="Syllabus not found")
        result = plan_service.generate_plan_from_features(
            db, user.id, body.syllabus_id, body.path_id, body.features,
        )
        db.commit()
        return {
            "plan_id": result["plan_id"],
            "summary": result["summary"],
            "plan_json": result.get("plan_json"),
        }
    finally:
        db.close()


# ---- Packs catalog ----

@app.get("/packs/catalog")
def packs_catalog(settings: Settings = Depends(get_settings)):
    """Serve catalog.json from packs dist."""
    catalog_path = settings.packs_dist_path / "catalog.json"
    if not catalog_path.exists():
        return []
    with open(catalog_path, "r") as f:
        return _json.load(f)


# ---- Packs install (job + stream + cancel) ----

@app.post("/packs/install")
def packs_install_start(
    body: dict,
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Start pack install job. Returns job_id."""
    from server.services import pack_install_service as pis
    pack_id = body.get("pack_id") or ""
    pack_title = body.get("pack_title") or pack_id
    download_url = body.get("download_url") or ""
    if not pack_id or not download_url:
        raise HTTPException(status_code=400, detail="pack_id and download_url required")
    job = pis.create_job(pack_id, pack_title)

    async def run_in_bg():
        await asyncio.to_thread(
            pis.run_install_job,
            job.job_id,
            download_url,
            settings.packs_dist_path,
            settings.index_root,
        )

    asyncio.create_task(run_in_bg())
    return {"job_id": job.job_id}


@app.get("/packs/install/{job_id}")
def packs_install_status(job_id: str):
    """Get install job status (for polling)."""
    from server.services import pack_install_service as pis
    job = pis.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "pack_id": job.pack_id,
        "pack_title": job.pack_title,
        "status": job.status,
        "phase": job.phase,
        "message": job.message,
        "current": job.current,
        "total": job.total,
        "error": job.error,
        "result": job.result,
    }


@app.get("/packs/install/{job_id}/stream")
def packs_install_stream(job_id: str):
    """SSE stream of install progress."""
    from server.services import pack_install_service as pis

    async def event_generator():
        import asyncio
        job = pis.get_job(job_id)
        if not job:
            yield f"data: {_json.dumps({'error': 'Job not found'})}\n\n"
            return
        last = None
        while True:
            job = pis.get_job(job_id)
            if not job:
                break
            state = {
                "status": job.status,
                "phase": job.phase,
                "message": job.message,
                "current": job.current,
                "total": job.total,
                "error": job.error,
                "result": job.result,
            }
            key = (state["status"], state["phase"], state["message"], state["current"], state["total"])
            if key != last:
                last = key
                yield f"data: {_json.dumps(state)}\n\n"
            if job.status in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/packs/install/{job_id}/cancel")
def packs_install_cancel(job_id: str):
    """Cancel install job."""
    from server.services import pack_install_service as pis
    ok = pis.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job not found or already finished")
    return {"ok": True}


# ---- User PDF upload (job + SSE + cancel) ----

ALLOWED_PDF_MIMES = {"application/pdf", "application/x-pdf"}


@app.post("/uploads/pdf")
def uploads_pdf_start(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    display_title: str = Form(None),
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    max_bytes = int(settings.max_upload_size_mb * 1024 * 1024)
    """Start PDF upload + ingest job. Returns job_id."""
    from server.services import upload_job_service as ujs

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF file required")

    # Mime check
    content_type = (file.content_type or "").lower().strip()
    if content_type and content_type not in ALLOWED_PDF_MIMES and "pdf" not in content_type:
        raise HTTPException(status_code=400, detail="File must be PDF (application/pdf)")

    # Rate limit
    err = ujs._check_rate_limit(user.id, settings.upload_rate_limit_per_user)
    if err:
        raise HTTPException(status_code=429, detail=err)

    # Read and size check (streaming)
    content = file.file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max {settings.max_upload_size_mb:.0f}MB.",
        )

    job = ujs.create_job(user.id, file.filename, display_title or Path(file.filename).stem)

    # Save to user-owned storage
    user_dir = settings.uploads_root / "users" / user.id
    user_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = user_dir / f"{job.job_id}.pdf"
    pdf_path.write_bytes(content)

    user_id = user.id
    display_title_val = job.display_title

    def run_in_bg():
        ujs.run_upload_job(
            job.job_id,
            pdf_path,
            settings.index_root,
            settings.uploads_root,
            display_title_val,
            user_id,
        )

    background_tasks.add_task(run_in_bg)
    return {"job_id": job.job_id}


@app.get("/uploads/{job_id}")
def uploads_status(job_id: str):
    """Get upload job status (for polling)."""
    from server.services import upload_job_service as ujs
    job = ujs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.job_id,
        "filename": job.filename,
        "status": job.status,
        "phase": job.phase,
        "message": job.message,
        "progress": {"current": job.current, "total": job.total},
        "error": job.error,
        "result": job.result,
    }


@app.get("/uploads/{job_id}/stream")
def uploads_stream(job_id: str):
    """SSE stream of upload progress."""
    from server.services import upload_job_service as ujs

    async def event_generator():
        job = ujs.get_job(job_id)
        if not job:
            yield f"data: {_json.dumps({'error': 'Job not found'})}\n\n"
            return
        last = None
        while True:
            job = ujs.get_job(job_id)
            if not job:
                break
            state = {
                "status": job.status,
                "phase": job.phase,
                "message": job.message,
                "progress": {"current": job.current, "total": job.total},
                "error": job.error,
                "result": job.result,
            }
            key = (state["status"], state["phase"], state["message"], job.current, job.total)
            if key != last:
                last = key
                yield f"data: {_json.dumps(state)}\n\n"
            if job.status in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/uploads/{job_id}/cancel")
def uploads_cancel(job_id: str):
    """Cancel upload job."""
    from server.services import upload_job_service as ujs
    ok = ujs.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Job not found or already finished")
    return {"ok": True}


# ---- Books metadata (user-owned) ----

@app.patch("/books/{book_id}/metadata")
def books_patch_metadata(
    book_id: str,
    body: dict,
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Update metadata for user-owned book."""
    display_title = body.get("display_title")
    subject_tags = body.get("subject_tags")
    course_tags = body.get("course_tags")
    if not any([display_title is not None, subject_tags is not None, course_tags is not None]):
        raise HTTPException(status_code=400, detail="At least one field required")
    ok = library_service.update_user_book_metadata(
        settings.index_root,
        user.id,
        book_id,
        display_title=display_title,
        subject_tags=subject_tags,
        course_tags=course_tags,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Book not found or not owned by you")
    return {"ok": True}


# ---- Outline & Scoped Summary ----

@app.get("/books/{book_id}/outline", response_model=OutlineResponse)
def books_get_outline(
    book_id: str,
    settings: Settings = Depends(get_settings),
):
    """Get hierarchical outline for scope selection. Builds from chunks if not cached."""
    from server.outline import get_or_build_outline
    from server.library import load_library, verify_library_cached

    index_root = Path(settings.index_root).resolve()
    book_dir = index_root / "books" / book_id
    if not book_dir.exists():
        raise HTTPException(status_code=404, detail="Book not found")

    lib = load_library(index_root)
    if lib:
        _, _, valid_ids = verify_library_cached(index_root, lib)
        if book_id not in valid_ids:
            raise HTTPException(status_code=404, detail="Book not found or not ready")

    try:
        outline_id, items = get_or_build_outline(book_dir)
        return {
            "outline_id": outline_id,
            "items": [OutlineItemSchema(**it) for it in items],
        }
    except Exception as e:
        logger.exception("Outline build failed for book %s", book_id)
        raise HTTPException(status_code=500, detail="Could not build outline")


@app.post("/books/{book_id}/summaries", response_model=ScopedSummaryResponse)
def books_post_summaries(
    book_id: str,
    body: SummaryScopeRequest,
    settings: Settings = Depends(get_settings),
):
    """Generate scoped summary for selected chapters/sections."""
    from server.services import summary_service

    index_root = Path(settings.index_root).resolve()
    item_ids = body.scope.get("item_ids") or []
    opts = body.options or {}
    bullets_target = opts.get("bullets_target", 10)
    max_pages = opts.get("max_pages", 80)

    try:
        result = summary_service.generate_scoped_summary(
            index_root,
            book_id,
            body.outline_id,
            item_ids,
            bullets_target=bullets_target,
            max_pages=max_pages,
        )
        return result
    except ValueError as e:
        msg = str(e)
        if "Outline has changed" in msg:
            raise HTTPException(status_code=409, detail=msg)
        if "No sections selected" in msg or "No content found" in msg:
            raise HTTPException(status_code=400, detail=msg)
        if "too large" in msg.lower():
            raise HTTPException(status_code=400, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        logger.exception("Scoped summary failed for book %s", book_id)
        raise HTTPException(status_code=500, detail="Summary generation failed")


# ---- Catalog (lazy: loads index on first request) ----

@app.get("/catalog", response_model=CatalogResponse)
def catalog(settings: Settings = Depends(get_settings)):
    try:
        result = query_service.get_catalog(str(settings.index_root))
        return result
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Index unavailable at {settings.index_root}. "
            f"Build the index first (run_pipeline.py) or check INDEX_ROOT. Error: {e!s}",
        )


# ---- Query (lazy: loads index on first request) ----

@app.post("/query", response_model=QueryResponse)
def query(
    body: QueryRequest,
    settings: Settings = Depends(get_settings),
    runtime=Depends(get_runtime),
):
    try:
        result = query_service.answer_question_offline(
            body.question,
            book=body.book,
            top_k=body.top_k,
            index_root=str(settings.index_root),
            graph_path=settings.graph_registry_path,
            save_last_answer=body.save_last_answer,
            runtime=runtime,
            settings=settings,
        )
    except LibraryUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Index unavailable at {settings.index_root}. "
            f"Build the index first (run_pipeline.py) or check INDEX_ROOT. Error: {e!s}",
        )
    answer_dict = result['answer_dict']
    return {
        'question': result['question'],
        'answer': answer_dict.get('answer', ''),
        'key_points': answer_dict.get('key_points', []),
        'citations': answer_dict.get('citations', []),
        'confidence': answer_dict.get('confidence', {}),
        'retrieved_chunks': result['retrieved_chunks'],
        'meta': result.get('meta'),
    }


# ---- Study Plan ----

@app.post("/study/plan", response_model=StudyPlanResponse)
def study_plan(
    body: StudyPlanRequest,
    settings: Settings = Depends(get_settings),
    store: CardStore = Depends(get_card_store),
    graph=Depends(get_graph),
):
    return study_service.get_study_plan(
        store,
        minutes=body.minutes,
        book=body.book,
        graph_registry_path=settings.graph_registry_path,
        graph=graph,
    )


# ---- Due Cards ----

@app.get("/study/due", response_model=DueCardsResponse)
def due_cards(store: CardStore = Depends(get_card_store)):
    return study_service.get_due_cards(store)


# ---- Review ----

@app.post("/study/review", response_model=ReviewResponse)
def review(body: ReviewRequest, store: CardStore = Depends(get_card_store)):
    try:
        return study_service.review_card(store, body.card_id, body.user_answer)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Card not found: {body.card_id}")


# ---- Cards from last answer ----

@app.post("/cards/from_last_answer", response_model=CardsFromLastAnswerResponse)
def cards_from_last_answer(
    body: CardsFromLastAnswerRequest,
    settings: Settings = Depends(get_settings),
    store: CardStore = Depends(get_card_store),
):
    return study_service.cards_from_last_answer(
        settings.index_root, store, max_cards=body.max_cards,
    )


# ---- Progress ----

@app.get("/progress", response_model=ProgressResponse)
def progress(store: CardStore = Depends(get_card_store)):
    return study_service.get_progress(store)


# ---- Eval ----

@app.post("/eval/run", response_model=EvalResponse)
def eval_run(body: EvalRequest, settings: Settings = Depends(get_settings)):
    golden_path = settings.golden_sets_dir / body.golden_set
    if not golden_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Golden set not found: {body.golden_set}",
        )
    return eval_service.run_evaluation(
        golden_path,
        index_root=str(settings.index_root),
        top_k=body.top_k,
    )
