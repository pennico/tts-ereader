"""Engine factory + registry (AC-505, AC-506).

New engines plug in by subclassing TTSEngine and registering here; the rest
of the app only knows engine names. The fallback order is: requested engine,
then the remaining available engines (primary Gemini, free fallback edge).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.engines.base import EngineError, TTSEngine

_REGISTRY: Dict[str, TTSEngine] = {}
_FALLBACK_ORDER = ["gemini", "edge"]


def register(engine: TTSEngine) -> None:
    _REGISTRY[engine.name] = engine


def get_engine(name: str) -> TTSEngine:
    if name not in _REGISTRY:
        raise EngineError(f"unknown TTS engine: {name}")
    return _REGISTRY[name]


def list_engines() -> List[TTSEngine]:
    ordered = [n for n in _FALLBACK_ORDER if n in _REGISTRY]
    ordered += [n for n in _REGISTRY if n not in ordered]
    return [_REGISTRY[n] for n in ordered]


def fallback_chain(requested: Optional[str]) -> List[TTSEngine]:
    """Available engines, requested first, then the documented order."""
    names: List[str] = []
    if requested:
        names.append(requested)
    names += [n for n in _FALLBACK_ORDER if n not in names]
    names += [n for n in _REGISTRY if n not in names]
    chain = []
    for name in names:
        engine = _REGISTRY.get(name)
        if engine and engine.is_available():
            chain.append(engine)
    return chain


def _default_registry() -> None:
    """Register the built-in engines once (import-safe)."""
    if _REGISTRY:
        return
    from app.engines.edge_tts import EdgeTTSEngine
    from app.engines.gemini import GeminiTTSEngine

    register(GeminiTTSEngine())
    register(EdgeTTSEngine())


_default_registry()
