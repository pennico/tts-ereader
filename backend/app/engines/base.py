"""TTSEngine abstract base class (ARCHITECTURE_v1 §11.1, AC-501, AC-505).

The app never calls an engine directly: everything goes through this
interface, so new engines are added as adapters without touching app code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional


@dataclass
class WordBoundary:
    """One word's time span within a synthesis result (ms)."""

    word: str
    start_ms: float
    end_ms: float


@dataclass
class SynthesisResult:
    """Normalized synthesis output (AC-508: consistent format across engines).

    format: "wav" (PCM16) or "mp3"; both decode via the Web Audio API.
    word_boundaries is None for engines without timestamps (AC-507).
    """

    audio: bytes
    sample_rate: int
    duration_ms: float
    format: str = "wav"
    word_boundaries: Optional[List[WordBoundary]] = field(default=None)


class EngineError(Exception):
    """Raised when an engine fails or is misconfigured (drives AC-506 fallback)."""


class TTSEngine(ABC):
    """A pluggable TTS engine adapter."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier, e.g. "gemini"."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for the UI."""

    @abstractmethod
    async def list_voices(self, language: Optional[str] = None) -> List[dict]:
        """Voices as dicts with at least ShortName/name, gender, locale."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str,
        rate: float = 1.0,
        pitch: float = 0.0,
    ) -> SynthesisResult:
        """Synthesize text to audio; rate is a multiplier (1.0 = native)."""

    async def synthesize_stream(
        self,
        text: str,
        voice: str,
        rate: float = 1.0,
        pitch: float = 0.0,
    ) -> AsyncIterator[bytes]:
        """Stream raw audio chunks; default: yield the full synthesize() blob."""
        result = await self.synthesize(text, voice, rate, pitch)
        yield result.audio

    def is_available(self) -> bool:
        """Whether the engine can run in this environment (keys, deps)."""
        return True
