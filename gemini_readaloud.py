#!/usr/bin/env python3
"""gemini_readaloud: read-along EPUB with Gemini TTS (box method).

Same output contract as epub_readaloud.py (prepared text as content, one
SMIL-synced paragraph per line), but synthesis goes through the Gemini
TTS engine one line at a time — the "box" method validated in
out/voice_tests: short requests, no style prefix, per-line voices.

The blocking quota is the per-day REQUEST count (100/day on the 3.8
TTS models), not tokens, so lines are batched into multi-speaker
requests while keeping per-line voice casting, per-line SMIL offsets
(the batch take is split back into per-line segments at silence gaps),
per-batch cache keys, and the per-line fallbacks (recitation-filter
sentence-splitting, exit-75 quota abort).

Batch sizing (owner decision, 2026-10-07): by default the WHOLE
required text is spread over --daily-requests 90 requests — each
request carries total_chars/90 characters (capped by
--max-request-chars) — so a full read fits one day's 100-request
quota with the remainder as margin for ad-hoc daily tests.
--lines-per-request N overrides the sizing with fixed batches;
--daily-requests 0 restores the original one-request-per-line box
method.

Every line's audio is cleaned (shared/audio_clean.py: the 3.8 end-of-
response noise burst and start click are trimmed, edges faded) and
cached under the work dir, so runs are resumable: re-running skips
everything already synthesized and only spends quota on new lines.
The prepared text is cached too and reused verbatim on re-runs (issue
#17): LLM preparation is non-deterministic, so regenerating it would
rewrite every line, invalidate the whole segment cache and re-spend
the chapter's Gemini quota on every run — a quota-limited run could
never finish. --reprepare forces regeneration.

Every run appends its measured request/token counts (from the API
responses' usageMetadata) to the quota ledger (default
out/quota_ledger.json, issue #25) — on success, quota abort, and
failure alike.

Usage:
  python3 gemini_readaloud.py --epub book.epub --list-chapters
  python3 gemini_readaloud.py --epub book.epub --chapter 3 --output out/ch1.epub
  python3 gemini_readaloud.py --epub book.epub --all --output out/book.epub
  python3 gemini_readaloud.py --epub book.epub --chapter 3 \
      --daily-requests 40 --output out/ch1.epub

  python3 gemini_readaloud.py --epub book.epub --chapter 3 \
      --preset balanced --output out/ch1.epub

Voice (owner decision, 2026-10-07): single voice Rami on
gemini-3.8-flash-lite-tts. --single VOICE changes the single voice;
--cast switches to the role cast (narration Kore, male dialogue Rami,
female dialogue Leda).

Requires: MISTRAL_API_KEY + GEMINI_API_KEY (.env), pydub + ffmpeg (mp3).
NOTE: Apple Books ignores Media Overlays; test in Thorium Reader.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import os
import re
import sys
import time
import wave
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "backend"))

from app.engines.base import EngineError  # noqa: E402
from app.engines.gemini import GeminiTTSEngine  # noqa: E402

from epub_mo import clock_value, validate  # noqa: E402
from epub_readaloud import (  # noqa: E402
    CONTAINER,
    CSS,
    build_opf,
    chapter_smil,
    chapter_xhtml,
    nav_doc,
    slice_text,
    source_metadata,
    strip_title_leak,
)
from poc_reader import chunk_text, extract_epub_chapter, list_epub_chapters  # noqa: E402
from shared.audio_clean import THRESH_QUIET, clean_pcm  # noqa: E402
from shared.quota_ledger import add_entry, day_totals  # noqa: E402
from shared.text_preparation import llm_prepare, parse_lines, split_long_narration  # noqa: E402

RATE_DEFAULT = 24000  # Gemini TTS output sample rate

# sysexits EX_TEMPFAIL: a resumable abort, not a crash. Wrapper jobs
# (homelab tts-ch1-3-run.sh) treat 75 as "quota reached, re-run to
# resume" instead of filing a failure issue (issue #21).
EXIT_QUOTA = 75


class QuotaExhausted(RuntimeError):
    """Daily Gemini quota hit mid-run; the run is resumable via the cache."""


def load_env():
    env_path = SCRIPT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def cast_voice(speaker, gender, args):
    """Box-method cast: one Gemini voice per role. The owner's default
    (2026-10-07) is a single voice for everything; --cast restores the
    narration/dialogue role cast."""
    if getattr(args, "single", None) and not getattr(args, "cast", False):
        return args.single
    if speaker is None:
        return args.narrator
    return args.voice_f if gender == "f" else args.voice_m


def prepared_chapter_text(client, args, idx, ch_dir, text):
    """Prepared text for one chapter, reused across runs (issue #17).

    The segment cache is keyed by line text; regenerating the prepared
    text with the LLM rewrites every line, so the cache would never hit
    and each run would re-spend the chapter's full Gemini quota. Reuse
    the stored prepared text when it was produced from the same source
    slice (epub path resolved, chapter, --slice, --max-chars,
    --model-llm, plus a sha1 of the sliced source text so a replaced or
    re-downloaded epub at the same path is detected); the fingerprint
    lives in prepared_meta.txt next to it.
    """
    prepared_file = ch_dir / "prepared_text.txt"
    meta_file = ch_dir / "prepared_meta.txt"
    fingerprint = "|".join(str(x) for x in
                           (Path(args.epub).resolve(), idx, args.slice,
                            args.max_chars, args.model_llm,
                            hashlib.sha1(text.encode()).hexdigest()))
    if (not args.reprepare and prepared_file.exists()
            and meta_file.exists()
            and meta_file.read_text() == fingerprint):
        print("  reusing prepared text from previous run", flush=True)
        return prepared_file.read_text()
    chunks = chunk_text(text, max_chars=args.max_chars)
    prepared_parts = []
    for i, chunk in enumerate(chunks):
        print(f"  preparing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)", flush=True)
        prepared_parts.append(llm_prepare(client, args.model_llm, chunk))
    prepared = "\n\n".join(prepared_parts)
    prepared_file.write_text(prepared)
    meta_file.write_text(fingerprint)
    return prepared


SENTENCE_GAP_MS = 120  # pause between sentences of a split line


def _is_content_filter(exc):
    """True when Gemini's copyright recitation filter blocked the passage.

    The response carries finishReason OTHER and no content (the
    finishMessage names copyrighted material). The block is
    deterministic per passage, so retrying the same text never helps;
    only shorter pieces get through.
    """
    return '"finish_reasons": ["OTHER"]' in str(exc)


def _is_daily_quota(exc):
    """True for a hard daily-quota 429 (issue #23).

    The quota metric name reached us in two formats: the older CamelCase
    GenerateRequestsPerDayPerProjectPerModel and the current snake_case
    generate_requests_per_model_per_day. Matching the literal "PerDay"
    missed the new format, so a daily-quota 429 fell into the per-minute
    backoff branch and surfaced as exit 1 instead of the resumable
    EXIT_QUOTA. Normalize case and separators before matching so both
    formats (and any future spelling of "...per day...") abort at once.
    """
    s = str(exc).lower().replace("_", "").replace(" ", "")
    return "429" in s and "perday" in s


def _quota_abort_message(exc):
    """One-line resumable-abort message, with the API's own retry hint."""
    m = re.search(r"retry in ([\dhms.]+)", str(exc))
    when = (f" The API says: retry in {m.group(1).rstrip('.')}."
            if m else "")
    return ("Gemini daily quota exhausted (hard per-day request limit; "
            "it does not recover within a run)."
            + when
            + " Lines already synthesized are cached; re-run after the "
            "quota resets to resume without re-spending quota.")


def _sentence_pieces(text):
    """Split a line into sentence pieces for the filter fallback."""
    return [s for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s]


async def _request_with_quota_retries(request, max_retries=5):
    """Await request() with the 429 policy shared by every Gemini call.

    Daily-quota 429s do not recover within a run: the per-day limit is
    a hard wall (observed limit: 100 requests/day per model) that resets
    hours later. Retry-backoff only burns ten minutes against it; abort
    at once — cached segments make the run resumable. Per-minute 429s
    are transient and keep the 60-240 s backoff retry.
    """
    for attempt in range(max_retries):
        try:
            return await request()
        except Exception as e:
            if _is_daily_quota(e):
                raise QuotaExhausted(_quota_abort_message(e)) from e
            if "429" in str(e) and attempt < max_retries - 1:
                wait = 60 * (attempt + 1)
                print(f"    429, waiting {wait}s...", flush=True)
                await asyncio.sleep(wait)
            else:
                raise


async def synth_line(eng, voice, text, cache_dir, pace, max_retries=5):
    """Synthesize one line, clean it, cache it. Returns the WAV path.

    Lines blocked by the recitation filter are split into sentences,
    synthesized piece by piece, and stitched back into one cached
    segment (the pieces are cached too, so re-runs resume).
    """
    key = hashlib.sha1(f"{eng.model}|{voice}|{text}".encode()).hexdigest()[:16]
    seg = cache_dir / f"{voice}-{key}.wav"
    if seg.exists() and seg.stat().st_size > 1000:
        return seg
    try:
        res = await _request_with_quota_retries(
            lambda: eng.synthesize(text, voice=voice), max_retries)
    except EngineError as e:
        parts = _sentence_pieces(text)
        if not _is_content_filter(e) or len(parts) < 2:
            raise
        print(f"    recitation filter on line, synthesizing "
              f"{len(parts)} sentences separately", flush=True)
        wavs = [await synth_line(eng, voice, p, cache_dir, pace, max_retries)
                for p in parts]
        wav_bytes, _ = stitch(wavs, SENTENCE_GAP_MS)
        seg.write_bytes(wav_bytes)
        return seg
    with wave.open(io.BytesIO(res.audio)) as w:
        rate, width = w.getframerate(), w.getsampwidth()
        pcm = w.readframes(w.getnframes())
    cleaned = clean_pcm(pcm, width, rate)
    if not cleaned:
        raise RuntimeError(f"empty audio for line: {text[:50]!r}")
    with wave.open(str(seg), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(cleaned)
    await asyncio.sleep(pace)
    return seg


# ── request-efficient batching (issue #25) ─────────────────────────────────
#
# The quota that blocks chapter runs is the per-day REQUEST count (100/day
# on 3.8-flash-tts), not tokens: one request per prepared line spends
# 100+ requests on a single chapter. --lines-per-request N sends up to N
# lines as ONE multi-speaker request (per-line voice casting is kept:
# each line is labeled with its cast voice). The batch's single audio
# take is split back into per-line segments at silence gaps so the
# SMIL offsets stay per-line; when the audio cannot be aligned
# confidently, the batch falls back to per-line synthesis (a few extra
# requests beat silently misaligned highlighting).

# Minimal instruction for 2-voice multi-speaker requests. Single lines
# and 1-voice batches are sent bare (the box method found no style
# prefix best), but a labeled conversation needs the model to treat the
# labels as speaker assignments, not text to read aloud.
BATCH_STYLE = ("Read the conversation aloud, each line in the labeled "
               "speaker's voice. Do not read the labels aloud.")

BATCH_SPLIT_MIN_GAP_MS = 200   # silence run that can act as a line boundary
BATCH_SPLIT_TOLERANCE_S = 1.5  # base max distance expected vs chosen boundary
BATCH_SPLIT_TOLERANCE_FRAC = 0.35  # ...or 35% of the average line duration
BATCH_MIN_SEGMENT_S = 0.25     # a line's audio cannot be shorter than this


def _silence_gaps(pcm, rate):
    """(start, end) sample ranges of silence runs >= BATCH_SPLIT_MIN_GAP_MS.

    10 ms windows whose RMS is at or below audio_clean's THRESH_QUIET,
    mirroring clean_pcm's notion of silence.
    """
    import struct

    win = max(1, rate // 100)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[:len(pcm) // 2 * 2])
    n = len(samples) // win
    min_wins = max(1, BATCH_SPLIT_MIN_GAP_MS // 10)
    gaps, start = [], None
    for i in range(n):
        chunk = samples[i * win:(i + 1) * win]
        rms = (sum(s * s for s in chunk) / win) ** 0.5
        quiet = rms <= THRESH_QUIET
        if quiet and start is None:
            start = i
        elif not quiet and start is not None:
            if i - start >= min_wins:
                gaps.append((start * win, i * win))
            start = None
    if start is not None and n - start >= min_wins:
        gaps.append((start * win, n * win))
    return gaps


def _assign_boundaries(mids, expected):
    """Optimal monotone assignment of line boundaries to silence gaps.

    Picks len(expected) strictly increasing gap midpoints minimizing the
    total distance to the expected positions (boundaries must stay in
    reading order). Returns the chosen gap indices, or None when there
    are fewer gaps than boundaries.
    """
    m, k = len(mids), len(expected)
    if m < k:
        return None
    inf = float("inf")
    # dp[i][j]: boundary j at gap i, boundaries 0..j on gaps 0..i-1
    dp = [[inf] * k for _ in range(m)]
    parent = [[-1] * k for _ in range(m)]
    for i in range(m):
        dp[i][0] = abs(mids[i] - expected[0])
        for j in range(1, k):
            best, best_i = inf, -1
            for i2 in range(i):
                if dp[i2][j - 1] < best:
                    best, best_i = dp[i2][j - 1], i2
            if best < inf:
                dp[i][j] = abs(mids[i] - expected[j]) + best
                parent[i][j] = best_i
    total, last = inf, -1
    for i in range(m):
        if dp[i][k - 1] < total:
            total, last = dp[i][k - 1], i
    if last < 0:
        return None
    chosen = [0] * k
    i, j = last, k - 1
    while j >= 0:
        chosen[j] = i
        i = parent[i][j]
        j -= 1
    return chosen


def split_batch_pcm(pcm, width, rate, char_weights):
    """Split a batch's cleaned PCM into one chunk per line, or None.

    Boundary candidates are the silence gaps between lines; each boundary
    is placed at the gap closest to the position proportional to
    cumulative text length (speech time tracks text length closely
    enough for this). Returns None when no confident split exists —
    the caller then falls back to per-line synthesis rather than emit
    misaligned SMIL offsets.
    """
    if width != 2 or len(char_weights) < 2 or not char_weights:
        return None
    gaps = _silence_gaps(pcm, rate)
    k = len(char_weights) - 1
    if len(gaps) < k:
        return None
    total_chars = sum(char_weights)
    total_frames = len(pcm) // 2
    expected = [total_frames * sum(char_weights[:j + 1]) / total_chars
                for j in range(k)]
    mids = [(s + e) // 2 for s, e in gaps]
    chosen = _assign_boundaries(mids, expected)
    if chosen is None:
        return None
    avg_line_s = (total_frames / rate) / len(char_weights)
    tol = rate * max(BATCH_SPLIT_TOLERANCE_S,
                     BATCH_SPLIT_TOLERANCE_FRAC * avg_line_s)
    min_frames = rate * BATCH_MIN_SEGMENT_S
    bounds = []
    for j, gi in enumerate(chosen):
        if abs(mids[gi] - expected[j]) > tol:
            return None
        bounds.append(mids[gi])
    chunks, prev = [], 0
    for b in bounds + [total_frames]:
        if b - prev < min_frames:
            return None
        chunks.append(pcm[prev * 2:b * 2])
        prev = b
    return chunks


def _batch_key(eng, batch):
    """Cache key for one batch (model + every line's voice and text)."""
    joined = "|".join(f"{v}|{t}" for v, t in batch)
    return hashlib.sha1(f"{eng.model}|{joined}".encode()).hexdigest()[:16]


def _per_line_seg(cache_dir, eng, voice, text):
    """The per-line cache path for one line (same key synth_line uses)."""
    key = hashlib.sha1(f"{eng.model}|{voice}|{text}".encode()).hexdigest()[:16]
    return cache_dir / f"{voice}-{key}.wav"


def _split_batch_by_voices(batch):
    """Split a batch into sub-batches the API can take in one request.

    Multi-speaker requests allow at most 2 distinct voices (the API
    requires exactly 2 speaker_voice_configs; a 1-voice sub-batch is
    sent as a plain single-voice request). Lines keep their order.
    """
    subs, cur, cur_voices = [], [], set()
    for voice, text in batch:
        if cur and voice not in cur_voices and len(cur_voices) == 2:
            subs.append(cur)
            cur, cur_voices = [], set()
        cur.append((voice, text))
        cur_voices.add(voice)
    if cur:
        subs.append(cur)
    return subs


async def synth_batch(eng, batch, cache_dir, pace, max_retries=5):
    """Synthesize up to N lines in ONE request per voice-compatible
    group. Returns a WAV path per line, in batch order.

    batch: [(voice, text)] in reading order. Keeps the per-line
    guarantees of synth_line: per-line voice casting (multi-speaker
    requests for 2-voice groups, plain requests for 1-voice groups),
    per-batch cache keys (resumable), the recitation-filter
    sentence-splitting and exit-75 quota behavior (both via per-line
    fallback), and re-use of segments already paid for in earlier
    per-line runs (a fully per-line-cached batch is stitched from the
    per-line cache without a new request).
    """
    seg_files = []
    for sub in _split_batch_by_voices(batch):
        seg_files.extend(await _synth_subbatch(eng, sub, cache_dir, pace,
                                               max_retries))
    return seg_files


async def _synth_subbatch(eng, sub, cache_dir, pace, max_retries=5):
    """One request for one voice-compatible group of lines."""
    if len(sub) == 1:
        voice, text = sub[0]
        return [await synth_line(eng, voice, text, cache_dir, pace, max_retries)]
    key = _batch_key(eng, sub)
    split_files = [cache_dir / f"batch-{key}-{i:03d}.wav"
                   for i in range(len(sub))]
    if all(p.exists() and p.stat().st_size > 1000 for p in split_files):
        return split_files
    cached = [_per_line_seg(cache_dir, eng, v, t) for v, t in sub]
    if all(p.exists() and p.stat().st_size > 1000 for p in cached):
        print("    batch fully cached per-line from earlier runs", flush=True)
        return cached
    voices = {v for v, _t in sub}
    # A labeled 2-voice conversation needs the instruction; a plain
    # 1-voice group is sent bare, like the box method (issue #25).
    style = BATCH_STYLE if len(voices) == 2 else ""
    try:
        res = await _request_with_quota_retries(
            lambda: eng.synthesize_multi(list(sub), style=style),
            max_retries)
    except EngineError as e:
        if not _is_content_filter(e):
            raise
        print(f"    recitation filter on batch, synthesizing "
              f"{len(sub)} lines separately", flush=True)
        return [await synth_line(eng, v, t, cache_dir, pace, max_retries)
                for v, t in sub]
    with wave.open(io.BytesIO(res.audio)) as w:
        rate, width = w.getframerate(), w.getsampwidth()
        pcm = w.readframes(w.getnframes())
    cleaned = clean_pcm(pcm, width, rate)
    if not cleaned:
        raise RuntimeError("empty audio for batch")
    chunks = split_batch_pcm(cleaned, width, rate, [len(t) for _v, t in sub])
    if chunks is None:
        print("    batch audio cannot be aligned to lines, "
              "synthesizing lines separately", flush=True)
        return [await synth_line(eng, v, t, cache_dir, pace, max_retries)
                for v, t in sub]
    for path, chunk in zip(split_files, chunks):
        with wave.open(str(path), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(width)
            w.setframerate(rate)
            w.writeframes(chunk)
    await asyncio.sleep(pace)
    return split_files


def stitch(segments, gap_ms):
    """Concatenate cleaned segments with a silence gap.

    Returns (wav_bytes, offsets) where wav_bytes is a complete WAV
    (RIFF header, mono, rate/width taken from the segments themselves —
    the engine can return rates other than 24 kHz, and a hardcoded
    header would play at the wrong speed and desync every SMIL offset)
    and offsets are (start, end) second pairs per segment, excluding
    the trailing gap.
    """
    rate, width, gap = RATE_DEFAULT, 2, b""
    frames, offsets, t = [], [], 0.0
    for i, seg in enumerate(segments):
        with wave.open(str(seg)) as w:
            seg_rate, seg_width = w.getframerate(), w.getsampwidth()
            if i == 0:
                rate, width = seg_rate, seg_width
                gap = b"\x00" * (rate * width * gap_ms // 1000)
            elif (seg_rate, seg_width) != (rate, width):
                # Concatenating mixed-format PCM cannot produce a valid
                # single-header WAV; fail loudly instead of corrupting
                # the audio and every SMIL offset.
                raise ValueError(
                    f"segment {seg} is {seg_rate} Hz / {seg_width}-byte, "
                    f"expected {rate} Hz / {width}-byte: refusing to "
                    "stitch mixed-format segments")
            data = w.readframes(w.getnframes())
        dur = len(data) / (rate * width)
        offsets.append((t, t + dur))
        frames.append(data)
        frames.append(gap)
        t += dur + gap_ms / 1000.0
    out = io.BytesIO()
    with wave.open(out, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"".join(frames))
    return out.getvalue(), offsets


def to_mp3(wav_bytes):
    from pydub import AudioSegment
    audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
    out = io.BytesIO()
    audio.export(out, format="mp3")
    return out.getvalue()


def plan_batch_chars(args, chapter_segments):
    """Owner request-split policy (2026-10-07): spread the whole
    required text over the daily request budget — default 90 of the
    observed 100/day free-tier limit, keeping the remainder as margin
    for ad-hoc daily tests — so each request carries total_chars /
    budget characters and a full read takes at most `budget` requests.

    Returns the per-request character target, or None when batching is
    not wanted (--lines-per-request set, or --daily-requests 0 = the
    per-line box method). The target is capped by --max-request-chars;
    when the cap bites, the run needs more than `budget` requests and
    resumes across days via the cache + exit-75 quota abort.
    """
    if getattr(args, "lines_per_request", None):
        return None
    budget = getattr(args, "daily_requests", 0) or 0
    if budget <= 0:
        return None
    total = sum(len(t) for segs in chapter_segments.values()
                for _s, _g, t, _v, _vn in segs)
    if not total:
        return None
    per_request = -(-total // budget)  # ceil(total / budget)
    return max(1, min(per_request, args.max_request_chars))


def pack_batches_by_chars(segments, batch_chars):
    """Group consecutive lines into batches of at most batch_chars
    characters (a single longer line becomes its own batch)."""
    batches, current, size = [], [], 0
    for seg in segments:
        line_len = len(seg[2]) + 1  # +1: the newline joining batch lines
        if current and size + line_len > batch_chars:
            batches.append(current)
            current, size = [], 0
        current.append(seg)
        size += line_len
    if current:
        batches.append(current)
    return batches


def prepare_chapter(client, args, idx, work_dir):
    """Prepare one chapter's segments: extract, LLM-prepare (cached),
    parse lines, cast voices. Runs before the first Gemini request so
    the batch size can be computed over the whole required text."""
    ch_id = f"ch{idx:03d}"
    ch_dir = work_dir / ch_id
    ch_dir.mkdir(parents=True, exist_ok=True)
    book_title, _creator = source_metadata(args.epub)
    text = strip_title_leak(
        slice_text(extract_epub_chapter(args.epub, idx), args.slice), book_title)
    prepared = prepared_chapter_text(client, args, idx, ch_dir, text)
    lines = split_long_narration(parse_lines(prepared))
    return [(s, g, t, cast_voice(s, g, args), cast_voice(s, g, args))
            for s, g, t in lines]


async def process_chapter(client, args, idx, work_dir, eng,
                          segments=None, batch_chars=None):
    ch_id = f"ch{idx:03d}"
    ch_dir = work_dir / ch_id
    cache_dir = work_dir / "gemini_segments" / args.model.replace(".", "_")
    ch_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if segments is None:
        segments = prepare_chapter(client, args, idx, work_dir)
    cast = {}
    for _s, _g, _t, v, _vn in segments:
        cast[v] = cast.get(v, 0) + 1
    print(f"  {len(segments)} lines: " + ", ".join(f"{k} x{v}" for k, v in cast.items()),
          flush=True)

    npr = getattr(args, "lines_per_request", None) or 0
    if npr > 1:
        batches = [segments[i:i + npr] for i in range(0, len(segments), npr)]
        mode = f"fixed {npr} lines/request"
    elif batch_chars:
        batches = pack_batches_by_chars(segments, batch_chars)
        mode = f"auto-sized, <= {batch_chars} chars/request"
    else:
        batches = None
    if batches is not None:
        print(f"  synthesizing with Gemini (batched, {mode})...", flush=True)
        seg_files = []
        first = 0
        for bi, b in enumerate(batches):
            turns = [(voice, text_line)
                     for _s, _g, text_line, voice, _vn in b]
            paths = await synth_batch(eng, turns, cache_dir, args.pace)
            seg_files.extend(paths)

            voices = "/".join(sorted({v for v, _t in turns}))
            print(f"    batch {bi + 1:02d}/{len(batches)} "
                  f"lines {first:03d}-{first + len(b) - 1:03d} "
                  f"[{voices}] done", flush=True)
            first += len(b)
    else:
        print("  synthesizing with Gemini (box method)...", flush=True)
        seg_files = []
        for i, (s, _g, text_line, voice, _vn) in enumerate(segments):
            path = await synth_line(eng, voice, text_line, cache_dir, args.pace)
            seg_files.append(path)
            print(f"    line {i:03d} [{s or 'narr'} -> {voice}] done", flush=True)

    wav_bytes, offsets = stitch(seg_files, args.gap_ms)
    (ch_dir / "audio.wav").write_bytes(wav_bytes)
    audio = to_mp3(wav_bytes)
    duration = offsets[-1][1] if offsets else 0.0
    print(f"  audio: {duration:.1f}s ({clock_value(duration)})", flush=True)

    title = f"Capitolo {idx + 1}"
    return {
        "ch_id": ch_id,
        "title": title,
        "xhtml": chapter_xhtml(title, segments),
        "smil": chapter_smil(ch_id, offsets),
        "audio": audio,
        "duration": duration,
    }


def run_generation(run, on_finish=None):
    """Await the generation, converting a resumable quota abort into a
    clean one-line message and exit code EXIT_QUOTA (75) instead of a
    traceback and exit 1 — wrappers must be able to tell "re-run
    tomorrow" apart from a real failure (issue #21). on_finish runs on
    every exit path (including the quota abort and real failures): a
    run that spent requests updates the quota ledger even when it does
    not finish (issue #25)."""
    try:
        asyncio.run(run())
    except QuotaExhausted as e:
        print(f"\nQUOTA EXHAUSTED (resumable, exit code {EXIT_QUOTA}): {e}",
              flush=True)
        print("Re-run after the quota reset to resume; "
              "cached lines are not re-spent.", flush=True)
        sys.exit(EXIT_QUOTA)
    finally:
        if on_finish:
            on_finish()


# Approach presets (issue #26): one flag that expands to the underlying
# --lines-per-request. Values are the lines-per-request each preset
# means; see docs/REQUEST_EFFICIENCY.md for the measured tradeoffs.
PRESETS = {
    # Per-line box method: best prosody (each line a fresh, self-contained
    # delivery), exact SMIL offsets, one request per line — the slowest
    # against the per-day request quota.
    "quality": 1,
    # The measured recommendation: half the 100/day budget for a 513-line
    # run, alignment error measured acceptable (docs/REQUEST_EFFICIENCY.md).
    "balanced": 10,
    # Aggressive batching: fewest requests; the most exposure to batch
    # alignment drift and the read timeout on long batches.
    "fast": 20,
}


def apply_preset(args):
    """Expand --preset into the batching knobs (issue #26).

    An explicit --lines-per-request wins over the preset's value.
    Returns the expansion line to print in the run log, or None when
    no preset was given. Without a preset nothing is touched: the
    default stays the owner's --daily-requests auto-sizing (2026-10-07,
    issue #25) — lines_per_request None lets plan_batch_chars size
    requests from the daily budget.
    """
    if args.preset is None:
        return None
    if args.lines_per_request is None:
        args.lines_per_request = PRESETS[args.preset]
    if args.preset == "quality":
        # 1 line/request is indistinguishable from auto-sizing to the
        # batching logic (a falsy lines_per_request falls through to
        # plan_batch_chars), so the box method needs the budget off.
        args.daily_requests = 0
    return f"preset: {args.preset} -> --lines-per-request {args.lines_per_request}"


def main():
    parser = argparse.ArgumentParser(
        description="gemini_readaloud: read-along EPUB with Gemini TTS")
    parser.add_argument("--epub", help="Path to the source EPUB")
    parser.add_argument("--chapter", type=int, help="Chapter index (see --list-chapters)")
    parser.add_argument("--all", action="store_true", help="Process all chapters")
    parser.add_argument("--slice", type=int, help="Max source chars per chapter (test mode)")
    parser.add_argument("--output", help="Output EPUB path")
    parser.add_argument("--work-dir", default="out/gemini_readaloud_work")
    parser.add_argument("--model", default="gemini-3.8-flash-lite-tts",
                        help="Gemini TTS model (default %(default)s; owner "
                             "decision 2026-10-07)")
    parser.add_argument("--model-llm", default="mistral-large-latest",
                        help="Mistral model for text preparation")
    parser.add_argument("--max-chars", type=int, default=4000)
    parser.add_argument("--narrator", default="Kore", help="Narration voice "
                        "(--cast mode only)")
    parser.add_argument("--voice-m", default="Rami", help="Male dialogue "
                        "voice (--cast mode only)")
    parser.add_argument("--voice-f", default="Leda", help="Female dialogue "
                        "voice (--cast mode only)")
    parser.add_argument("--single", default="Rami",
                        help="One voice for everything (default %(default)s; "
                             "owner decision 2026-10-07)")
    parser.add_argument("--cast", action="store_true",
                        help="Use the narration/dialogue cast instead of "
                             "the single voice")
    parser.add_argument("--pace", type=float, default=7.0,
                        help="Seconds between Gemini requests (free-tier pacing)")
    parser.add_argument("--gap-ms", type=int, default=250,
                        help="Silence gap between lines in ms")
    parser.add_argument("--reprepare", action="store_true",
                        help="Regenerate the prepared text even if cached "
                             "(cached segments for old lines are not "
                             "deleted)")
    parser.add_argument("--lines-per-request", type=int, default=None,
                        help="Batch exactly N prepared lines into one "
                             "Gemini request; overrides --daily-requests "
                             "auto-sizing")
    parser.add_argument("--daily-requests", type=int, default=90,
                        help="Auto-size requests so the whole required "
                             "text takes at most N requests: each carries "
                             "total_chars/N chars, capped by "
                             "--max-request-chars (default %(default)s of "
                             "the observed 100/day free-tier limit, "
                             "keeping the remainder as margin for ad-hoc "
                             "daily tests; 0 = one request per line)")
    parser.add_argument("--max-request-chars", type=int, default=2000,
                        help="Per-request character cap for "
                             "--daily-requests sizing (default %(default)s)")

    parser.add_argument("--preset", choices=sorted(PRESETS), default=None,
                        help="Approach preset (issue #26): expands to "
                             "--lines-per-request (quality=1 box method, "
                             "balanced=10, fast=20); an explicit "
                             "--lines-per-request wins")
    parser.add_argument("--quota-ledger",
                        default=str(SCRIPT_DIR / "out" / "quota_ledger.json"),
                        help="Quota ledger this run's requests/tokens are "
                             "appended to (issue #25)")
    parser.add_argument("--list-chapters", action="store_true")
    args = parser.parse_args()

    expansion = apply_preset(args)
    if expansion:
        print(expansion, flush=True)

    if not args.epub:
        print("ERROR: --epub is required")
        sys.exit(1)

    chapters = list_epub_chapters(args.epub)
    if args.list_chapters:
        for i, fname, size, first in chapters:
            print(f"  [{i:2d}] {size:>7} chars  {first}")
        return

    if args.all:
        indices = [i for i, _f, _s, _t in chapters]
    elif args.chapter is not None:
        if args.chapter < 0 or args.chapter >= len(chapters):
            print(f"ERROR: chapter index {args.chapter} out of range (0-{len(chapters) - 1})")
            sys.exit(1)
        indices = [args.chapter]
    else:
        print("ERROR: provide --chapter N, --all, or --list-chapters")
        sys.exit(1)
    if not args.output:
        print("ERROR: --output is required for generation")
        sys.exit(1)

    load_env()
    if not os.environ.get("MISTRAL_API_KEY"):
        print("ERROR: MISTRAL_API_KEY not set (env or .env)")
        sys.exit(1)
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not set (env or .env)")
        sys.exit(1)

    try:
        from mistralai import Mistral
    except ImportError:  # mistralai 2.x: client moved off the top level
        from mistralai.client import Mistral
    import httpx
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    files = {"META-INF/container.xml": CONTAINER, "styles.css": CSS}
    chapter_ids, durations = [], {}
    t0 = time.time()
    eng_holder = {}

    # 120 s read timeout: 3.8 responses for ~300-char lines can exceed 30 s
    async def run():
        async with httpx.AsyncClient(timeout=120.0) as hc:
            eng = GeminiTTSEngine(model=args.model, style="", client=hc)
            eng_holder["eng"] = eng
            # Pass 1: prepare every chapter (cached) BEFORE the first
            # Gemini request, so the batch size covers the whole
            # required text (owner policy: total_chars / daily budget).
            chapter_segments = {}
            for idx in indices:
                chapter_segments[idx] = prepare_chapter(
                    client, args, idx, work_dir)
            batch_chars = plan_batch_chars(args, chapter_segments)
            if batch_chars:
                total = sum(len(t) for segs in chapter_segments.values()
                            for _s, _g, t, _v, _vn in segs)
                est = -(-total // batch_chars)
                print(f"  request plan: {total} chars -> ~{est} requests "
                      f"(budget {args.daily_requests}/day, "
                      f"cap {args.max_request_chars} chars/request)",
                      flush=True)
            for idx in indices:
                print(f"\n=== Chapter {idx} ===", flush=True)
                result = await process_chapter(client, args, idx, work_dir,
                                               eng, chapter_segments[idx],
                                               batch_chars)
                ch = result["ch_id"]
                files[f"{ch}.xhtml"] = result["xhtml"]
                files[f"{ch}.smil"] = result["smil"]
                files[f"audio/{ch}.mp3"] = result["audio"]
                chapter_ids.append(ch)
                durations[ch] = result["duration"]

    def record_usage():
        """Append this run's measured requests/tokens to the quota ledger
        (issue #25) — also on the quota-abort and failure paths, because
        those requests were spent too."""
        eng = eng_holder.get("eng")
        if eng is None or not (eng.request_count or eng.token_count):
            return
        entry = add_entry(args.quota_ledger, model=args.model,
                          run_id=time.strftime("%Y-%m-%dT%H:%M:%S"),
                          requests=eng.request_count,
                          tokens=eng.token_count)
        totals = day_totals(args.quota_ledger, model=args.model)
        print(f"  quota: {entry['requests']} requests, "
              f"{entry['tokens']} tokens this run; "
              f"{totals['requests']} requests today for {args.model} "
              f"(ledger: {args.quota_ledger})", flush=True)

    run_generation(run, on_finish=record_usage)

    title, creator = source_metadata(args.epub)
    files["nav.xhtml"] = nav_doc(
        [(ch, f"Capitolo {i + 1}") for i, ch in zip(indices, chapter_ids)])
    files["content.opf"] = build_opf(f"{title} (lettura)", creator, chapter_ids, durations)

    print(f"\nPackaging {out_path}...", flush=True)
    with zipfile.ZipFile(out_path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        for name, data in files.items():
            z.writestr(name, data, zipfile.ZIP_DEFLATED)

    errors = validate(out_path)
    total = sum(durations.values())
    print(f"\n{'=' * 60}")
    print(f"DONE in {time.time() - t0:.0f}s -> {out_path}")
    print(f"  chapters: {len(chapter_ids)}, total audio: {clock_value(total)}")
    if errors:
        print(f"  VALIDATION ERRORS ({len(errors)}):")
        for e in errors[:20]:
            print(f"    - {e}")
        sys.exit(1)
    print("  validation: OK")
    print("  NOTE: Apple Books ignores Media Overlays; test in Thorium Reader.")


if __name__ == "__main__":
    main()
