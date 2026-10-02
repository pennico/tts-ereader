"""Unit tests for TTS engine adapters (AC-502, AC-503, AC-507, AC-508)."""
from __future__ import annotations

import base64
import logging
import sys
import types

import pytest
from app.engines import edge_tts as edge_module
from app.engines.base import EngineError
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


class _FakeClientSeq:
    """Returns queued responses in order — for retry-path tests (issue #15)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    async def post(self, url, json=None, headers=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


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
async def test_gemini_429_body_keeps_quota_metric_name():
    # Issue #17: callers (gemini_readaloud.synth_line) tell a hard daily
    # quota from a per-minute limit by the quota metric name in the 429
    # body, so the error must not truncate it away. The preamble is the
    # real body's (long) one, padded past 300 chars so the metric name
    # sits outside the old truncation window and this test fails if the
    # window is ever reverted to resp.text[:300].
    body = (
        '{"error": {"code": 429, "message": "You exceeded your current '
        "quota, please check your plan and billing details. For more "
        "information on how to request increases to your quota limits, "
        "follow the directions here: https://ai.google.dev/gemini-api/"
        "docs/rate-limits. \\n* Quota exceeded for quota metric "
        "'GenerateRequestsPerDayPerProjectPerModel' and limit "
        "'GenerateRequestsPerDayPerProjectPerModel-freetier' of service "
        "'generativelanguage.googleapis.com' for consumer "
        "'project_number:1234567890'.\"}}"
    )
    assert body.index("PerDay") > 300  # outside the old truncation window
    client = _FakeClient(_FakeResponse(status_code=429, text=body))
    engine = GeminiTTSEngine(api_key="k", client=client)
    with pytest.raises(EngineError, match="PerDayPerProjectPerModel"):
        await engine.synthesize("Ciao", "Kore")


@pytest.mark.asyncio
async def test_gemini_retries_malformed_response_then_succeeds(caplog):
    # Issue #15: a 200 whose candidate has no `content` is transient —
    # the identical request succeeds on re-send.
    pcm = b"\x00\x00" * 2400
    malformed = {"candidates": [{"finishReason": "STOP"}]}
    client = _FakeClientSeq(
        [_FakeResponse(payload=malformed), _FakeResponse(payload=_gemini_payload(pcm))]
    )
    engine = GeminiTTSEngine(api_key="k", client=client, retry_delays=(0.0,))
    with caplog.at_level(logging.WARNING, logger="tts_ereader.gemini"):
        result = await engine.synthesize("Ciao", "Kore")
    assert result.audio[:4] == b"RIFF"
    assert result.sample_rate == 24000
    assert len(client.requests) == 2  # one re-send, then success
    # The discarded response shape is logged for diagnosis.
    assert "STOP" in caplog.text
    assert "finish_reasons" in caplog.text


@pytest.mark.asyncio
async def test_gemini_raises_after_retries_exhausted():
    malformed = {
        "candidates": [{"finishReason": "SAFETY"}],
        "promptFeedback": {"blockReason": "SAFETY"},
    }
    client = _FakeClientSeq([_FakeResponse(payload=malformed)] * 3)
    engine = GeminiTTSEngine(api_key="k", client=client, retry_delays=(0.0, 0.0))
    with pytest.raises(EngineError, match="SAFETY") as excinfo:
        await engine.synthesize("Ciao", "Kore")
    assert "unexpected Gemini response shape" in str(excinfo.value)
    assert len(client.requests) == 3  # bounded: 1 + len(retry_delays)


class _RawBodyResponse(_FakeResponse):
    """200 response whose json() body is not a dict (proxy/CDN garbage)."""

    def __init__(self, body):
        super().__init__()
        self._body = body

    def json(self):
        return self._body


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], None, "hello", {"candidates": 5}])
async def test_gemini_nondict_response_flows_through_retry_and_engine_error(
    caplog, body
):
    # Review finding on PR #16: a non-dict 200 body must not escape as a
    # raw AttributeError/TypeError — it goes through the retry loop and
    # ends as EngineError, like on main.
    client = _FakeClientSeq([_RawBodyResponse(body)] * 2)
    engine = GeminiTTSEngine(api_key="k", client=client, retry_delays=(0.0,))
    with caplog.at_level(logging.WARNING, logger="tts_ereader.gemini"):
        with pytest.raises(EngineError, match="unexpected Gemini response shape"):
            await engine.synthesize("Ciao", "Kore")
    assert len(client.requests) == 2  # retried once, then EngineError
    assert "malformed response" in caplog.text


@pytest.mark.asyncio
async def test_gemini_nondict_response_then_good_payload_succeeds():
    # A transient non-dict 200 followed by a good response recovers.
    pcm = b"\x00\x00" * 2400
    client = _FakeClientSeq(
        [_RawBodyResponse([]), _FakeResponse(payload=_gemini_payload(pcm))]
    )
    engine = GeminiTTSEngine(api_key="k", client=client, retry_delays=(0.0,))
    result = await engine.synthesize("Ciao", "Kore")
    assert result.audio[:4] == b"RIFF"
    assert len(client.requests) == 2


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
