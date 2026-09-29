"""Gemini TTS segment cleaning — shared by the voice-test stitching and the
read-along pipeline.

gemini-3.8-flash-tts responses carry two generation artifacts, measured
live on 2026-09-29 (9/9 segments, identical shape):

- a ~120 ms loud noise burst (RMS ~16-18k, half of peak) at the very end
  of every response, after the speech has already faded to silence —
  heard as "blowing into the microphone" at every segment join;
- a short click in the first ~10-20 ms.

clean_pcm() trims both, normalizes the leading/trailing silence around
the speech, and applies short fades so segments can be concatenated
with a silence gap without clicks.
"""
from __future__ import annotations

import audioop
import struct

# 10 ms analysis windows
THRESH_LOUD = 500   # above this: speech or artifact burst
THRESH_QUIET = 100  # below this: silence
KEEP_LEAD_MS = 100  # natural silence kept before speech
KEEP_TAIL_MS = 120  # natural silence kept after speech
FADE_MS = 5         # click-free edges


def _windows(pcm: bytes, sample_width: int, rate: int) -> list:
    win = max(1, rate // 100) * sample_width
    n = len(pcm) // win
    return [audioop.rms(pcm[i * win:(i + 1) * win], sample_width)
            for i in range(n)], win


def clean_pcm(pcm: bytes, sample_width: int = 2, rate: int = 24000) -> bytes:
    """Return the speech portion of a Gemini TTS response, edge-cleaned."""
    if not pcm:
        return pcm
    rms, win = _windows(pcm, sample_width, rate)
    n = len(rms)
    if n == 0:
        return pcm

    # Tail: walk back over the loud burst (if any), then over silence,
    # keeping at most KEEP_TAIL_MS of quiet after the last speech window.
    i = n
    while i > 0 and rms[i - 1] > THRESH_LOUD:
        i -= 1                      # skip the end burst
    q = i
    while q > 0 and rms[q - 1] <= THRESH_QUIET:
        q -= 1                      # back to the end of speech
    if q == 0:
        return b""                  # no speech in this response at all
    end = min(i, q + max(1, KEEP_TAIL_MS // 10))

    # Head: skip a click in the first 50 ms, then keep KEEP_LEAD_MS of
    # the leading silence.
    j = 0
    while j < 5 and j < n and rms[j] > THRESH_LOUD:
        j += 1                      # skip the start click
    s = j
    while s < end and rms[s] <= THRESH_QUIET:
        s += 1                      # forward to the start of speech
    start = max(j, s - max(1, KEEP_LEAD_MS // 10))

    if end <= start:
        return b""
    data = pcm[start * win:end * win]

    # Short fades for click-free concatenation.
    fade = max(1, rate * FADE_MS // 1000)
    samples = list(struct.unpack("<%dh" % (len(data) // sample_width), data))
    for k in range(min(fade, len(samples) // 2)):
        samples[k] = int(samples[k] * k / fade)
        samples[-1 - k] = int(samples[-1 - k] * k / fade)
    return struct.pack("<%dh" % len(samples), *samples)
