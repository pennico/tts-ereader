#!/usr/bin/env python3
"""PoC Reader: AI-powered TTS eReader pipeline.

Pipeline:
  Text -> [Mistral LLM analysis] -> reading_script.json
       -> [voice_profile mapping] -> voice_id / ref_audio
       -> [Voxtral TTS per segment] -> audio segments + offsets manifest
       -> poc_output.mp3 + poc_manifest.json

Usage:
  python3 poc_reader.py --sample danish_fiction
  python3 poc_reader.py --sample english_fiction --output-dir out
  python3 poc_reader.py --text "Your custom text here"
  python3 poc_reader.py --sample danish_fiction --list-voices

Requires:
  export MISTRAL_API_KEY="your-key"
  pip install mistralai pydub mutagen
  ffmpeg installed (brew install ffmpeg)
"""

import argparse
import base64
import html.parser
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

# ── Constants ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = SCRIPT_DIR / "samples"
VOICES_CONFIG = SCRIPT_DIR / "voices.json"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "out"

LLM_MODEL = "mistral-large-latest"
TTS_MODEL = "voxtral-mini-tts-2603"
TTS_FORMAT = "mp3"
CROSSFADE_MS = 40  # crossfade between segments to avoid clicks
GAP_MS = 150  # silence gap between segments (in addition to crossfade)
MISTRAL_API_BASE = "https://api.mistral.ai/v1"

# Voxtral TTS supported languages (Danish is NOT supported — see README)
SUPPORTED_LANGS = {"en", "fr", "de", "es", "nl", "pt", "it", "hi", "ar"}


# ── EPUB extraction ──────────────────────────────────────────────────────────

class _HTMLStripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True
    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self.text.append("\n")
    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def _strip_html(html_content):
    s = _HTMLStripper()
    s.feed(html_content)
    raw = "".join(s.text)
    # Collapse whitespace but preserve paragraph breaks
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
    lines = [l for l in lines if l]
    return "\n\n".join(lines)


def list_epub_chapters(epub_path):
    """List all HTML files in the EPUB with their first line and char count."""
    with zipfile.ZipFile(epub_path) as z:
        html_files = sorted(n for n in z.namelist()
                            if n.endswith((".html", ".xhtml", ".htm")))
        chapters = []
        for i, f in enumerate(html_files):
            content = z.read(f).decode("utf-8", errors="replace")
            text = _strip_html(content)
            if len(text) < 200:
                continue
            first_line = text.split("\n")[0][:80]
            chapters.append((i, f, len(text), first_line))
        return chapters


def extract_epub_chapter(epub_path, chapter_index):
    """Extract text from a specific chapter by index (into the filtered chapter list)."""
    with zipfile.ZipFile(epub_path) as z:
        html_files = sorted(n for n in z.namelist()
                            if n.endswith((".html", ".xhtml", ".htm")))
        # Filter to substantive chapters
        substantive = []
        for f in html_files:
            content = z.read(f).decode("utf-8", errors="replace")
            text = _strip_html(content)
            if len(text) >= 200:
                substantive.append((f, text))
        if chapter_index < 0 or chapter_index >= len(substantive):
            print(f"ERROR: chapter index {chapter_index} out of range (0-{len(substantive)-1})")
            sys.exit(1)
        return substantive[chapter_index][1]


def chunk_text(text, max_chars=4000):
    """Split text into chunks at paragraph boundaries, each <= max_chars."""
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ── Mistral client ───────────────────────────────────────────────────────────

def get_api_key():
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY not set. Get one at https://console.mistral.ai")
        sys.exit(1)
    return api_key


def get_client():
    """Return the Mistral SDK client (used for chat completions only).
    TTS and voice management use raw HTTP — see tts_speech() and list_voices_http()."""
    api_key = get_api_key()
    try:
        from mistralai import Mistral
    except ImportError:
        try:  # mistralai 2.x: client moved off the top level
            from mistralai.client import Mistral
        except ImportError:
            print("ERROR: mistralai not installed. Run: pip install mistralai")
            sys.exit(1)
    return Mistral(api_key=api_key)


# ── Voice config ─────────────────────────────────────────────────────────────

def load_voices_config():
    if not VOICES_CONFIG.exists():
        print(f"WARNING: {VOICES_CONFIG} not found — all profiles will use default voice.")
        return {"basic": {"default_voice_id": None}, "enhanced": {"default_voice_id": None}}
    with open(VOICES_CONFIG) as f:
        return json.load(f)


def get_style_config(config, style):
    """Return the sub-config for the given style ('basic' or 'enhanced')."""
    return config.get(style, config.get("basic", {"default_voice_id": None}))


def get_voice_name(config, style, voice_id):
    """Look up a human-readable voice name from the style config."""
    style_cfg = get_style_config(config, style)
    names = style_cfg.get("voice_names", {})
    return names.get(voice_id, voice_id[:8] if voice_id else "?")


def list_voices_http(api_key):
    """List saved and preset voices via raw HTTP (SDK 1.10.0 lacks TTS/voice APIs)."""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        resp = requests.get(f"{MISTRAL_API_BASE}/audio/voices",
                            headers=headers, params={"type": "all"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        print(f"Voices in your Mistral account ({data.get('total', len(items))} total):")
        for v in items:
            print(f"  id={v.get('id')}  name={v.get('name')}  "
                  f"gender={v.get('gender', '?')}  languages={v.get('languages', [])}")
        if not items:
            print("  (none — create one in https://console.mistral.ai)")
    except Exception as e:
        print(f"Could not list voices: {e}")


def resolve_voice(profile_name, emotion, style_config):
    """Resolve a voice for a (profile, emotion) pair using the style config.
    Returns (voice_id, ref_audio_b64, voice_name).

    Lookup order for 'enhanced' style:
      1. voice_map["profile:emotion"]
      2. fallback_by_profile["profile"]
      3. default_voice_id
    For 'basic' style: always default_voice_id.
    """
    # Try profile:emotion in voice_map
    voice_map = style_config.get("voice_map", {})
    key = f"{profile_name}:{emotion}"
    vid = voice_map.get(key)
    if vid:
        return vid, None, None

    # Try fallback by profile
    fallback = style_config.get("fallback_by_profile", {})
    vid = fallback.get(profile_name)
    if vid:
        return vid, None, None

    # Try old-style profiles dict (for backward compat)
    profiles = style_config.get("profiles", {})
    entry = profiles.get(profile_name)
    if entry:
        vid = entry.get("voice_id")
        ref_path = entry.get("ref_audio")
        if vid:
            return vid, None, None
        if ref_path:
            full = Path(ref_path)
            if not full.is_absolute():
                full = SCRIPT_DIR / full
            if full.exists():
                b64 = base64.b64encode(full.read_bytes()).decode()
                return None, b64, None

    # Fall back to default
    default_vid = style_config.get("default_voice_id")
    if default_vid:
        return default_vid, None, None

    print(f"  WARNING: no voice mapping for '{profile_name}:{emotion}' and no default set.")
    return None, None, None


# ── LLM analysis ─────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """\
You are a reading director for an AI-powered audiobook system. Analyze the following text and break it into segments for text-to-speech synthesis.

For each segment, identify:
- id: sequential integer starting at 0
- text: the exact original text of this segment (for display)
- speakable_text: the text prepared for TTS (see rules below)
- speaker: "narrator" for narration, or the character's name for dialogue
- gender: "female", "male", or "neutral"
- role: "narration", "dialogue", or "technical"
- emotion: one of "calm", "tense", "convinced", "soft", "excited", "sad", "angry", "neutral"
- pace: "slow", "normal", or "fast"
- pitch_hint: "low", "mid", or "high"
- voice_profile: one of the available profiles listed below

Rules for segmentation:
- Detect the language of the text automatically and set the "language" field.
- Break text into natural reading units: each sentence or dialogue line is its own segment.
- For technical, instructional, or expository text: use role "technical", voice_profile "tech-neutral", emotion "neutral", pace "normal".
- For fiction: distinguish characters by name, gender, and emotional state. Narration uses "narrator" as speaker.
- The voice_profile MUST be one of: {profiles}
- Segments must cover the ENTIRE input text with no gaps and no overlaps. Every word must appear in exactly one segment.

Rules for speakable_text (the text that will be sent to TTS):
- Convert numbers to their spoken form: "1234" -> "one thousand two hundred and thirty four" (or "twelve thirty four" if it's a time). Use the appropriate language.
- Spell out abbreviations: "FBI" -> "F B I", "NASA" -> "N A S A", "Mr." -> "Mister", "Dr." -> "Doctor".
- Remove markdown formatting, emojis, and special characters that cannot be spoken.
- Add natural pause indicators where the text has punctuation that implies a pause: use ", " for short pauses and ". " for sentence endings. Keep semicolons and colons as natural pause points.
- For dialogue, keep the quotation marks removed — the TTS should not read "quote" markers.
- For ellipsis "...", write it as "..." (the TTS will interpret it as a trailing pause).
- Keep the speakable_text in the SAME LANGUAGE as the original text.
- The speakable_text should sound natural when read aloud. If a sentence is very long, you may add a comma where a natural breathing pause would occur.

Return ONLY valid JSON. No markdown, no explanation, no code fences.

Available voice profiles: {profiles}

Input text:
---
{text}
---

Return JSON in this exact structure:
{{
  "language": "en",
  "segments": [
    {{
      "id": 0,
      "text": "the original text",
      "speakable_text": "the text prepared for TTS",
      "speaker": "narrator",
      "gender": "neutral",
      "role": "narration",
      "emotion": "calm",
      "pace": "normal",
      "pitch_hint": "mid",
      "voice_profile": "narrator-warm"
    }}
  ]
}}
"""


def analyze_text(client, text, config):
    # Get profiles from enhanced style (they're the same across styles)
    enhanced = config.get("enhanced", {})
    profiles = list(enhanced.get("fallback_by_profile", {}).keys())
    if not profiles:
        profiles = [
            "narrator-warm", "narrator-calm", "female-soft", "female-tense",
            "male-rough", "male-soft", "tech-neutral",
        ]
    profiles_str = ", ".join(profiles)

    prompt = ANALYSIS_PROMPT.format(text=text, profiles=profiles_str)

    print("Analyzing text with Mistral LLM...")
    response = client.chat.complete(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    content = response.choices[0].message.content
    script = json.loads(content)

    # Validate
    segs = script.get("segments", [])
    if not segs:
        raise ValueError("LLM returned no segments")

    lang = script.get("language", "unknown")
    if lang not in SUPPORTED_LANGS:
        print(f"  NOTE: Detected language '{lang}' is NOT in Voxtral's supported list "
              f"({', '.join(sorted(SUPPORTED_LANGS))}). Quality may be degraded.")

    print(f"  Language: {lang}")
    print(f"  Segments: {len(segs)}")
    for s in segs:
        st = s.get("speakable_text", s.get("text", ""))
        print(f"    [{s['id']}] speaker={s.get('speaker','?')} "
              f"emotion={s.get('emotion','?')} profile={s.get('voice_profile','?')} "
              f"tts=\"{st[:50]}...\"")

    return script


# ── TTS synthesis ────────────────────────────────────────────────────────────

def synthesize_segment(api_key, text, voice_id=None, ref_audio_b64=None,
                       retries=3):
    """Synthesize one text segment via raw HTTP POST to /v1/audio/speech.
    Returns raw MP3 bytes, or None on failure.

    The Mistral Python SDK (1.10.0) does not yet include the TTS endpoint,
    so we call the REST API directly.
    """
    if not voice_id and not ref_audio_b64:
        print("  ERROR: no voice_id or ref_audio available — skipping segment.")
        return None

    payload = {
        "model": TTS_MODEL,
        "input": text,
        "response_format": TTS_FORMAT,
    }
    if voice_id:
        payload["voice_id"] = voice_id
    elif ref_audio_b64:
        payload["ref_audio"] = ref_audio_b64

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{MISTRAL_API_BASE}/audio/speech",
                headers=headers, json=payload, timeout=60,
            )
            if resp.status_code == 403:
                print(f"  SKIP (content moderation 403): {text[:60]}...")
                return None
            if resp.status_code == 429:
                wait = 2 ** attempt
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()

            data = resp.json()
            audio_b64 = data.get("audio_data")
            if not audio_b64:
                print("  ERROR: no audio_data in response")
                return None
            return base64.b64decode(audio_b64)

        except requests.exceptions.HTTPError as e:
            err_str = str(e)
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  Retry {attempt+1}/{retries} after {wait}s: {err_str[:80]}")
                time.sleep(wait)
            else:
                print(f"  FAILED after {retries} retries: {err_str[:120]}")
                return None
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  Retry {attempt+1}/{retries} after {wait}s: {str(e)[:80]}")
                time.sleep(wait)
            else:
                print(f"  FAILED after {retries} retries: {str(e)[:120]}")
                return None
    return None


# ── Audio concatenation ─────────────────────────────────────────────────────

def get_duration_ms(mp3_path):
    """Get MP3 duration in milliseconds using mutagen (pure Python, no ffmpeg)."""
    try:
        from mutagen.mp3 import MP3
        audio = MP3(str(mp3_path))
        return int(audio.info.length * 1000)
    except Exception:
        return 0


def concatenate_with_pydub(segment_paths, output_path, crossfade_ms=CROSSFADE_MS,
                           gap_ms=GAP_MS):
    """Concatenate using pydub (requires ffmpeg). Returns list of (start_ms, end_ms)."""
    from pydub import AudioSegment

    silence = AudioSegment.silent(duration=gap_ms)
    combined = AudioSegment.empty()
    offsets = []
    cursor = 0  # ms

    for i, path in enumerate(segment_paths):
        seg = AudioSegment.from_mp3(str(path))
        seg_len = len(seg)

        if i == 0:
            start = cursor
            combined = seg
            cursor = seg_len
            end = cursor
        else:
            # Add silence gap, then crossfade
            start = cursor + gap_ms - crossfade_ms
            combined = combined + silence
            combined = combined.append(seg, crossfade=crossfade_ms)
            cursor = len(combined)
            end = cursor

        offsets.append((start / 1000.0, end / 1000.0))

    combined.export(str(output_path), format="mp3")
    return offsets


def concatenate_binary(segment_paths, output_path, gap_ms=GAP_MS):
    """Fallback: binary-concatenate MP3s with a silent frame gap.
    Less precise than pydub but works without ffmpeg.
    Returns list of (start_s, end_s) using mutagen for durations."""
    # Minimal silent MP3 frame (standard 417-byte frame for 128kbps/44.1kHz)
    SILENT_FRAME = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)

    offsets = []
    cursor = 0.0
    with open(output_path, "wb") as out:
        for i, path in enumerate(segment_paths):
            if i > 0:
                # Write a few silent frames as a gap
                for _ in range(10):
                    out.write(SILENT_FRAME)
                cursor += gap_ms / 1000.0

            dur = get_duration_ms(path) / 1000.0
            start = cursor
            with open(path, "rb") as f:
                out.write(f.read())
            end = start + dur
            offsets.append((start, end))
            cursor = end
    return offsets


def concatenate_segments(segment_paths, output_path):
    """Try pydub first; fall back to binary concatenation if ffmpeg unavailable."""
    try:
        from pydub import AudioSegment
        # Quick test that ffmpeg is actually available
        AudioSegment.from_mp3(str(segment_paths[0]))
        print("Concatenating with pydub (ffmpeg)...")
        return concatenate_with_pydub(segment_paths, output_path)
    except Exception as e:
        print(f"pydub/ffmpeg unavailable ({e}), falling back to binary concatenation...")
        return concatenate_binary(segment_paths, output_path)


# ── Main pipeline ───────────────────────────────────────────────────────────

def run_pipeline(args):
    api_key = get_api_key()
    client = get_client()
    config = load_voices_config()
    style = args.style
    style_config = get_style_config(config, style)

    if args.list_voices:
        list_voices_http(api_key)
        return

    if args.list_chapters:
        if not args.epub:
            print("ERROR: --list-chapters requires --epub <path>")
            sys.exit(1)
        chapters = list_epub_chapters(args.epub)
        print(f"Chapters in {Path(args.epub).name} ({len(chapters)} total):\n")
        for idx, fname, chars, title in chapters:
            print(f"  [{idx:2d}] {chars:6d} chars  {title}")
        return

    # Load text
    if args.text:
        text = args.text
        label = "custom"
    elif args.epub:
        if args.chapter is None:
            print("ERROR: --epub requires --chapter <index> (use --list-chapters to see options)")
            sys.exit(1)
        text = extract_epub_chapter(args.epub, args.chapter)
        label = f"{Path(args.epub).stem[:30]}_ch{args.chapter}"
    elif args.sample:
        sample_path = SAMPLES_DIR / f"{args.sample}.txt"
        if not sample_path.exists():
            print(f"ERROR: sample not found: {sample_path}")
            print(f"Available samples: {', '.join(p.stem for p in SAMPLES_DIR.glob('*.txt'))}")
            sys.exit(1)
        text = sample_path.read_text(encoding="utf-8").strip()
        label = args.sample
    else:
        print("ERROR: provide --sample <name>, --text '...', or --epub <path> --chapter <n>")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"PoC Reader — sample: {label}  style: {style}")
    print(f"Text length: {len(text)} chars")
    print(f"{'='*60}\n")

    # Step 1: Analyze (chunk long texts)
    chunks = chunk_text(text, args.max_chars)
    if len(chunks) > 1:
        print(f"Text split into {len(chunks)} chunks (max {args.max_chars} chars each)\n")

    all_segments = []
    script_lang = "unknown"
    for ci, chunk in enumerate(chunks):
        if len(chunks) > 1:
            print(f"--- Chunk {ci+1}/{len(chunks)} ({len(chunk)} chars) ---")
        script = analyze_text(client, chunk, config)
        script_lang = script.get("language", script_lang)
        # Renumber segment IDs globally
        for seg in script["segments"]:
            seg["id"] = len(all_segments)
            all_segments.append(seg)

    script = {"language": script_lang, "segments": all_segments}

    # Save reading script
    script_path = output_dir / "reading_script.json"
    with open(script_path, "w") as f:
        json.dump(script, f, indent=2, ensure_ascii=False)
    print(f"\nSaved reading script: {script_path}")
    print(f"Total segments: {len(all_segments)}\n")

    # Step 2: Synthesize each segment
    segments = all_segments
    segment_files = []
    synthesized = []
    voice_names = {}

    print(f"Synthesizing segments with Voxtral TTS (style: {style})...")
    for seg in segments:
        sid = seg["id"]
        seg_text = seg.get("speakable_text", seg["text"])
        profile = seg.get("voice_profile", "tech-neutral")
        emotion = seg.get("emotion", "neutral")

        voice_id, ref_audio_b64, _ = resolve_voice(profile, emotion, style_config)
        vname = get_voice_name(config, style, voice_id) if voice_id else "?"
        voice_names[sid] = vname

        print(f"  [{sid}] {vname}  profile={profile} emotion={emotion} -> "
              f"{'voice_id=' + voice_id[:12] if voice_id else 'ref_audio' if ref_audio_b64 else 'NONE'}")

        audio_bytes = synthesize_segment(api_key, seg_text, voice_id, ref_audio_b64)

        if audio_bytes:
            seg_path = output_dir / f"seg_{sid:03d}.mp3"
            seg_path.write_bytes(audio_bytes)
            segment_files.append(seg_path)
            synthesized.append(seg)
        else:
            print(f"  [{sid}] skipped (no audio)")

    if not segment_files:
        print("\nERROR: no segments were synthesized. Check API key, voice mappings, and content moderation.")
        sys.exit(1)

    # Step 3: Concatenate
    output_mp3 = output_dir / "poc_output.mp3"
    offsets = concatenate_segments(segment_files, output_mp3)
    print(f"\nConcatenated {len(segment_files)} segments -> {output_mp3}")

    # Step 4: Build manifest
    manifest = {
        "audio": "poc_output.mp3",
        "sample": label,
        "style": style,
        "language": script.get("language", "unknown"),
        "total_segments": len(synthesized),
        "segments": [],
    }
    for i, seg in enumerate(synthesized):
        start, end = offsets[i]
        sid = seg["id"]
        manifest["segments"].append({
            "id": sid,
            "text": seg["text"],
            "speakable_text": seg.get("speakable_text", ""),
            "speaker": seg.get("speaker", ""),
            "gender": seg.get("gender", ""),
            "role": seg.get("role", ""),
            "emotion": seg.get("emotion", ""),
            "pace": seg.get("pace", ""),
            "pitch_hint": seg.get("pitch_hint", ""),
            "voice_profile": seg.get("voice_profile", ""),
            "voice_name": voice_names.get(sid, ""),
            "start": round(start, 3),
            "end": round(end, 3),
        })

    manifest_path = output_dir / "poc_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Saved manifest: {manifest_path}")
    print(f"\n{'='*60}")
    print(f"DONE. {len(synthesized)}/{len(segments)} segments synthesized.")
    print(f"  Audio:  {output_mp3}")
    print("  Player: open poc_player.html in a browser")
    print("  Serve:  python3 -m http.server 8000  (then open http://localhost:8000/poc_player.html)")
    print(f"{'='*60}")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PoC Reader: AI-powered TTS eReader pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python3 poc_reader.py --sample danish_fiction
  python3 poc_reader.py --sample english_fiction
  python3 poc_reader.py --sample danish_technical
  python3 poc_reader.py --sample italian_fiction
  python3 poc_reader.py --text "Your custom text here"
  python3 poc_reader.py --list-voices
""",
    )
    parser.add_argument("--sample", type=str, help="Sample name (e.g. danish_fiction, english_fiction)")
    parser.add_argument("--text", type=str, help="Custom text to process")
    parser.add_argument("--epub", type=str, help="Path to an EPUB file to read")
    parser.add_argument("--chapter", type=int, help="Chapter index in the EPUB (use --list-chapters to see options)")
    parser.add_argument("--list-chapters", action="store_true",
                        help="List chapters in the EPUB and exit (requires --epub)")
    parser.add_argument("--style", type=str, default="enhanced", choices=["basic", "enhanced"],
                        help="Voice style: 'basic' (single voice) or 'enhanced' (multi-voice with emotions)")
    parser.add_argument("--max-chars", type=int, default=4000,
                        help="Max chars per LLM analysis chunk (default: 4000). Long texts are split at paragraph boundaries.")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--list-voices", action="store_true",
                        help="List saved voices in your Mistral account and exit")
    args = parser.parse_args()

    run_pipeline(args)


if __name__ == "__main__":
    main()
