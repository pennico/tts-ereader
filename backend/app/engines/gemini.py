"""Gemini TTS adapter — the primary engine (AC-503).

REST call to the Generative Language API with the owner's GEMINI_API_KEY
(AI Studio key; live-verified 2026-09-19 for Italian and Danish). Output is
raw PCM L16 24kHz mono, wrapped in a WAV container (AC-508). Gemini provides
no word timestamps (AC-507: word_boundaries is None); the reader syncs at
sentence granularity for this engine. Style is controlled via a prompt
prefix (e.g. "Read as a warm narrator."). rate/pitch are ignored by this
engine in M2 (playback rate is applied client-side).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re

from app.engines.base import EngineError, SynthesisResult, TTSEngine
from app.utils.audio import pcm_to_wav

logger = logging.getLogger("tts_ereader.gemini")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash-tts"
DEFAULT_STYLE = "Read the following as a warm narrator:"

# Bounded retry for transient malformed responses (issue #15): Gemini
# occasionally answers 200 with a candidate that has no `content`; re-sending
# the identical request succeeds. One retry delay = one extra attempt.
DEFAULT_RETRY_DELAYS = (2.0, 4.0)

# Prebuilt Gemini TTS voices (subset of Google's documented list; the reader
# UI lists these). Gender per Google's voice descriptions.
PREBUILT_VOICES = [
    ("Kore", "Female", "firm"),
    ("Puck", "Male", "upbeat"),
    ("Charon", "Male", "informative"),
    ("Aoede", "Female", "breezy"),
    ("Leda", "Female", "youthful"),
    ("Orus", "Male", "firm"),
    ("Zephyr", "Female", "bright"),
    ("Fenrir", "Male", "excitable"),
]


def _response_shape(data: object) -> dict:
    """Diagnosable summary of a Gemini response: keys and finishReasons,
    never the base64 audio payload. Total: must never raise, even when
    the 200 body is not a dict at all (proxy/CDN garbage, null)."""
    if not isinstance(data, dict):
        return {"type": type(data).__name__, "repr": str(data)[:200]}
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    return {
        "keys": sorted(data.keys()),
        "candidate_count": len(candidates),
        "finish_reasons": [
            c.get("finishReason") for c in candidates if isinstance(c, dict)
        ],
        "candidate_keys": [
            sorted(c.keys()) for c in candidates if isinstance(c, dict)
        ],
        "prompt_feedback": data.get("promptFeedback"),
    }


class GeminiTTSEngine(TTSEngine):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        style: str = DEFAULT_STYLE,
        api_key: str | None = None,
        client=None,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    ):
        """client: injectable httpx-like async client (tests pass a mock).
        retry_delays: seconds to wait between attempts on a malformed
        response; len(retry_delays) + 1 attempts total (tests pass zeros)."""
        self.model = model
        self.style = style
        self._api_key = api_key
        self._client = client
        self.retry_delays = tuple(retry_delays)
        # Request/token instrumentation (issue #25): every HTTP request
        # consumes the per-model daily request quota, and usageMetadata
        # carries the token accounting. Callers read these after a run
        # and persist them in the quota ledger.
        self.request_count = 0
        self.token_count = 0

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Gemini TTS"

    def _key(self) -> str | None:
        return self._api_key or os.environ.get("GEMINI_API_KEY")

    def is_available(self) -> bool:
        return bool(self._key())

    async def _post(self, payload: dict) -> dict:
        import httpx

        key = self._key()
        if not key:
            raise EngineError("GEMINI_API_KEY not set")
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.post(
                f"{API_BASE}/models/{self.model}:generateContent",
                json=payload,
                headers={"x-goog-api-key": key},
            )
        except Exception as e:
            raise EngineError(f"Gemini request failed: {e}") from e
        finally:
            if self._client is None:
                await client.aclose()
        self.request_count += 1  # sent and answered: quota consumed
        if resp.status_code != 200:
            # 800 chars: a 429 body must include the quota metric name
            # (e.g. GenerateRequestsPerDayPerProjectPerModel) so callers
            # can distinguish a hard daily quota from a per-minute limit.
            raise EngineError(
                f"Gemini API error {resp.status_code}: {resp.text[:800]}"
            )
        return resp.json()

    async def list_voices(self, language: str | None = None) -> list[dict]:
        # Prebuilt voices are language-agnostic (multilingual).
        return [
            {"name": name, "display_name": name, "gender": gender, "locale": ""}
            for name, gender, _desc in PREBUILT_VOICES
        ]

    def _record_usage(self, data: dict) -> dict | None:
        """Accumulate usageMetadata tokens; return the per-request usage."""
        u = data.get("usageMetadata")
        if not isinstance(u, dict):
            return None
        total = u.get("totalTokenCount")
        if not isinstance(total, int):
            total = (u.get("promptTokenCount") or 0) + (u.get("candidatesTokenCount") or 0)
        self.token_count += total
        return {
            "prompt": u.get("promptTokenCount"),
            "candidates": u.get("candidatesTokenCount"),
            "total": total,
        }

    async def _generate_audio(self, payload: dict) -> tuple[bytes, str, dict | None]:
        """POST the payload, retry malformed responses, parse the audio.

        Returns (pcm, mimeType, usage). Raises EngineError on API errors
        (callers inspect the message for 429s and the recitation filter).
        """
        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            data = await self._post(payload)
            try:
                inline = data["candidates"][0]["content"]["parts"][0]["inlineData"]
                mime = inline.get("mimeType", "")
                pcm = base64.b64decode(inline["data"])
                return pcm, mime, self._record_usage(data)
            except (KeyError, IndexError, TypeError, ValueError) as e:
                shape = _response_shape(data)
                logger.warning(
                    "Gemini malformed response, attempt %d/%d: %s",
                    attempt + 1,
                    attempts,
                    json.dumps(shape, default=str),
                )
                if attempt == attempts - 1:
                    raise EngineError(
                        f"unexpected Gemini response shape after "
                        f"{attempts} attempts: {e} "
                        f"[response: {json.dumps(shape, default=str)}]"
                    ) from e
                await asyncio.sleep(self.retry_delays[attempt])

    async def synthesize(
        self,
        text: str,
        voice: str,
        rate: float = 1.0,
        pitch: float = 0.0,
    ) -> SynthesisResult:
        payload = {
            "contents": [{"parts": [{"text": f"{self.style} {text}" if self.style else text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
                },
            },
        }
        pcm, mime, usage = await self._generate_audio(payload)

        match = re.search(r"rate=(\d+)", mime)
        sample_rate = int(match.group(1)) if match else 24000
        wav = pcm_to_wav(pcm, sample_rate)
        duration_ms = len(pcm) / (sample_rate * 2) * 1000.0  # 16-bit mono
        return SynthesisResult(
            audio=wav,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            format="wav",
            word_boundaries=None,
            usage=usage,
        )

    async def synthesize_multi(
        self,
        turns: list[tuple[str, str]],
        style: str | None = None,
    ) -> SynthesisResult:
        """One request for several lines (issue #25).

        turns: [(voice, text)] in reading order. One voice: a plain
        single-voice request with the lines as paragraphs. Two voices: a
        multi-speaker request — each voice becomes a speaker label
        ("Rami: <line>") and the model reads each line in the labeled
        speaker's voice without speaking the labels. More than two
        voices is rejected locally: the API requires exactly 2
        speaker_voice_configs, so the caller splits the batch.
        """
        voices: list[str] = []
        for voice, _text in turns:
            if voice not in voices:
                voices.append(voice)
        if len(voices) > 2:
            raise EngineError(
                "Gemini multi-speaker requests take at most 2 voices "
                f"(got {len(voices)}): split the batch so each request "
                "has at most 2 distinct voices")
        style = self.style if style is None else style
        if len(voices) == 1:
            text = "\n\n".join(t for _v, t in turns)
            speech_config: dict = {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voices[0]}
                }
            }
        else:
            text = "\n\n".join(f"{v}: {t}" for v, t in turns)
            speech_config = {
                "multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
                    {
                        "speaker": v,
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {"voiceName": v}
                        },
                    }
                    for v in voices
                ]}
            }
        payload = {
            "contents": [{"parts": [
                {"text": f"{style} {text}" if style else text}
            ]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": speech_config,
            },
        }
        pcm, mime, usage = await self._generate_audio(payload)

        match = re.search(r"rate=(\d+)", mime)
        sample_rate = int(match.group(1)) if match else 24000
        wav = pcm_to_wav(pcm, sample_rate)
        duration_ms = len(pcm) / (sample_rate * 2) * 1000.0  # 16-bit mono
        return SynthesisResult(
            audio=wav,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            format="wav",
            word_boundaries=None,
            usage=usage,
        )
