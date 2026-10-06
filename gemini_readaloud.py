#!/usr/bin/env python3
"""gemini_readaloud: read-along EPUB with Gemini TTS (box method).

Same output contract as epub_readaloud.py (prepared text as content, one
SMIL-synced paragraph per line), but synthesis goes through the Gemini
TTS engine one line at a time — the "box" method validated in
out/voice_tests: short requests, no style prefix, per-line voices.

Every line's audio is cleaned (shared/audio_clean.py: the 3.8 end-of-
response noise burst and start click are trimmed, edges faded) and
cached under the work dir, so runs are resumable: re-running skips
everything already synthesized and only spends quota on new lines.
The prepared text is cached too and reused verbatim on re-runs (issue
#17): LLM preparation is non-deterministic, so regenerating it would
rewrite every line, invalidate the whole segment cache and re-spend
the chapter's Gemini quota on every run — a quota-limited run could
never finish. --reprepare forces regeneration.

Usage:
  python3 gemini_readaloud.py --epub book.epub --list-chapters
  python3 gemini_readaloud.py --epub book.epub --chapter 3 --slice 1200 \
      --single Kore --output out/slice.epub
  python3 gemini_readaloud.py --epub book.epub --all --output out/book.epub

Cast (default): narration Kore, male dialogue Rami, female dialogue
Leda. --single VOICE reads everything with one voice.

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
from shared.audio_clean import clean_pcm  # noqa: E402
from shared.text_preparation import llm_prepare, parse_lines, split_long_narration  # noqa: E402

RATE_DEFAULT = 24000  # Gemini TTS output sample rate


def load_env():
    env_path = SCRIPT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def cast_voice(speaker, gender, args):
    """Box-method cast: one Gemini voice per role."""
    if args.single:
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


def _sentence_pieces(text):
    """Split a line into sentence pieces for the filter fallback."""
    return [s for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s]


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
        for attempt in range(max_retries):
            try:
                res = await eng.synthesize(text, voice=voice)
                break
            except Exception as e:
                # Daily-quota 429s ("...PerDayPerProjectPerModel..." in the
                # error body) do not recover within a run: the free tier is a
                # hard ~10 requests/day per model. Retry-backoff only burns
                # ten minutes against a wall that resets at midnight Pacific;
                # abort at once — cached segments make the run resumable.
                if "429" in str(e) and "PerDay" in str(e):
                    raise RuntimeError(
                        "Gemini daily quota exhausted (free tier: hard "
                        "~10 requests/day per model). Lines already "
                        "synthesized are cached; re-run tomorrow to resume "
                        "without re-spending quota.") from e
                if "429" in str(e) and attempt < max_retries - 1:
                    wait = 60 * (attempt + 1)
                    print(f"    429 ({voice}), waiting {wait}s...", flush=True)
                    await asyncio.sleep(wait)
                else:
                    raise
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


async def process_chapter(client, args, idx, work_dir, eng):
    ch_id = f"ch{idx:03d}"
    ch_dir = work_dir / ch_id
    cache_dir = work_dir / "gemini_segments" / args.model.replace(".", "_")
    ch_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    book_title, _creator = source_metadata(args.epub)
    text = strip_title_leak(
        slice_text(extract_epub_chapter(args.epub, idx), args.slice), book_title)
    prepared = prepared_chapter_text(client, args, idx, ch_dir, text)

    lines = split_long_narration(parse_lines(prepared))
    segments = [(s, g, t, cast_voice(s, g, args), cast_voice(s, g, args))
                for s, g, t in lines]
    cast = {}
    for _s, _g, _t, v, _vn in segments:
        cast[v] = cast.get(v, 0) + 1
    print(f"  {len(segments)} lines: " + ", ".join(f"{k} x{v}" for k, v in cast.items()),
          flush=True)

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


def main():
    parser = argparse.ArgumentParser(
        description="gemini_readaloud: read-along EPUB with Gemini TTS")
    parser.add_argument("--epub", help="Path to the source EPUB")
    parser.add_argument("--chapter", type=int, help="Chapter index (see --list-chapters)")
    parser.add_argument("--all", action="store_true", help="Process all chapters")
    parser.add_argument("--slice", type=int, help="Max source chars per chapter (test mode)")
    parser.add_argument("--output", help="Output EPUB path")
    parser.add_argument("--work-dir", default="out/gemini_readaloud_work")
    parser.add_argument("--model", default="gemini-3.8-flash-tts",
                        help="Gemini TTS model (default %(default)s)")
    parser.add_argument("--model-llm", default="mistral-large-latest",
                        help="Mistral model for text preparation")
    parser.add_argument("--max-chars", type=int, default=4000)
    parser.add_argument("--narrator", default="Kore", help="Narration voice")
    parser.add_argument("--voice-m", default="Rami", help="Male dialogue voice")
    parser.add_argument("--voice-f", default="Leda", help="Female dialogue voice")
    parser.add_argument("--single", help="One voice for everything (overrides cast)")
    parser.add_argument("--pace", type=float, default=7.0,
                        help="Seconds between Gemini requests (free-tier pacing)")
    parser.add_argument("--gap-ms", type=int, default=250,
                        help="Silence gap between lines in ms")
    parser.add_argument("--reprepare", action="store_true",
                        help="Regenerate the prepared text even if cached "
                             "(cached segments for old lines are not "
                             "deleted)")
    parser.add_argument("--list-chapters", action="store_true")
    args = parser.parse_args()

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

    # 120 s read timeout: 3.8 responses for ~300-char lines can exceed 30 s
    async def run():
        async with httpx.AsyncClient(timeout=120.0) as hc:
            eng = GeminiTTSEngine(model=args.model, style="", client=hc)
            for idx in indices:
                print(f"\n=== Chapter {idx} ===", flush=True)
                result = await process_chapter(client, args, idx, work_dir, eng)
                ch = result["ch_id"]
                files[f"{ch}.xhtml"] = result["xhtml"]
                files[f"{ch}.smil"] = result["smil"]
                files[f"audio/{ch}.mp3"] = result["audio"]
                chapter_ids.append(ch)
                durations[ch] = result["duration"]

    asyncio.run(run())

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
