"""Reader endpoints: chapter list and chapter text (AC-109 area, M1)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.book import Chapter
from app.services import library_service

router = APIRouter(prefix="/api/books/{book_id}/chapters", tags=["reader"])


class ChapterOut(BaseModel):
    index: int
    title: str
    char_count: int


class ChapterTextOut(BaseModel):
    index: int
    title: str
    text: str


def _require_chapters(session: Session, book_id: int) -> List[Chapter]:
    if library_service.get_book(session, book_id) is None:
        raise HTTPException(status_code=404, detail=f"book {book_id} not found")
    return list(
        session.exec(
            select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.index)
        ).all()
    )


@router.get("", response_model=List[ChapterOut])
def list_chapters(book_id: int, session: Session = Depends(get_session)):
    return [
        ChapterOut(index=c.index, title=c.title, char_count=len(c.text))
        for c in _require_chapters(session, book_id)
    ]


@router.get("/{chapter_index}", response_model=ChapterTextOut)
def get_chapter(book_id: int, chapter_index: int, session: Session = Depends(get_session)):
    for chapter in _require_chapters(session, book_id):
        if chapter.index == chapter_index:
            return ChapterTextOut(
                index=chapter.index, title=chapter.title, text=chapter.text
            )
    raise HTTPException(
        status_code=404,
        detail=f"chapter {chapter_index} not found in book {book_id}",
    )
