"""TTS business logic: cached synthesis with engine fallback (AC-506, AC-508).

Every synthesis is cached on disk keyed by engine+voice+params+text hash, so
re-reading a chapter is instant and the homelab can pre-warm books.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from app.core.config import Settings
from app.engines import base as engine_base
from app.engines import factory


def _cache_key(engine_name: str, voice: str, rate: float, pitch: float, text: str) -> str:
    raw = f"{engine_name}|{voice}|{rate:.3f}|{pitch:.3f}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result_to_dict(result: engine_base.SynthesisResult) -> dict:
    d = asdict(result)
    d["audio"] = base64.b64encode(result.audio).decode("ascii")
    return d


def _result_from_dict(d: dict) -> engine_base.SynthesisResult:
    return engine_base.SynthesisResult(
        audio=base64.b64decode(d["audio"]),
        sample_rate=d["sample_rate"],
        duration_ms=d["duration_ms"],
        format=d.get("format", "wav"),
        word_boundaries=[
            engine_base.WordBoundary(**wb) for wb in (d.get("word_boundaries") or [])
        ]
        or None,
    )


def _cache_path(settings: Settings, key: str) -> Path:
    return settings.audio_cache_dir / f"{key}.json"


def _cache_get(settings: Settings, key: str) -> engine_base.SynthesisResult | None:
    path = _cache_path(settings, key)
    if not path.is_file():
        return None
    try:
        return _result_from_dict(json.loads(path.read_text()))
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _cache_put(settings: Settings, key: str, result: engine_base.SynthesisResult) -> None:
    path = _cache_path(settings, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_result_to_dict(result)))


async def synthesize(
    settings: Settings,
    text: str,
    voice: str,
    engine_name: str | None = None,
    rate: float = 1.0,
    pitch: float = 0.0,
) -> dict:
    """Synthesize one text, falling back across engines on failure (AC-506).

    Returns the serialized result dict (audio base64) plus the engine that
    actually produced it.
    """
    engine_name = engine_name or settings.default_engine
    key = _cache_key(engine_name, voice, rate, pitch, text)
    cached = _cache_get(settings, key)
    if cached is not None:
        out = _result_to_dict(cached)
        out["engine"] = engine_name
        out["cached"] = True
        return out

    errors: list[str] = []
    for engine in factory.fallback_chain(engine_name):
        try:
            result = await engine.synthesize(text, voice, rate, pitch)
        except engine_base.EngineError as e:
            errors.append(f"{engine.name}: {e}")
            continue
        _cache_put(settings, key, result)
        out = _result_to_dict(result)
        out["engine"] = engine.name
        out["cached"] = False
        return out
    raise engine_base.EngineError(
        f"all engines failed for engine={engine_name!r}: " + "; ".join(errors)
    )


async def synthesize_batch(
    settings: Settings,
    texts: list[str],
    voice: str,
    engine_name: str | None = None,
    rate: float = 1.0,
    pitch: float = 0.0,
    voices: list[str] | None = None,
) -> list[dict]:
    """Synthesize a window of sentences (the reader's playback unit).

    voices (AC-305): optional per-text voice overrides for voice-cast
    playback; texts without an entry fall back to `voice`.
    """
    out = []
    for i, text in enumerate(texts):
        text_voice = voices[i] if voices and i < len(voices) and voices[i] else voice
        out.append(
            await synthesize(settings, text, text_voice, engine_name, rate, pitch)
        )
    return out
