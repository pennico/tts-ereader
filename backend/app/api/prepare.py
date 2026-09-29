"""Chapter preparation endpoints: LLM speaker tagging + voice cast (AC-305,
AC-401, AC-403, AC-405..AC-407).

POST /api/books/{id}/chapters/{n}/prepare runs the shared Mistral preparation
pipeline on the chapter (cached on disk per book+chapter), tags each line with
a cast role, and resolves roles to concrete voices via the per-book cast
overrides. GET .../prepared returns the cached preparation without calling
the LLM (404 when the chapter was never prepared).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

try:  # pragma: no cover - import bootstrap for non-repo-root working dirs
    from shared import voice_cast
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from shared import voice_cast

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models.book import Book, Chapter
from app.services import llm_service

router = APIRouter(prefix="/api/books/{book_id}/chapters", tags=["prepare"])


class PrepareIn(BaseModel):
    engine: Optional[str] = None
    # role -> voice id overrides on top of the engine's default cast (AC-305)
    cast: Optional[Dict[str, str]] = None
    force: bool = False  # re-run the LLM even if a cached preparation exists


class PreparedSegmentOut(BaseModel):
    index: int
    text: str
    speaker: Optional[str] = None
    gender: Optional[str] = None
    role: str
    voice: str


class PreparedOut(BaseModel):
    chapter_index: int
    language: str
    cached: bool
    segments: List[PreparedSegmentOut]


def _chapter_text(session: Session, book_id: int, chapter_index: int):
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"book {book_id} not found")
    chapter = session.exec(
        select(Chapter).where(Chapter.book_id == book_id, Chapter.index == chapter_index)
    ).first()
    if chapter is None:
        raise HTTPException(
            status_code=404,
            detail=f"chapter {chapter_index} not found in book {book_id}",
        )
    return book, chapter


def _resolve_cast(engine: Optional[str], language: str, overrides: Optional[Dict[str, str]]):
    """Default cast for the engine+language, with per-book overrides applied."""
    defaults = voice_cast.default_cast(engine or "gemini", language)
    cast = {role: voice for role, (voice, _name) in defaults.items()}
    for role, voice in (overrides or {}).items():
        if role in voice_cast.ROLES and voice:
            cast[role] = voice
    return cast


def _segments_out(chapter_index: int, language: str, cached: bool, data: dict, cast: dict):
    tagged = voice_cast.assign_roles(
        [(speaker, gender, text) for speaker, gender, text in data["lines"]]
    )
    segments = []
    for i, (speaker, gender, text, role) in enumerate(tagged):
        segments.append(
            PreparedSegmentOut(
                index=i,
                text=text,
                speaker=speaker,
                gender=gender,
                role=role,
                voice=cast.get(role, cast.get("narrator", "")),
            )
        )
    return PreparedOut(
        chapter_index=chapter_index, language=language, cached=cached, segments=segments
    )


@router.post("/{chapter_index}/prepare", response_model=PreparedOut)
def prepare_chapter(
    book_id: int,
    chapter_index: int,
    body: PrepareIn,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Prepare a chapter with the LLM and return cast-resolved segments."""
    book, chapter = _chapter_text(session, book_id, chapter_index)
    language = book.language or llm_service.detect_language(chapter.text)
    data = None if body.force else llm_service.load_prepared(
        settings, book_id, chapter_index
    )
    cached = data is not None
    if data is None:
        try:
            prepared = llm_service.prepare_text(chapter.text, language=language)
        except llm_service.LLMUnavailableError as e:
            raise HTTPException(status_code=503, detail=str(e))
        data = llm_service.save_prepared(
            settings, book_id, chapter_index, language, prepared
        )
    cast = _resolve_cast(body.engine, language, body.cast)
    return _segments_out(chapter_index, language, cached, data, cast)


@router.get("/{chapter_index}/prepared", response_model=PreparedOut)
def get_prepared_chapter(
    book_id: int,
    chapter_index: int,
    engine: Optional[str] = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Cached preparation only (never calls the LLM); 404 if not prepared."""
    book, _chapter = _chapter_text(session, book_id, chapter_index)
    data = llm_service.load_prepared(settings, book_id, chapter_index)
    if data is None:
        raise HTTPException(
            status_code=404, detail=f"chapter {chapter_index} is not prepared yet"
        )
    language = data.get("language") or book.language or "en"
    cast = _resolve_cast(engine, language, None)
    return _segments_out(chapter_index, language, True, data, cast)
