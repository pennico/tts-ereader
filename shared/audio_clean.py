"""Gemini TTS segment cleaning — shared by the voice-test stitching and the
read-along pipeline.

gemini-3.8-flash-tts responses carry two generation artifacts, measured
live on 2026-09-29 (9/9 segments, identical shape):

- a ~120 ms loud noise burst (RMS ~16-18k, half of peak) at the very end
  of every response, after the speech has already faded to silence —
  heard as "blowing into the microphone" at every segment join;
- a short click in the first ~10-20 ms.

gemini-3.8-flash-lite-tts ends every response with a two-part version of
the burst (measured on Lucidità Capitolo 1-2, 2026-11-28, 178/178
requests): ~40 ms loud, ~30 ms silent, ~90 ms loud up to the last
sample, after >= 130 ms of silence. Heard as a crash at every request
join; the single-run trim below kept it because the 30 ms gap is not
the required silence.

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
# Only a short loud zone at the very end that follows silence is the end
# burst (it may be split by short gaps: the lite model's is two bursts);
# only a short loud run followed by silence is the start click. Anything
# else loud at an edge is speech and stays (review C221: a take that
# ended without trailing silence lost its last word to the burst trim).
BURST_MAX_MS = 250
BURST_QUIET_MS = 100  # silence the burst zone must follow (speech faded out)
# Level matching between takes (match_level).
SPEECH_RMS = 1500          # windows above this count as speech
TARGET_SPEECH_RMS = 3600   # median speech RMS of Lucidità Capitolo 1-2
MAX_GAIN_DB = 6.0
PEAK_LIMIT = 30000
CLICK_MAX_MS = 50
CLICK_QUIET_MS = 20   # silence the click must be followed by


def _windows(pcm: bytes, sample_width: int, rate: int) -> list:
    win = max(1, rate // 100) * sample_width
    n = len(pcm) // win
    return [audioop.rms(pcm[i * win:(i + 1) * win], sample_width)
            for i in range(n)], win


def tail_burst_start(rms: list) -> int:
    """Index of the first window of the end-burst zone, or len(rms).

    The zone is the stretch after the last silence run of at least
    BURST_QUIET_MS; it is the burst only when the take ends loud (the
    artifact runs to the last sample) and the zone is at most
    BURST_MAX_MS long. Short gaps inside the zone are part of it.
    """
    n = len(rms)
    if n == 0 or rms[-1] <= THRESH_LOUD:
        return n                    # ends quiet: no burst (or already cut)
    need = max(1, BURST_QUIET_MS // 10)
    run = 0
    k = n
    while k > 0:
        k -= 1
        if rms[k] <= THRESH_QUIET:
            run += 1
            if run >= need:
                start = k + run     # first window after the silence run
                return start if n - start <= BURST_MAX_MS // 10 else n
        else:
            run = 0
        if n - k > BURST_MAX_MS // 10 + need:
            break                   # loud zone too long: speech
    return n


def speech_level(pcm: bytes, sample_width: int = 2, rate: int = 24000) -> float:
    """Median RMS of the speech windows (0.0 when there is no speech)."""
    rms, _win = _windows(pcm, sample_width, rate)
    speech = sorted(r for r in rms if r > SPEECH_RMS)
    return float(speech[len(speech) // 2]) if speech else 0.0


def match_level(pcm: bytes, sample_width: int = 2, rate: int = 24000,
                target: float = TARGET_SPEECH_RMS) -> bytes:
    """Scale one take so its speech level is `target` (median speech RMS).

    Each Gemini request comes back at its own level; matching them makes
    the joins between requests less audible. The gain is capped at
    +/- MAX_GAIN_DB and never pushes a sample past PEAK_LIMIT.
    """
    level = speech_level(pcm, sample_width, rate)
    if level <= 0:
        return pcm
    cap = 10 ** (MAX_GAIN_DB / 20)
    gain = min(max(target / level, 1 / cap), cap)
    peak = audioop.max(pcm, sample_width)
    if peak and peak * gain > PEAK_LIMIT:
        gain = PEAK_LIMIT / peak
    if abs(gain - 1.0) < 0.01:
        return pcm
    return audioop.mul(pcm, sample_width, gain)


def clean_pcm(pcm: bytes, sample_width: int = 2, rate: int = 24000) -> bytes:
    """Return the speech portion of a Gemini TTS response, edge-cleaned."""
    if not pcm:
        return pcm
    rms, win = _windows(pcm, sample_width, rate)
    n = len(rms)
    if n == 0:
        return pcm

    # Tail: cut the end-burst zone (if any), then walk back over
    # silence, keeping at most KEEP_TAIL_MS of quiet after the last
    # speech window.
    i = tail_burst_start(rms)
    q = i
    while q > 0 and rms[q - 1] <= THRESH_QUIET:
        q -= 1                      # back to the end of speech
    if q == 0:
        return b""                  # no speech in this response at all
    end = min(i, q + max(1, KEEP_TAIL_MS // 10))

    # Head: skip a click in the first 50 ms, then keep KEEP_LEAD_MS of
    # the leading silence.
    j = 0
    while j < CLICK_MAX_MS // 10 and j < n and rms[j] > THRESH_LOUD:
        j += 1                      # the loud run at the very start
    quiet_wins = CLICK_QUIET_MS // 10
    if not (j + quiet_wins <= n
            and all(r <= THRESH_QUIET for r in rms[j:j + quiet_wins])):
        j = 0                       # speech from the first sample: keep it
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
