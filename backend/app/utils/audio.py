"""Audio helpers: PCM->WAV wrapping and MP3->WAV conversion (AC-508).

Dependency-light: WAV wrapping is a hand-built 44-byte RIFF header (stdlib
only). MP3 conversion uses pydub (already a v0 dependency) when available;
callers fall back to serving MP3 directly, which the browser decodes anyway.
"""
from __future__ import annotations

import struct
from typing import Optional


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM (L16, mono by default) in a WAV container."""
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        byte_rate,
        block_align,
        sample_width * 8,
        b"data",
        data_size,
    )
    return header + pcm


def mp3_to_wav(mp3: bytes) -> Optional[bytes]:
    """Convert MP3 to WAV via pydub/ffmpeg; None if unavailable."""
    try:
        from pydub import AudioSegment
    except ImportError:
        return None
    try:
        import io

        seg = AudioSegment.from_file(io.BytesIO(mp3), format="mp3")
        out = io.BytesIO()
        seg.export(out, format="wav")
        return out.getvalue()
    except Exception:
        # Missing ffmpeg binary or corrupt audio: let the caller serve MP3.
        return None


def wav_duration_ms(wav: bytes) -> float:
    """Duration of a WAV blob from its header (data size / byte rate)."""
    if len(wav) < 44 or wav[:4] != b"RIFF":
        return 0.0
    sample_rate = struct.unpack_from("<I", wav, 24)[0]
    byte_rate = struct.unpack_from("<I", wav, 28)[0]
    data_size = struct.unpack_from("<I", wav, 40)[0]
    if byte_rate == 0:
        byte_rate = sample_rate * 2
    if byte_rate == 0:
        return 0.0
    return data_size / byte_rate * 1000.0
