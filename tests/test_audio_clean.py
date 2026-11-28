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

from shared.audio_clean import TARGET_SPEECH_RMS, clean_pcm, match_level, speech_level  # noqa: E402

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


def test_speech_running_to_the_end_is_not_trimmed():
    """Review C221: a take that ends mid-speech (no trailing silence)
    used to lose its last word to the end-burst trim."""
    pcm = _quiet(200) + _tone(1000) + _quiet(30) + _tone(200)
    out = clean_pcm(pcm, 2, RATE)
    assert len(out) >= len(_tone(1000) + _quiet(30) + _tone(200))


def test_speech_from_the_first_sample_is_not_trimmed():
    pcm = _tone(1000) + _quiet(300)
    out = clean_pcm(pcm, 2, RATE)
    # All of the speech plus the kept 120 ms of trailing silence.
    assert len(out) >= len(_tone(1000) + _quiet(110))


def test_long_loud_tail_is_speech_not_burst():
    pcm = _quiet(200) + _tone(500) + _quiet(200) + _burst(400)
    out = clean_pcm(pcm, 2, RATE)
    assert len(out) >= len(_tone(500) + _quiet(200) + _burst(400))


def test_two_part_end_burst_is_cut():
    """gemini-3.8-flash-lite-tts (measured 2026-11-28, every request):
    silence, 40 ms burst, 30 ms gap, 90 ms burst to the last sample."""
    pcm = (_quiet(200) + _tone(1000) + _quiet(300)
           + _burst(40, 17000) + _quiet(30) + _burst(90, 19000))
    out = clean_pcm(pcm, WIDTH, RATE)
    assert len(out) <= len(_quiet(100) + _tone(1000) + _quiet(130))
    assert audioop.rms(out[-RATE * WIDTH * 100 // 1000:], WIDTH) < 100


def test_short_word_after_a_comma_pause_is_not_a_burst():
    # A final word after only a short pause, ending the take: speech.
    pcm = _quiet(200) + _tone(1000) + _quiet(60) + _tone(200)
    out = clean_pcm(pcm, WIDTH, RATE)
    assert len(out) >= len(_tone(1000) + _quiet(60) + _tone(200))


def test_match_level_brings_takes_to_the_target():
    for amp in (3000, 8000):
        out = match_level(_quiet(100) + _tone(800, amp=amp) + _quiet(100), WIDTH, RATE)
        assert abs(speech_level(out, WIDTH, RATE) - TARGET_SPEECH_RMS) < 100


def test_match_level_caps_gain_and_peaks():
    quiet_take = _tone(500, amp=300 * 1.414)   # far below target: capped at +6 dB
    out = match_level(quiet_take, WIDTH, RATE)
    assert audioop.max(out, WIDTH) <= 2 * audioop.max(quiet_take, WIDTH) + 2
    loud_peak = _tone(500, amp=2500) + _burst(20, 32000)
    out = match_level(loud_peak, WIDTH, RATE)
    assert audioop.max(out, WIDTH) <= 30000
