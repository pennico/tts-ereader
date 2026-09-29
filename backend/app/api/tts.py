"""TTS endpoints: engines, voices, synthesize, batch (AC-501..AC-508)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.engines import base as engine_base
from app.engines import factory
from app.services import tts_service

router = APIRouter(prefix="/api/tts", tags=["tts"])


class EngineOut(BaseModel):
    name: str
    display_name: str
    available: bool
    is_default: bool


class VoiceOut(BaseModel):
    name: str
    display_name: str
    gender: str
    locale: str


class SynthesizeIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    engine: Optional[str] = None
    voice: str
    rate: float = Field(default=1.0, ge=0.5, le=2.0)  # AC-303
    pitch: float = Field(default=0.0, ge=-20.0, le=20.0)


class WordBoundaryOut(BaseModel):
    word: str
    start_ms: float
    end_ms: float


class SynthesisOut(BaseModel):
    text: str
    engine: str
    cached: bool
    audio_b64: str
    format: str
    sample_rate: int
    duration_ms: float
    word_boundaries: Optional[List[WordBoundaryOut]] = None


class BatchIn(BaseModel):
    texts: List[str] = Field(min_length=1, max_length=64)
    engine: Optional[str] = None
    voice: str
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-20.0, le=20.0)


class BatchOut(BaseModel):
    segments: List[SynthesisOut]


def _synthesis_out(text: str, result: dict) -> SynthesisOut:
    return SynthesisOut(
        text=text,
        engine=result["engine"],
        cached=result["cached"],
        audio_b64=result["audio"],
        format=result["format"],
        sample_rate=result["sample_rate"],
        duration_ms=result["duration_ms"],
        word_boundaries=[
            WordBoundaryOut(**wb) for wb in (result.get("word_boundaries") or [])
        ]
        or None,
    )


@router.get("/engines", response_model=List[EngineOut])
def list_engines(settings: Settings = Depends(get_settings)):
    """Registered engines with availability (drives the UI selector, AC-301)."""
    out = []
    for engine in factory.list_engines():
        out.append(
            EngineOut(
                name=engine.name,
                display_name=engine.display_name,
                available=engine.is_available(),
                is_default=engine.name == settings.default_engine,
            )
        )
    return out


@router.get("/engines/{engine_name}/voices", response_model=List[VoiceOut])
async def list_voices(
    engine_name: str,
    language: Optional[str] = Query(default=None),
):
    try:
        engine = factory.get_engine(engine_name)
    except engine_base.EngineError as e:
        raise HTTPException(status_code=404, detail=str(e))
    voices = await engine.list_voices(language)
    return [VoiceOut(**v) for v in voices]


@router.post("/synthesize", response_model=SynthesisOut)
async def synthesize(body: SynthesizeIn, settings: Settings = Depends(get_settings)):
    try:
        result = await tts_service.synthesize(
            settings,
            body.text,
            body.voice,
            engine_name=body.engine,
            rate=body.rate,
            pitch=body.pitch,
        )
    except engine_base.EngineError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return _synthesis_out(body.text, result)


@router.post("/synthesize-batch", response_model=BatchOut)
async def synthesize_batch(body: BatchIn, settings: Settings = Depends(get_settings)):
    """Synthesize a window of sentences for read-along playback (AC-201)."""
    try:
        results = await tts_service.synthesize_batch(
            settings,
            body.texts,
            body.voice,
            engine_name=body.engine,
            rate=body.rate,
            pitch=body.pitch,
        )
    except engine_base.EngineError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return BatchOut(
        segments=[_synthesis_out(text, result) for text, result in zip(body.texts, results)]
    )
