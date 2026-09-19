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
from mistralai import Mistral
from pydub import AudioSegment

from poc_reader import chunk_text, extract_epub_chapter, list_epub_chapters

SCRIPT_DIR = Path(__file__).resolve().parent

LLM_MODEL_DEFAULT = "mistral-large-latest"
RATE_DEFAULT = "-8%"
GAP_SAME_MS = 250    # silence between consecutive lines of the same voice
GAP_SWITCH_MS = 600  # silence at a voice change

VOICE_NARRATOR = "it-IT-GiuseppeMultilingualNeural"
VOICE_FEMALE_1 = "fr-FR-VivienneMultilingualNeural"
VOICE_FEMALE_2 = "en-US-EmmaMultilingualNeural"
VOICE_SHORT_MALE = "en-US-AndrewMultilingualNeural"

PREPARE_PROMPT = """Sei un preparatore di testi per la sintesi vocale (TTS) in italiano.
Il testo è tratto da "Storia dell'assedio di Lisbona" di José Saramago, traduzione italiana di Rita Desti.
Lo stile di Saramago ha periodi lunghissimi con catene di virgole e dialoghi incorporati nella narrazione senza virgolette.

Prepara il testo per essere letto ad alta voce in italiano:
1. PULIZIA: correggi gli evidenti errori di OCR e di ortografia (parole fuse o spezzate, lettere scambiate, accenti mancanti), senza cambiare lo stile né le parole di contenuto. Se una parola è corretta ma rara, lasciala com'è.
2. PUNTEGGIATURA PER IL PARLATO: conserva il ritmo fluido dell'autore, ma dove una catena di virgole renderebbe la lettura a scatti, unisci le clausole brevi in un respiro solo, oppure usa un punto dove termina davvero un pensiero completo, così la voce assume contorni intonativi naturali invece di abbassarsi su ogni virgola.
3. DIALOGHI: metti le parole pronunciate da ciascun personaggio su una riga propria, prefissata dal nome del personaggio in maiuscolo, seguito da [f] o [m] e da due punti (per esempio "MADONNA [f]:"). Le clausole di regia ("gli disse", "domandò", "rispose") restano nella narrazione.
4. Scrivi i numeri in lettere, sviluppa le abbreviazioni ed elimina i riferimenti a note a piè di pagina (come [3]).
5. Rimuovi anche il corpo delle note a piè di pagina quando è incorporato nel flusso del testo: i passaggi che iniziano con un numero seguito da un trattino, per esempio "3 - Narra la leggenda che...". Questi passaggi non devono essere letti ad alta voce.
6. Non aggiungere, togliere o cambiare nessuna parola di contenuto. Restituisci solo il testo preparato, senza commenti né intestazioni."""


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


def llm_prepare(client, model, text, retries=3):
    """One LLM call per chunk: clean + repunctuate + speaker tags."""
    for attempt in range(retries):
        try:
            response = client.chat.complete(
                model=model,
                messages=[{"role": "user", "content": PREPARE_PROMPT + "\n\n---\n\n" + text}],
            )
            content = response.choices[0].message.content.strip()
            # Guard against markdown fences or preambles
            if content.startswith("```"):
                content = re.sub(r"^```[a-z]*\n?|\n?```$", "", content).strip()
            # Drop a leading preamble line ("Ecco il testo preparato...:")
            # unless it looks like a speaker tag (all-caps name, [f]/[m])
            lines = content.split("\n")
            first = lines[0].strip()
            if first.endswith(":") and not first.isupper() \
                    and not re.search(r"\[[fm]\]:$", first):
                content = "\n".join(lines[1:]).strip()
            # Drop standalone separator lines ("---")
            content = re.sub(r"(?m)^\s*-{3,}\s*$", "", content).strip()
            return content
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  LLM call failed ({e}), retrying in {2 ** attempt}s...")
            time.sleep(2 ** attempt)


def parse_lines(prepared):
    """Split prepared text into (speaker, gender, text) lines.

    Handles both 'NAME [f]: text' on one line and the two-line format where
    'NAME [f]:' stands alone and the dialogue follows on the next line.
    Speaker labels are voice switches, never spoken.
    """
    name_pat = r"[A-ZÀÈÉÌÒÙ' ]{2,}"
    lines = []
    pending = None  # (speaker, gender) awaiting its text line
    for raw in prepared.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(rf"^({name_pat}?)\s*\[([fm])\]:\s*(.+)$", line)
        if m:
            speaker = m.group(1).strip() or "dialogo"
            lines.append((speaker, m.group(2), m.group(3).strip()))
            pending = None
            continue
        m = re.match(rf"^({name_pat}?)\s*\[([fm])\]:$", line)
        if m:
            pending = ((m.group(1).strip() or "dialogo"), m.group(2))
            continue
        # Untagged speaker label (no gender) — treat as narration-side dialogue
        m = re.match(rf"^({name_pat}):$", line)
        if m:
            pending = (m.group(1).strip(), None)
            continue
        m = re.match(rf"^({name_pat}):\s*(.+)$", line)
        if m:
            lines.append((m.group(1).strip(), None, m.group(2).strip()))
            pending = None
            continue
        speaker, gender = pending if pending else (None, None)
        lines.append((speaker, gender, line))
        pending = None
    return lines


def split_long_narration(lines, max_chars=300):
    """Split long narration lines at sentence boundaries for finer highlighting."""
    out = []
    for speaker, gender, text in lines:
        if speaker or len(text) <= max_chars:
            out.append((speaker, gender, text))
            continue
        sentences = re.split(r"(?<=[.!?])\s+", text)
        buf = ""
        for sentence in sentences:
            if buf and len(buf) + len(sentence) > max_chars:
                out.append((None, None, buf.strip()))
                buf = sentence
            else:
                buf = (buf + " " + sentence).strip()
        if buf:
            out.append((None, None, buf.strip()))
    return out


def assign_voices(lines, andrew_short=False):
    """Two-pass voice assignment. Returns list of (speaker, gender, text, voice, voice_name)."""
    # Pass 1: per-character stats in order of first appearance
    stats = {}  # name -> {"gender": g, "lines": n, "chars": total}
    order = []
    for speaker, gender, text in lines:
        if not speaker:
            continue
        if speaker not in stats:
            stats[speaker] = {"gender": gender, "lines": 0, "chars": 0}
            order.append(speaker)
        stats[speaker]["lines"] += 1
        stats[speaker]["chars"] += len(text)
        if gender:
            stats[speaker]["gender"] = gender

    female_assigned = []
    for speaker in order:
        if stats[speaker]["gender"] == "f":
            female_assigned.append(speaker)

    def voice_for(speaker, text):
        if not speaker:
            return VOICE_NARRATOR, "Giuseppe"
        s = stats[speaker]
        if s["gender"] == "f":
            if speaker == female_assigned[0]:
                return VOICE_FEMALE_1, "Vivienne"
            return VOICE_FEMALE_2, "Emma"
        # male or unknown gender
        if andrew_short and s["lines"] == 1 and len(text) < 80:
            return VOICE_SHORT_MALE, "Andrew"
        return VOICE_NARRATOR, "Giuseppe"

    return [
        (speaker, gender, text) + voice_for(speaker, text)
        for speaker, gender, text in lines
    ]


async def synthesize(segments, output_dir, rate):
    """Synthesize each line with edge-tts. Returns list of (path, voice_name)."""
    files = []
    for i, (speaker, gender, text, voice, voice_name) in enumerate(segments):
        seg_path = output_dir / f"seg_{i:03d}.mp3"
        for attempt in range(3):
            try:
                communicate = edge_tts.Communicate(text, voice, rate=rate)
                await communicate.save(str(seg_path))
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ERROR synthesizing segment {i}: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)
        files.append((seg_path, voice_name))
        tag = speaker or "narrator"
        print(f"  [{i:03d}] {tag:>14} -> {voice_name}")
    return files


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
    files = asyncio.run(synthesize(segments, output_dir, args.rate))

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
