"""MockTTSEngine (ARCHITECTURE_v1 §5.4): silence + generated word boundaries.

Registered as "mock" for tests; never calls the network.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engines.base import SynthesisResult, TTSEngine, WordBoundary
from app.utils.audio import pcm_to_wav

MS_PER_CHAR = 50.0


class MockTTSEngine(TTSEngine):
    """Deterministic engine: silent WAV sized to the text, fake boundaries."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []
        self.voice_calls: list[tuple] = []

    @property
    def name(self) -> str:
        return "mock"

    @property
    def display_name(self) -> str:
        return "Mock TTS"

    async def list_voices(self, language: str | None = None) -> list[dict]:
        voices = [
            {"name": "mock-voice", "display_name": "Mock Voice", "gender": "Neutral", "locale": "it-IT"},
            {"name": "mock-voice-da", "display_name": "Mock Voice DA", "gender": "Neutral", "locale": "da-DK"},
        ]
        if language:
            lang = language.lower()
            voices = [v for v in voices if v["locale"].lower().startswith(lang)]
        return voices

    async def synthesize(
        self,
        text: str,
        voice: str,
        rate: float = 1.0,
        pitch: float = 0.0,
    ) -> SynthesisResult:
        if self.fail:
            from app.engines.base import EngineError

            raise EngineError("mock engine failure")
        self.calls.append(text)
        self.voice_calls.append((voice, text))
        words = text.split()
        boundaries = []
        at = 0.0
        for word in words:
            boundaries.append(WordBoundary(word=word, start_ms=at, end_ms=at + MS_PER_CHAR))
            at += MS_PER_CHAR
        duration = max(at, 100.0)
        pcm = b"\x00\x00" * int(24000 * 2 * duration / 1000)
        return SynthesisResult(
            audio=pcm_to_wav(pcm, 24000),
            sample_rate=24000,
            duration_ms=duration,
            format="wav",
            word_boundaries=boundaries,
        )
