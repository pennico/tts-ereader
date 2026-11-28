"""Library endpoints: import, list, get, delete, progress (AC-001..AC-005)."""
from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models.book import Book, Chapter, Progress
from app.services import library_service

router = APIRouter(prefix="/api/books", tags=["library"])


class BookOut(BaseModel):
    id: int
    title: str
    author: str
    language: str
    cover_path: str | None = None
    chapter_count: int = 0
    progress_chapter: int = 0
    progress_position: float = 0.0


class ProgressIn(BaseModel):
    chapter_index: int = Field(ge=0)
    position: float = Field(ge=0.0, le=1.0)


def _book_out(session: Session, book: Book) -> BookOut:
    progress = session.get(Progress, book.id)
    chapter_count = len(
        list(session.exec(select(Chapter).where(Chapter.book_id == book.id)).all())
    )
    return BookOut(
        id=book.id,
        title=book.title,
        author=book.author,
        language=book.language,
        cover_path=book.cover_path,
        chapter_count=chapter_count,
        progress_chapter=progress.chapter_index if progress else 0,
        progress_position=progress.position if progress else 0.0,
    )


def _require_book(session: Session, book_id: int) -> Book:
    book = library_service.get_book(session, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"book {book_id} not found")
    return book


@router.post("", response_model=BookOut)
def import_book(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Import an EPUB into the library (AC-001)."""
    data = file.file.read()
    try:
        book = library_service.import_epub(session, settings, file.filename or "book.epub", data)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="not a valid EPUB (not a zip file)")
    return _book_out(session, book)


@router.get("", response_model=list[BookOut])
def list_books(session: Session = Depends(get_session)):
    return [_book_out(session, book) for book in library_service.list_books(session)]


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int, session: Session = Depends(get_session)):
    return _book_out(session, _require_book(session, book_id))


@router.delete("/{book_id}")
def delete_book(
    book_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    if not library_service.delete_book(session, settings, book_id):
        raise HTTPException(status_code=404, detail=f"book {book_id} not found")
    return {"ok": True}


@router.get("/{book_id}/cover")
def get_cover(
    book_id: int,
    session: Session = Depends(get_session),
):
    """Serve the stored cover image (AC-002)."""
    book = _require_book(session, book_id)
    if not book.cover_path:
        raise HTTPException(status_code=404, detail=f"book {book_id} has no cover")
    path = Path(book.cover_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"cover file missing for book {book_id}")
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".img": "application/octet-stream",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.get("/{book_id}/progress", response_model=ProgressIn)
def get_progress(book_id: int, session: Session = Depends(get_session)):
    _require_book(session, book_id)
    progress = library_service.get_progress(session, book_id)
    return ProgressIn(chapter_index=progress.chapter_index, position=progress.position)


@router.put("/{book_id}/progress", response_model=ProgressIn)
def set_progress(
    book_id: int,
    body: ProgressIn,
    session: Session = Depends(get_session),
):
    _require_book(session, book_id)
    progress = library_service.set_progress(
        session, book_id, body.chapter_index, body.position
    )
    return ProgressIn(chapter_index=progress.chapter_index, position=progress.position)
