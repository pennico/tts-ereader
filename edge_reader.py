#!/usr/bin/env python3
"""edge_reader: LLM-prepared, edge-tts-synthesized reading pipeline.

Text -> [Mistral LLM: clean OCR/spelling errors + repunctuate for speech
         + tag dialogue speakers with gender]
     -> prepared lines -> [voice cast] -> edge-tts per line
     -> poc_output.mp3 + poc_manifest.json (compatible with poc_player.html)

Voice cast (Italian):
  narrator / male characters      -> it-IT-GiuseppeMultilingualNeural
  first female character          -> fr-FR-VivienneMultilingualNeural
  other female characters         -> en-US-EmmaMultilingualNeural
  (--andrew-short) one-line, very short male side roles
                                  -> en-US-AndrewMultilingualNeural

Usage:
  python3 edge_reader.py --file sample.txt --output-dir out/saramago_edge
  python3 edge_reader.py --epub book.epub --list-chapters
  python3 edge_reader.py --epub book.epub --chapter 4 --output-dir out/ch4

Requires: MISTRAL_API_KEY (env or .env in the script directory), edge-tts,
pydub, ffmpeg.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import edge_tts
try:
    from mistralai import Mistral
except ImportError:  # mistralai 2.x: client moved off the top level
    from mistralai.client import Mistral
from pydub import AudioSegment

from poc_reader import chunk_text, extract_epub_chapter, list_epub_chapters

# Shared preparation + voice-cast logic (M3, AC-803): the canonical code lives
# in shared/ and is reused by the v1 app; the v0 CLI surface is unchanged.
from shared.text_preparation import llm_prepare, parse_lines, split_long_narration
from shared.voice_cast import (
    CAST_EDGE_IT,
    ROLE_FEMALE_1,
    ROLE_FEMALE_OTHER,
    ROLE_MALE_SHORT,
    ROLE_NARRATOR,
    assign_voices as _assign_voices,
)

SCRIPT_DIR = Path(__file__).resolve().parent

LLM_MODEL_DEFAULT = "mistral-large-latest"
RATE_DEFAULT = "-8%"
WORKERS_DEFAULT = 4  # concurrent edge-tts requests (edge-tts is free; be polite)
GAP_SAME_MS = 250    # silence between consecutive lines of the same voice
GAP_SWITCH_MS = 600  # silence at a voice change

# v0 voice cast (Italian, edge-tts) — kept as module constants for callers.
VOICE_NARRATOR, VOICE_FEMALE_1, VOICE_FEMALE_2, VOICE_SHORT_MALE = (
    CAST_EDGE_IT[ROLE_NARRATOR][0],
    CAST_EDGE_IT[ROLE_FEMALE_1][0],
    CAST_EDGE_IT[ROLE_FEMALE_OTHER][0],
    CAST_EDGE_IT[ROLE_MALE_SHORT][0],
)


def assign_voices(lines, andrew_short=False):
    """Two-pass voice assignment. Returns list of (speaker, gender, text, voice, voice_name)."""  # noqa: E501
    return _assign_voices(lines, cast=CAST_EDGE_IT, andrew_short=andrew_short)


def load_env():
    """Load MISTRAL_API_KEY from SCRIPT_DIR/.env if not already set."""
    if os.environ.get("MISTRAL_API_KEY"):
        return
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("MISTRAL_API_KEY="):
                os.environ["MISTRAL_API_KEY"] = line.split("=", 1)[1].strip()


async def synthesize(segments, output_dir, rate, workers=WORKERS_DEFAULT):
    """Synthesize lines with edge-tts, up to `workers` requests in flight.

    Returns list of (path, voice_name) in segment order — the order is what
    concatenate() builds its offsets from, so it must not change.
    """
    sem = asyncio.Semaphore(max(1, workers))

    async def synth_one(i, speaker, _gender, text, voice, voice_name):
        seg_path = output_dir / f"seg_{i:03d}.mp3"
        for attempt in range(3):
            try:
                async with sem:
                    communicate = edge_tts.Communicate(text, voice, rate=rate)
                    await communicate.save(str(seg_path))
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ERROR synthesizing segment {i}: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)
        tag = speaker or "narrator"
        print(f"  [{i:03d}] {tag:>14} -> {voice_name}")
        return (seg_path, voice_name)

    return list(await asyncio.gather(
        *(synth_one(i, *seg) for i, seg in enumerate(segments))))


def concatenate(files, output_mp3):
    """Join segment files with silence gaps; return (start, end) offsets in seconds."""
    final = AudioSegment.empty()
    offsets = []
    prev_voice = None
    for path, voice_name in files:
        seg = AudioSegment.from_file(str(path), format="mp3")
        gap_ms = GAP_SWITCH_MS if prev_voice != voice_name else GAP_SAME_MS
        if len(final) == 0:
            gap_ms = 0
        final += AudioSegment.silent(duration=gap_ms)
        start = len(final) / 1000.0
        final += seg
        offsets.append((start, len(final) / 1000.0))
        prev_voice = voice_name
    final.export(str(output_mp3), format="mp3")
    return offsets


def main():
    parser = argparse.ArgumentParser(description="edge_reader: LLM-prepared edge-tts readings")
    parser.add_argument("--text", help="Custom text to process")
    parser.add_argument("--file", help="Path to a text file to process")
    parser.add_argument("--epub", help="Path to an EPUB file")
    parser.add_argument("--chapter", type=int, help="Chapter index in the EPUB")
    parser.add_argument("--list-chapters", action="store_true", help="List EPUB chapters")
    parser.add_argument("--label", default="edge reading", help="Label for the manifest")
    parser.add_argument("--output-dir", default="out/edge", help="Output directory")
    parser.add_argument("--rate", default=RATE_DEFAULT, help="edge-tts rate, e.g. -8%% (default)")
    parser.add_argument("--workers", type=int, default=WORKERS_DEFAULT,
                        help="Concurrent edge-tts requests (default %(default)s)")
    parser.add_argument("--model", default=LLM_MODEL_DEFAULT, help="Mistral model for preparation")
    parser.add_argument("--max-chars", type=int, default=4000, help="Max chars per LLM chunk")
    parser.add_argument("--andrew-short", action="store_true",
                        help="Use Andrew for one-line, very short male side roles")
    args = parser.parse_args()

    load_env()
    if not os.environ.get("MISTRAL_API_KEY"):
        print("ERROR: MISTRAL_API_KEY not set (env or .env). Get one at https://console.mistral.ai")
        sys.exit(1)

    if args.list_chapters:
        if not args.epub:
            print("ERROR: --list-chapters requires --epub")
            sys.exit(1)
        for i, fname, size, first in list_epub_chapters(args.epub):
            print(f"  [{i:2d}] {size:>7} chars  {first}")
        return

    if args.epub:
        if args.chapter is None:
            print("ERROR: --epub requires --chapter (or --list-chapters)")
            sys.exit(1)
        text = extract_epub_chapter(args.epub, args.chapter)
    elif args.file:
        text = Path(args.file).read_text()
    elif args.text:
        text = args.text
    else:
        print("ERROR: provide --text, --file, or --epub + --chapter")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    # Step 1: LLM preparation per chunk
    chunks = chunk_text(text, max_chars=args.max_chars)
    print(f"Preparing {len(text)} chars in {len(chunks)} chunk(s) with {args.model}...")
    prepared_parts = []
    for i, chunk in enumerate(chunks):
        print(f"  chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        prepared_parts.append(llm_prepare(client, args.model, chunk))
    prepared = "\n\n".join(prepared_parts)
    (output_dir / "prepared_text.txt").write_text(prepared)
    print(f"Saved prepared text: {output_dir / 'prepared_text.txt'}")

    # Step 2: parse lines, split long narration, assign voices
    lines = split_long_narration(parse_lines(prepared))
    segments = assign_voices(lines, andrew_short=args.andrew_short)
    print(f"\n{len(segments)} lines to synthesize:")
    cast = {}
    for _, _, _, voice, voice_name in segments:
        cast[voice_name] = cast.get(voice_name, 0) + 1
    print("  cast: " + ", ".join(f"{name} x{n}" for name, n in cast.items()))

    # Step 3: synthesize
    print("\nSynthesizing with edge-tts...")
    files = asyncio.run(synthesize(segments, output_dir, args.rate, args.workers))

    # Step 4: concatenate + manifest
    output_mp3 = output_dir / "poc_output.mp3"
    offsets = concatenate(files, output_mp3)
    print(f"\nConcatenated {len(files)} segments -> {output_mp3}")

    manifest = {
        "audio": "poc_output.mp3",
        "sample": args.label,
        "style": "edge-hybrid",
        "language": "it",
        "total_segments": len(segments),
        "segments": [],
    }
    for i, ((speaker, gender, text, voice, voice_name), (start, end)) in enumerate(zip(segments, offsets)):
        manifest["segments"].append({
            "id": i,
            "text": text,
            "speaker": speaker or "narrator",
            "gender": gender or "",
            "voice_name": voice_name,
            "start": round(start, 3),
            "end": round(end, 3),
        })
    manifest_path = output_dir / "poc_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Saved manifest: {manifest_path}")
    print(f"\n{'=' * 60}")
    print(f"DONE. {len(files)}/{len(segments)} lines synthesized.")
    print(f"  Audio:  {output_mp3}")
    print(f"  Player: python3 -m http.server 8000 -> http://localhost:8000/poc_player.html")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
