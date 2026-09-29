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

import base64
import os
import re
from typing import List, Optional

from app.engines.base import EngineError, SynthesisResult, TTSEngine
from app.utils.audio import pcm_to_wav

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_STYLE = "Read the following as a warm narrator:"

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


class GeminiTTSEngine(TTSEngine):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        style: str = DEFAULT_STYLE,
        api_key: Optional[str] = None,
        client=None,
    ):
        """client: injectable httpx-like async client (tests pass a mock)."""
        self.model = model
        self.style = style
        self._api_key = api_key
        self._client = client

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Gemini TTS"

    def _key(self) -> Optional[str]:
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
            raise EngineError(
                f"Gemini API error {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()

    async def list_voices(self, language: Optional[str] = None) -> List[dict]:
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
        data = await self._post(payload)
        try:
            inline = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            mime = inline.get("mimeType", "")
            pcm = base64.b64decode(inline["data"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise EngineError(f"unexpected Gemini response shape: {e}") from e

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
