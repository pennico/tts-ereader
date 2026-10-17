"""Integration tests for the TTS API (AC-301, AC-302, AC-501..AC-508)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engines import factory

from tests.mock_engine import MockTTSEngine


@pytest.fixture()
def mock_engine():
    saved = dict(factory._REGISTRY)
    engine = MockTTSEngine()
    factory.register(engine)
    yield engine
    factory._REGISTRY.clear()
    factory._REGISTRY.update(saved)


def test_list_engines(client, mock_engine):
    resp = client.get("/api/tts/engines")
    assert resp.status_code == 200
    engines = {e["name"]: e for e in resp.json()}
    assert "mock" in engines
    assert engines["mock"]["available"] is True
    # Gemini is the documented default engine (may be unavailable without key).
    assert engines["gemini"]["is_default"] is True


def test_list_voices_with_language_filter(client, mock_engine):
    resp = client.get("/api/tts/engines/mock/voices", params={"language": "da"})
    assert resp.status_code == 200
    voices = resp.json()
    assert [v["name"] for v in voices] == ["mock-voice-da"]


def test_list_voices_unknown_engine_404(client):
    resp = client.get("/api/tts/engines/nope/voices")
    assert resp.status_code == 404


def test_synthesize(client, mock_engine):
    resp = client.post(
        "/api/tts/synthesize",
        json={"text": "Ciao mondo.", "engine": "mock", "voice": "mock-voice"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine"] == "mock"
    assert body["format"] == "wav"
    assert body["duration_ms"] > 0
    assert body["word_boundaries"][0]["word"] == "Ciao"
    assert len(body["audio_b64"]) > 0


def test_synthesize_uses_cache(client, mock_engine):
    payload = {"text": "Ciao.", "engine": "mock", "voice": "mock-voice"}
    first = client.post("/api/tts/synthesize", json=payload).json()
    calls = len(mock_engine.calls)
    second = client.post("/api/tts/synthesize", json=payload).json()
    assert second["cached"] is True
    assert len(mock_engine.calls) == calls
    assert second["audio_b64"] == first["audio_b64"]


def test_synthesize_rate_validation(client):
    resp = client.post(
        "/api/tts/synthesize",
        json={"text": "Ciao.", "engine": "mock", "voice": "mock-voice", "rate": 5.0},
    )
    assert resp.status_code == 422  # AC-303: rate clamped to 0.5..2.0


def test_synthesize_unknown_engine_502(client):
    resp = client.post(
        "/api/tts/synthesize",
        json={"text": "Ciao.", "engine": "no-such-engine", "voice": "x"},
    )
    assert resp.status_code == 502
    assert "all engines failed" in resp.json()["detail"]


def test_synthesize_batch(client, mock_engine):
    resp = client.post(
        "/api/tts/synthesize-batch",
        json={
            "texts": ["Prima.", "Seconda."],
            "engine": "mock",
            "voice": "mock-voice",
        },
    )
    assert resp.status_code == 200
    segments = resp.json()["segments"]
    assert [s["text"] for s in segments] == ["Prima.", "Seconda."]
    assert all(s["duration_ms"] > 0 for s in segments)
