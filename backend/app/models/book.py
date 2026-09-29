"""Book, Chapter, and Progress models (ARCHITECTURE_v1 §2.1)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    # Timezone-aware: SQLModel's datetime columns are DateTime(timezone=True),
    # and SQLAlchemy >= 2.0.36 rejects naive datetimes for those.
    return datetime.now(timezone.utc)


class Book(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    author: str = "Unknown author"
    language: str = ""
    epub_path: str
    cover_path: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class Chapter(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(foreign_key="book.id", index=True)
    index: int
    title: str
    href: str
    text: str


class Progress(SQLModel, table=True):
    """One row per book: where the reader left off (AC-003)."""

    book_id: int = Field(primary_key=True, foreign_key="book.id")
    chapter_index: int = 0
    position: float = 0.0  # fraction within the chapter (0.0 - 1.0)
    updated_at: datetime = Field(default_factory=utcnow)
