"""SQLAlchemy models for auth and multi-tenant data."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LibraryBook(Base):
    __tablename__ = "library_books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "global" | "user"
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # null for global
    book_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    display_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    supersedes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    superseded_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class StudyCard(Base):
    __tablename__ = "study_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    book_row_id: Mapped[int] = mapped_column(Integer, ForeignKey("library_books.id", ondelete="CASCADE"), nullable=False)
    card_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class StudyProgress(Base):
    __tablename__ = "study_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    card_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ease: Mapped[float] = mapped_column(default=2.5)
    interval_days: Mapped[float] = mapped_column(default=0.0)
    reviews: Mapped[int] = mapped_column(Integer, default=0)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    avg_grade: Mapped[float | None] = mapped_column(nullable=True)


class LearningPlan(Base):
    __tablename__ = "learning_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    path_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Syllabus(Base):
    """Zero-knowledge: server stores only ciphertext, cannot decrypt."""

    __tablename__ = "syllabi"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    ciphertext_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    wrapped_udk: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kdf_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
