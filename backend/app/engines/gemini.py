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

    async def synthesize(
        self,
        text: str,
        voice: str,
        rate: float = 1.0,
        pitch: float = 0.0,
    ) -> SynthesisResult:
        payload = {
            "contents": [{"parts": [{"text": f"{self.style} {text}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
                },
            },
        }
        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            data = await self._post(payload)
            try:
                inline = data["candidates"][0]["content"]["parts"][0]["inlineData"]
                mime = inline.get("mimeType", "")
                pcm = base64.b64decode(inline["data"])
                break
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
        )
