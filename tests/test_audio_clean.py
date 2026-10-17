"""Tests for shared/audio_clean.py — synthetic PCM mirroring the measured
Gemini 3.8 TTS artifacts (start click, speech, silence, 120 ms end burst)."""
from __future__ import annotations

import audioop
import math
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from shared.audio_clean import clean_pcm  # noqa: E402

RATE = 24000
WIDTH = 2


def _tone(ms, freq=220, amp=8000):
    n = RATE * ms // 1000
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / RATE)))
                    for i in range(n))


def _quiet(ms):
    return b"\x00" * (RATE * ms // 1000 * WIDTH)


def _burst(ms, amp=16000):
    # noise at half of peak — the measured end-of-response artifact
    n = RATE * ms // 1000
    return b"".join(struct.pack("<h", int(amp * math.sin(37 * i))) for i in range(n))


def test_cleans_end_burst_and_start_click():
    pcm = _burst(10) + _quiet(200) + _tone(1000) + _quiet(200) + _burst(120)
    out = clean_pcm(pcm, WIDTH, RATE)
    rms_tail = audioop.rms(out[-480:], WIDTH)   # last 10 ms
    rms_head = audioop.rms(out[:480], WIDTH)    # first 10 ms
    assert rms_tail < 100, f"tail burst survived: {rms_tail}"
    assert rms_head < 100, f"start click survived: {rms_head}"
    # speech body kept
    assert audioop.rms(out, WIDTH) > 1000
    # roughly speech + kept silences, burst gone
    assert len(out) < len(pcm) - RATE * 100 // 1000 * WIDTH


def test_no_burst_still_normalizes_edges():
    pcm = _quiet(400) + _tone(500) + _quiet(400)
    out = clean_pcm(pcm, WIDTH, RATE)
    assert len(out) < len(pcm)  # excess silence trimmed
    assert audioop.rms(out, WIDTH) > 1000


def test_all_silence_returns_empty():
    assert clean_pcm(_quiet(500), WIDTH, RATE) == b""


def test_fades_present():
    pcm = _quiet(100) + _tone(500) + _quiet(100)
    out = clean_pcm(pcm, WIDTH, RATE)
    samples = struct.unpack("<%dh" % (len(out) // 2), out)
    assert abs(samples[0]) < 100 and abs(samples[-1]) < 100
