"""Initial schema: users, sessions, library_books, study_cards, study_progress, learning_plans, syllabi.

Revision ID: 001
Revises:
Create Date: 2025-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "library_books",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("owner_type", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=True),
        sa.Column("book_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("display_title", sa.String(512), nullable=True),
        sa.Column("origin", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), server_default="ready"),
        sa.Column("chunk_count", sa.Integer, server_default="0"),
        sa.Column("supersedes", sa.JSON, nullable=True),
        sa.Column("superseded_by", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "study_cards",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_row_id", sa.Integer, sa.ForeignKey("library_books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("card_id", sa.String(64), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("chunk_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "study_progress",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("card_id", sa.String(64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ease", sa.Float, server_default="2.5"),
        sa.Column("interval_days", sa.Float, server_default="0"),
        sa.Column("reviews", sa.Integer, server_default="0"),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("avg_grade", sa.Float, nullable=True),
    )
    op.create_table(
        "learning_plans",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.String(64), nullable=False),
        sa.Column("path_id", sa.String(128), nullable=False),
        sa.Column("plan_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "syllabi",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ciphertext_object_key", sa.String(512), nullable=False),
        sa.Column("wrapped_udk", sa.LargeBinary, nullable=False),
        sa.Column("kdf_params", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("syllabi")
    op.drop_table("learning_plans")
    op.drop_table("study_progress")
    op.drop_table("study_cards")
    op.drop_table("library_books")
    op.drop_table("sessions")
    op.drop_table("users")
