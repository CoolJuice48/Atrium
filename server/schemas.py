"""Pydantic request/response schemas for the Atrium API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---- Auth ----

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str


# ---- Syllabus (zero-knowledge) ----

class SyllabusUploadResponse(BaseModel):
    syllabus_id: str


class PlanGenerateRequest(BaseModel):
    syllabus_id: str
    path_id: str
    features: Dict[str, Any] = Field(default_factory=dict)


class PlanGenerateResponse(BaseModel):
    plan_id: str
    summary: Dict[str, Any]
    plan_json: Optional[Dict[str, Any]] = None


# ---- Query ----

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    book: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=50)
    save_last_answer: bool = True


class QueryResponse(BaseModel):
    question: str
    answer: str
    key_points: List[str]
    citations: List[str]
    confidence: Dict[str, Any]
    retrieved_chunks: List[Dict[str, Any]]
    meta: Optional[Dict[str, Any]] = None


# ---- Catalog ----

class BookInfo(BaseModel):
    name: str
    chunk_count: int


class CatalogResponse(BaseModel):
    books: List[BookInfo]
    total_chunks: int


# ---- Study Plan ----

class StudyPlanRequest(BaseModel):
    minutes: int = Field(default=30, ge=1, le=240)
    book: Optional[str] = None


class StudyPlanResponse(BaseModel):
    total_minutes: int
    review: Dict[str, Any]
    boost: Dict[str, Any]
    quiz: Dict[str, Any]
    gap_boost: Dict[str, Any]
    mastery_snapshot: Dict[str, Any]
    gap_snapshot: List[Any]


# ---- Due Cards ----

class CardSummary(BaseModel):
    card_id: str
    prompt: str
    answer: str
    card_type: str
    book_name: str
    due_date: str
    tags: List[str]


class DueCardsResponse(BaseModel):
    due_count: int
    cards: List[CardSummary]


# ---- Review ----

class ReviewRequest(BaseModel):
    card_id: str
    user_answer: str = Field(..., max_length=5000)


class ReviewResponse(BaseModel):
    score: int
    feedback: str
    new_schedule: Dict[str, Any]


# ---- Cards from last answer ----

class CardsFromLastAnswerRequest(BaseModel):
    max_cards: int = Field(default=6, ge=1, le=12)


class CardsFromLastAnswerResponse(BaseModel):
    cards_generated: int
    cards: List[CardSummary]


# ---- Progress ----

class ProgressResponse(BaseModel):
    overall_mastery: float
    by_book: Dict[str, float]
    weakest_sections: List[Any]
    strongest_sections: List[Any]
    total_cards: int
    due_count: int


# ---- Index status / build ----

class StatusResponse(BaseModel):
    ok: bool
    index_root: str
    pdf_dir: str
    index_exists: bool
    index_ready: bool
    chunk_count: int
    book_counts: List[Dict[str, Any]]
    consistency: Optional[Dict[str, Any]] = None


class IndexBuildRequest(BaseModel):
    pdf_dir: Optional[str] = None
    index_root: Optional[str] = None


class IngestedBook(BaseModel):
    book_id: str
    filename: str
    title: str
    chunk_count: int
    ingest_ms: int
    status: str


class SkippedBook(BaseModel):
    filename: str
    reason: str  # "duplicate_hash" | "already_ready"


class FailedBook(BaseModel):
    filename: str
    error: str


class BuildReport(BaseModel):
    elapsed_ms: int
    ingested: List[Dict[str, Any]]
    skipped: List[Dict[str, Any]]
    failed: List[Dict[str, Any]]
    rebuilt_search_index: bool
    avg_ingest_ms: int = 0


class IndexBuildResponse(BaseModel):
    ok: bool
    index_root: str
    built: bool
    report: Dict[str, Any]
    stats: Dict[str, Any]
    timings: Optional[Dict[str, Any]] = None


# ---- Outline & Scoped Summary ----

class OutlineItemSchema(BaseModel):
    id: str
    title: str
    level: int
    start_page: int
    end_page: int
    parent_id: Optional[str] = None


class OutlineResponse(BaseModel):
    outline_id: str
    items: List[OutlineItemSchema]


class SummaryScopeRequest(BaseModel):
    outline_id: str
    scope: Dict[str, Any] = Field(default_factory=dict)  # { item_ids: [...] }
    options: Optional[Dict[str, Any]] = None  # { bullets_target, max_pages }


class ScopedSummaryResponse(BaseModel):
    summary_markdown: str
    bullets: List[str]
    citations: List[str]
    key_terms: List[str]


# ---- Study Artifacts (per-book) ----

class BookStudyInfo(BaseModel):
    card_count: int
    due_count: int
    last_generated_at: Optional[str] = None
    avg_grade: Optional[float] = None


class BookWithStudy(BaseModel):
    book_id: str
    title: str
    chunk_count: int
    study: BookStudyInfo


class BooksResponse(BaseModel):
    books: List[BookWithStudy]


class StudyGenerateRequest(BaseModel):
    max_cards: int = Field(default=20, ge=1, le=100)
    strategy: str = Field(default="coverage", pattern="^(simple|coverage)$")


class StudyGenerateResponse(BaseModel):
    generated_count: int
    skipped_count: int
    elapsed_ms: int


class StudyDueCard(BaseModel):
    card_id: str
    question: str
    answer: str
    source: Dict[str, Any]


class StudyDueResponse(BaseModel):
    cards: List[StudyDueCard]


class StudyReviewRequest(BaseModel):
    card_id: str
    grade: int = Field(..., ge=0, le=5)


class StudyReviewResponse(BaseModel):
    ease: float
    interval_days: float
    due_at: str
    last_reviewed_at: Optional[str] = None


class ExamGenerateRequest(BaseModel):
    exam_size: int = Field(default=20, ge=5, le=50)
    blueprint: Optional[Dict[str, int]] = None
    seed: Optional[int] = None


class ExamQuestion(BaseModel):
    card_id: str
    prompt: str
    answer: str
    card_type: str
    book_name: str
    tags: List[str] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class ExamGenerateResponse(BaseModel):
    ok: bool = True
    book_id: str
    title: str
    exam: Dict[str, Any]  # {questions: [...]}
    meta: Dict[str, Any]  # counts_by_type, total, etc.


# ---- Index repair ----

class IndexRepairRequest(BaseModel):
    index_root: Optional[str] = None
    mode: str = Field(default="repair", pattern="^(verify|repair)$")
    rebuild_search_index: Optional[bool] = None  # default true if repairs occurred
    prune_tmp: bool = True


class IndexRepairResponse(BaseModel):
    ok: bool
    index_root: str
    report: Dict[str, Any]
    stats: Dict[str, Any]


# ---- Eval ----

class EvalRequest(BaseModel):
    golden_set: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)


class EvalResponse(BaseModel):
    summary: Dict[str, Any]
    per_question: List[Dict[str, Any]]
