"""FastAPI application -- routes for the Atrium learning platform."""

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from server.config import Settings
from server.dependencies import get_card_store, get_graph, get_runtime, get_settings
from server.schemas import (
    CardsFromLastAnswerRequest,
    CardsFromLastAnswerResponse,
    CatalogResponse,
    DueCardsResponse,
    EvalRequest,
    EvalResponse,
    ProgressResponse,
    QueryRequest,
    QueryResponse,
    ReviewRequest,
    ReviewResponse,
    StudyPlanRequest,
    StudyPlanResponse,
)
from server.services import eval_service, query_service, study_service
from server.__version__ import __version__
from study.storage import CardStore

logger = logging.getLogger("atrium")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan: no heavy work. Runtime/index built lazily on first request."""
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


# ---- Health (no dependencies, always fast) ----

@app.get("/health")
def health():
    """Minimal health check. No deps, no index load. Always returns immediately."""
    return {"ok": True}


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
        )
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
