"""Pydantic request/response schemas for the Atrium API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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


# ---- Eval ----

class EvalRequest(BaseModel):
    golden_set: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)


class EvalResponse(BaseModel):
    summary: Dict[str, Any]
    per_question: List[Dict[str, Any]]
