"""Library business logic: import, list, delete, progress (ARCHITECTURE_v1 §2.1)."""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import Settings
from app.models.book import Book, Chapter, Progress
from app.services.epub_parser import parse_epub


def import_epub(session: Session, settings: Settings, filename: str, data: bytes) -> Book:
    """Persist an EPUB and index its metadata + chapters (AC-001)."""
    settings.ensure_dirs()
    safe_suffix = Path(filename).suffix or ".epub"
    stored_name = f"{uuid.uuid4().hex}{safe_suffix}"
    epub_path = settings.epubs_dir / stored_name
    epub_path.write_bytes(data)

    parsed = parse_epub(epub_path)

    cover_path = None
    if parsed.cover:
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif"}.get(
            parsed.cover_media_type or "", ".img"
        )
        cover_file = settings.covers_dir / f"{stored_name}{ext}"
        cover_file.write_bytes(parsed.cover)
        cover_path = str(cover_file)

    book = Book(
        title=parsed.title,
        author=parsed.author,
        language=parsed.language,
        epub_path=str(epub_path),
        cover_path=cover_path,
    )
    session.add(book)
    session.flush()  # need book.id for the chapters
    for index, chapter in enumerate(parsed.chapters):
        session.add(
            Chapter(
                book_id=book.id,
                index=index,
                title=chapter.title,
                href=chapter.href,
                text=chapter.text,
            )
        )
    session.commit()
    session.refresh(book)
    return book


def list_books(session: Session) -> list[Book]:
    return list(session.exec(select(Book)).all())


def get_book(session: Session, book_id: int) -> Book | None:
    return session.get(Book, book_id)


def delete_book(session: Session, settings: Settings, book_id: int) -> bool:
    """Remove a book, its chapters, progress, and stored files."""
    book = session.get(Book, book_id)
    if book is None:
        return False
    for chapter in session.exec(select(Chapter).where(Chapter.book_id == book_id)):
        session.delete(chapter)
    progress = session.get(Progress, book_id)
    if progress:
        session.delete(progress)
    session.delete(book)
    session.commit()
    for path in (book.epub_path, book.cover_path):
        if path:
            try:
                Path(path).unlink()
            except OSError:
                pass
    return True


def get_progress(session: Session, book_id: int) -> Progress:
    """Progress row, created on first access (AC-003)."""
    progress = session.get(Progress, book_id)
    if progress is None:
        progress = Progress(book_id=book_id)
        session.add(progress)
        session.commit()
        session.refresh(progress)
    return progress


def set_progress(session: Session, book_id: int, chapter_index: int, position: float) -> Progress:
    progress = session.get(Progress, book_id)
    if progress is None:
        progress = Progress(book_id=book_id)
        session.add(progress)
    progress.chapter_index = chapter_index
    progress.position = position
    session.add(progress)
    session.commit()
    session.refresh(progress)
    return progress
