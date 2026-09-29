"""edge-tts adapter (AC-502, AC-507).

Streams edge-tts audio + WordBoundary events (offsets in 100-ns ticks,
converted to ms). Audio is normalized to WAV via pydub/ffmpeg when
available (AC-508); otherwise MP3 is served directly (the browser decodes
both). `pitch` is an edge-tts Hz offset (e.g. 10 -> "+10Hz"); `rate` is a
multiplier converted to edge-tts's percentage string.
"""
from __future__ import annotations

import os
from typing import List, Optional

from app.engines.base import EngineError, SynthesisResult, TTSEngine, WordBoundary
from app.utils.audio import mp3_to_wav, wav_duration_ms

TICKS_PER_MS = 10_000  # edge-tts boundary offsets are 100-ns ticks


def _rate_str(rate: float) -> str:
    """Multiplier (1.0 = native) -> edge-tts rate string like '+10%'."""
    pct = round((rate - 1.0) * 100)
    return f"{pct:+d}%"


def _pitch_str(pitch: float) -> str:
    """Hz offset (0 = native) -> edge-tts pitch string like '+10Hz'."""
    return f"{round(pitch):+d}Hz"


class EdgeTTSEngine(TTSEngine):
    def __init__(self, default_voice: str = "it-IT-GiuseppeMultilingualNeural"):
        self.default_voice = default_voice

    @property
    def name(self) -> str:
        return "edge"

    @property
    def display_name(self) -> str:
        return "edge-tts"

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401

            return True
        except ImportError:
            return False

    async def list_voices(self, language: Optional[str] = None) -> List[dict]:
        import edge_tts

        voices = await edge_tts.list_voices()
        out = [
            {
                "name": v["ShortName"],
                "display_name": v["ShortName"].split("-")[-1],
                "gender": v.get("Gender", ""),
                "locale": v.get("Locale", ""),
            }
            for v in voices
        ]
        if language:
            lang = language.lower()
            out = [v for v in out if v["locale"].lower().startswith(lang)]
        return out

    async def synthesize(
        self,
        text: str,
        voice: str,
        rate: float = 1.0,
        pitch: float = 0.0,
    ) -> SynthesisResult:
        import edge_tts

        try:
            communicate = edge_tts.Communicate(
                text,
                voice,
                rate=_rate_str(rate),
                pitch=_pitch_str(pitch),
                boundary="WordBoundary",
            )
            audio = bytearray()
            boundaries: List[WordBoundary] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    boundaries.append(
                        WordBoundary(
                            word=chunk["text"],
                            start_ms=chunk["offset"] / TICKS_PER_MS,
                            end_ms=(chunk["offset"] + chunk["duration"]) / TICKS_PER_MS,
                        )
                    )
        except Exception as e:  # network/service/voice errors -> AC-506 fallback
            raise EngineError(f"edge-tts synthesis failed: {e}") from e

        if not audio:
            raise EngineError("edge-tts returned no audio")

        wav = mp3_to_wav(bytes(audio))
        if wav is not None:
            return SynthesisResult(
                audio=wav,
                sample_rate=24000,
                duration_ms=wav_duration_ms(wav),
                format="wav",
                word_boundaries=boundaries or None,
            )
        # No pydub/ffmpeg: serve MP3 as-is (decoded client-side).
        return SynthesisResult(
            audio=bytes(audio),
            sample_rate=24000,
            duration_ms=(boundaries[-1].end_ms if boundaries else 0.0) + 250.0,
            format="mp3",
            word_boundaries=boundaries or None,
        )
