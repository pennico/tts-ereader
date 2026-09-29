"""Unit tests for TTS engine adapters (AC-502, AC-503, AC-507, AC-508)."""
from __future__ import annotations

import base64
import sys
import types

import pytest

from app.engines.base import EngineError, SynthesisResult, WordBoundary
from app.engines import edge_tts as edge_module
from app.engines.edge_tts import EdgeTTSEngine, _pitch_str, _rate_str
from app.engines.gemini import GeminiTTSEngine
from app.utils.audio import pcm_to_wav, wav_duration_ms


# ── utils/audio ────────────────────────────────────────────────────────────


def test_pcm_to_wav_header_and_duration():
    pcm = b"\x00\x00" * 24000  # 1 second of silence at 24kHz
    wav = pcm_to_wav(pcm, 24000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav_duration_ms(wav) == pytest.approx(1000.0)


def test_wav_duration_rejects_garbage():
    assert wav_duration_ms(b"nope") == 0.0


# ── edge-tts adapter ───────────────────────────────────────────────────────


def test_rate_and_pitch_strings():
    assert _rate_str(1.0) == "+0%"
    assert _rate_str(1.5) == "+50%"
    assert _rate_str(0.5) == "-50%"
    assert _pitch_str(0) == "+0Hz"
    assert _pitch_str(10) == "+10Hz"
    assert _pitch_str(-5) == "-5Hz"


class _FakeCommunicate:
    def __init__(self, text, voice, rate="+0%", pitch="+0Hz", boundary=None):
        self.text = text

    async def stream(self):
        words = self.text.split()
        offset = 500000  # 100-ns ticks
        for word in words:
            yield {
                "type": "WordBoundary",
                "offset": offset,
                "duration": 2875000,
                "text": word,
            }
            offset += 3000000
        yield {"type": "audio", "data": b"ID3fake-mp3-bytes"}


def _install_fake_edge_tts(monkeypatch):
    fake = types.ModuleType("edge_tts")
    fake.Communicate = _FakeCommunicate

    async def list_voices():
        return [
            {"ShortName": "da-DK-ChristelNeural", "Gender": "Female", "Locale": "da-DK"},
            {"ShortName": "it-IT-DiegoNeural", "Gender": "Male", "Locale": "it-IT"},
        ]

    fake.list_voices = list_voices
    monkeypatch.setitem(sys.modules, "edge_tts", fake)


@pytest.mark.asyncio
async def test_edge_synthesize_mp3_fallback(monkeypatch):
    _install_fake_edge_tts(monkeypatch)
    # No pydub/ffmpeg in this path: serve MP3 directly (AC-508 fallback).
    monkeypatch.setattr(edge_module, "mp3_to_wav", lambda mp3: None)
    engine = EdgeTTSEngine()
    result = await engine.synthesize("Ciao mondo", "it-IT-GiuseppeMultilingualNeural")
    assert result.format == "mp3"
    assert result.audio == b"ID3fake-mp3-bytes"
    assert result.word_boundaries is not None
    assert result.word_boundaries[0].word == "Ciao"
    assert result.word_boundaries[0].start_ms == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_edge_synthesize_wav(monkeypatch):
    _install_fake_edge_tts(monkeypatch)
    wav = pcm_to_wav(b"\x00\x00" * 4800, 24000)
    monkeypatch.setattr(edge_module, "mp3_to_wav", lambda mp3: wav)
    engine = EdgeTTSEngine()
    result = await engine.synthesize("Hej verden", "da-DK-ChristelNeural", rate=1.2)
    assert result.format == "wav"
    assert result.audio == wav
    assert result.word_boundaries[0].word == "Hej"


@pytest.mark.asyncio
async def test_edge_list_voices_language_filter(monkeypatch):
    _install_fake_edge_tts(monkeypatch)
    engine = EdgeTTSEngine()
    da = await engine.list_voices("da")
    assert [v["name"] for v in da] == ["da-DK-ChristelNeural"]
    assert engine.is_available()


# ── Gemini adapter ──────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response):
        self._response = response
        self.requests = []

    async def post(self, url, json=None, headers=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        return self._response


def _gemini_payload(pcm: bytes) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/L16;codec=pcm;rate=24000",
                                "data": base64.b64encode(pcm).decode(),
                            }
                        }
                    ]
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_gemini_synthesize_wraps_pcm_in_wav():
    pcm = b"\x00\x00" * 24000  # 1s
    client = _FakeClient(_FakeResponse(payload=_gemini_payload(pcm)))
    engine = GeminiTTSEngine(api_key="test-key", client=client)
    result = await engine.synthesize("Ciao", "Kore")
    assert result.format == "wav"
    assert result.sample_rate == 24000
    assert result.duration_ms == pytest.approx(1000.0)
    assert result.audio[:4] == b"RIFF"
    assert result.word_boundaries is None  # Gemini has no timestamps (AC-507)
    # Style prompt + voice config are in the request.
    body = client.requests[0]["json"]
    assert body["contents"][0]["parts"][0]["text"].startswith("Read the following")
    assert (
        body["generationConfig"]["speechConfig"]["voiceConfig"][
            "prebuiltVoiceConfig"
        ]["voiceName"]
        == "Kore"
    )
    assert client.requests[0]["headers"]["x-goog-api-key"] == "test-key"


@pytest.mark.asyncio
async def test_gemini_api_error_raises_engine_error():
    client = _FakeClient(_FakeResponse(status_code=429, text="rate limited"))
    engine = GeminiTTSEngine(api_key="k", client=client)
    with pytest.raises(EngineError, match="429"):
        await engine.synthesize("Ciao", "Kore")


@pytest.mark.asyncio
async def test_gemini_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    engine = GeminiTTSEngine()
    assert not engine.is_available()
    with pytest.raises(EngineError, match="GEMINI_API_KEY"):
        await engine.synthesize("Ciao", "Kore")


@pytest.mark.asyncio
async def test_gemini_list_voices_is_language_agnostic():
    engine = GeminiTTSEngine(api_key="k")
    voices = await engine.list_voices("da")
    assert {v["name"] for v in voices} >= {"Kore", "Puck", "Charon"}
