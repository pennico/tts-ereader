"""Unit tests for tts_service: caching and engine fallback (AC-506)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engines import factory
from app.services import tts_service

from tests.mock_engine import MockTTSEngine


@pytest.fixture()
def mock_engine():
    saved = dict(factory._REGISTRY)
    engine = MockTTSEngine()
    factory.register(engine)
    yield engine
    factory._REGISTRY.clear()
    factory._REGISTRY.update(saved)


@pytest.mark.asyncio
async def test_synthesize_returns_audio_and_caches(settings, mock_engine):
    result = await tts_service.synthesize(settings, "Ciao mondo.", "mock-voice", "mock")
    assert result["engine"] == "mock"
    assert result["cached"] is False
    assert result["format"] == "wav"
    assert result["duration_ms"] > 0
    assert result["word_boundaries"][0]["word"] == "Ciao"
    # Second call is served from the disk cache (no new engine calls).
    calls_before = len(mock_engine.calls)
    cached = await tts_service.synthesize(settings, "Ciao mondo.", "mock-voice", "mock")
    assert cached["cached"] is True
    assert len(mock_engine.calls) == calls_before
    assert cached["audio"] == result["audio"]


@pytest.mark.asyncio
async def test_cache_key_separates_voices(settings, mock_engine):
    await tts_service.synthesize(settings, "Ciao.", "mock-voice", "mock")
    await tts_service.synthesize(settings, "Ciao.", "mock-voice-da", "mock")
    assert len(mock_engine.calls) == 2


@pytest.mark.asyncio
async def test_fallback_to_mock_when_primary_fails(settings, mock_engine):
    failing_name = "mock-fail"

    class _Named(MockTTSEngine):
        @property
        def name(self):
            return failing_name

        @property
        def display_name(self):
            return "Failing mock"

    saved = dict(factory._REGISTRY)
    factory.register(_Named(fail=True))
    try:
        result = await tts_service.synthesize(
            settings, "Ciao.", "mock-voice", engine_name=failing_name
        )
    finally:
        factory._REGISTRY.clear()
        factory._REGISTRY.update(saved)
    # The failing engine raised; fallback produced audio via "mock".
    assert result["engine"] == "mock"
    assert result["cached"] is False


@pytest.mark.asyncio
async def test_all_engines_failing_raises(settings):
    from app.engines.base import EngineError

    with pytest.raises(EngineError, match="all engines failed"):
        await tts_service.synthesize(settings, "Ciao.", "mock-voice", "no-such-engine")


@pytest.mark.asyncio
async def test_synthesize_batch_order_preserved(settings, mock_engine):
    texts = ["Prima frase.", "Seconda frase.", "Terza frase."]
    results = await tts_service.synthesize_batch(settings, texts, "mock-voice", "mock")
    assert len(results) == 3
    assert all(r["duration_ms"] > 0 for r in results)
    assert mock_engine.calls == texts
