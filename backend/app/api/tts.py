"""TTS endpoints: engines, voices, synthesize, batch (AC-501..AC-508)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

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
    engine: str | None = None
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
    word_boundaries: list[WordBoundaryOut] | None = None


class BatchIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)
    engine: str | None = None
    voice: str
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-20.0, le=20.0)
    # Per-text voice overrides for voice-cast playback (AC-305); parallel to
    # texts, empty entries fall back to `voice`.
    voices: list[str] | None = None

    @model_validator(mode="after")
    def _voices_match_texts(self):
        if self.voices is not None and len(self.voices) != len(self.texts):
            raise ValueError("voices must be parallel to texts (same length)")
        return self


class CastRoleOut(BaseModel):
    role: str
    display_name: str
    voice: str
    voice_display_name: str


class CastDefaultsOut(BaseModel):
    engine: str
    language: str
    roles: list[CastRoleOut]


class BatchOut(BaseModel):
    segments: list[SynthesisOut]


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


@router.get("/engines", response_model=list[EngineOut])
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


@router.get("/engines/{engine_name}/voices", response_model=list[VoiceOut])
async def list_voices(
    engine_name: str,
    language: str | None = Query(default=None),
):
    try:
        engine = factory.get_engine(engine_name)
    except engine_base.EngineError as e:
        raise HTTPException(status_code=404, detail=str(e))
    voices = await engine.list_voices(language)
    return [VoiceOut(**v) for v in voices]


@router.get("/cast-defaults", response_model=CastDefaultsOut)
def cast_defaults(
    engine: str | None = None,
    language: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
):
    """Default voice cast for an engine + language (drives the cast UI, AC-305)."""
    try:
        from shared import voice_cast
    except ImportError:  # pragma: no cover - repo-root import bootstrap
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from shared import voice_cast

    engine_name = engine or settings.default_engine
    cast = voice_cast.default_cast(engine_name, language)
    return CastDefaultsOut(
        engine=engine_name,
        language=language or "",
        roles=[
            CastRoleOut(
                role=role,
                display_name=voice_cast.ROLE_DISPLAY[role],
                voice=voice,
                voice_display_name=name,
            )
            for role, (voice, name) in cast.items()
        ],
    )


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
            voices=body.voices,
        )
    except engine_base.EngineError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return BatchOut(
        segments=[_synthesis_out(text, result) for text, result in zip(body.texts, results)]
    )
