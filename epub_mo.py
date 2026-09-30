#!/usr/bin/env python3
"""epub_mo: EPUB 3 Media Overlays (read-along) generator.

Takes the source EPUB, and for each selected chapter:
  1. extracts sentence fragments from the raw XHTML (tracking raw offsets),
  2. prepares the text with a Mistral LLM (clean + repunctuate + speakers),
  3. synthesizes with edge-tts capturing WordBoundary timings,
  4. aligns prepared words back to original fragments (difflib),
  5. injects invisible <span id="mo-N"> anchors into the XHTML,
  6. writes a SMIL per chapter, upgrades the OPF to EPUB 3 (nav doc,
     media:duration metadata, media-overlay attributes), appends highlight
     CSS, and repackages everything into a read-along EPUB.

Fragments with no matched words (e.g. footnote bodies removed by the LLM)
get no <par> and are skipped during playback.

Usage:
  python3 epub_mo.py --epub book.epub --list-chapters
  python3 epub_mo.py --epub book.epub --chapter 4 --slice 4000 \
      --output out/saramago_mo_test.epub
  python3 epub_mo.py --epub book.epub --all --output out/book_readalong.epub

Requires: MISTRAL_API_KEY (env or .env in the script directory), edge-tts,
pydub, ffmpeg.
"""

import argparse
import asyncio
import difflib
import html as html_mod
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import edge_tts
try:
    from mistralai import Mistral
except ImportError:  # mistralai 2.x: client moved off the top level
    from mistralai.client import Mistral

from poc_reader import chunk_text, list_epub_chapters
from edge_reader import (
    GAP_SAME_MS,
    GAP_SWITCH_MS,
    LLM_MODEL_DEFAULT,
    RATE_DEFAULT,
    WORKERS_DEFAULT,
    assign_voices,
    concatenate,
    llm_prepare,
    load_env,
    parse_lines,
    split_long_narration,
)

SCRIPT_DIR = Path(__file__).resolve().parent

FRAG_MAX = 300          # fragments longer than this are sub-split at commas
SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")
COMMA_SPLIT = re.compile(r"(?<=,)\s+")
TOKEN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+")
BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"}

CSS_MO = """
/* Media Overlays read-along highlighting (added by epub_mo.py) */
.mo-active {
  background-color: #ffe89a;
}
.mo-playing {
  color: inherit;
}
"""

NARRATOR = "Giuseppe, Vivienne, Emma (edge-tts, preparazione Mistral)"


# ── Fragment extraction from raw XHTML ──────────────────────────────────────

def text_runs(raw):
    """Text nodes inside <body>, with absolute offsets and a paragraph id."""
    m = re.search(r"<body\b[^>]*>", raw, re.I)
    if not m:
        raise ValueError("no <body> element found")
    body_start = m.end()
    body_end = raw.rfind("</body>")
    if body_end < 0:
        body_end = len(raw)
    runs = []
    para = 0
    for tok in re.finditer(r"<[^>]+>|[^<]+", raw[body_start:body_end]):
        piece = tok.group(0)
        if piece.startswith("<"):
            t = re.match(r"</?\s*([a-zA-Z0-9]+)", piece)
            if t and t.group(1).lower() in BLOCK_TAGS:
                para += 1
        elif piece.strip():
            runs.append({
                "start": body_start + tok.start(),
                "end": body_start + tok.end(),
                "text": piece,
                "para": para,
            })
    return runs


def _split_offsets(text, pattern):
    """Regions (start, end) of text split at pattern matches; separators dropped."""
    regions = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            regions.append((pos, m.start()))
        pos = m.end()
    if len(text) > pos:
        regions.append((pos, len(text)))
    return regions


def extract_fragments(raw, runs, max_len=FRAG_MAX):
    """Sentence fragments (comma sub-split if long) with raw injection offsets."""
    frags = []
    for ri, run in enumerate(runs):
        text = run["text"]
        for s, e in _split_offsets(text, SENT_SPLIT):
            sub = [(s, e)]
            if e - s > max_len:
                sub = [(s + s2, s + e2) for s2, e2 in _split_offsets(text[s:e], COMMA_SPLIT)]
            for a, b in sub:
                raw_slice = raw[run["start"] + a:run["start"] + b]
                lead = len(raw_slice) - len(raw_slice.lstrip())
                trail = len(raw_slice) - len(raw_slice.rstrip())
                inj_start = run["start"] + a + lead
                inj_end = run["start"] + b - trail
                if inj_start >= inj_end:
                    continue
                frags.append({
                    "run": ri,
                    "para": run["para"],
                    "inj_start": inj_start,
                    "inj_end": inj_end,
                    "text": html_mod.unescape(raw_slice).strip(),
                })
    return frags


def apply_slice(frags, budget):
    """Keep fragments until the budget of source chars is reached."""
    if not budget:
        return frags
    out, total = [], 0
    for f in frags:
        out.append(f)
        total += len(f["text"])
        if total >= budget:
            break
    return out


def source_text(frags):
    """Fragments joined back into paragraphs for the LLM."""
    paras = []
    cur_para, cur = None, []
    for f in frags:
        if f["para"] != cur_para:
            if cur:
                paras.append(" ".join(cur))
            cur_para, cur = f["para"], []
        cur.append(f["text"])
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)


# ── Word-timed synthesis ─────────────────────────────────────────────────────

async def synth_word_timed(segments, work_dir, rate, workers=WORKERS_DEFAULT):
    """Synthesize segments with up to `workers` requests in flight.

    Returns (files, word_events), both in segment order — concatenate() and
    align_fragments() depend on that order.

    word_events[i] = list of (offset_sec, duration_sec, text) from edge-tts
    WordBoundary metadata, relative to the segment's own audio.
    """
    sem = asyncio.Semaphore(max(1, workers))

    async def synth_one(i, speaker, _gender, text, voice, voice_name):
        seg_path = work_dir / f"seg_{i:03d}.mp3"
        events = []
        for attempt in range(3):
            try:
                async with sem:
                    comm = edge_tts.Communicate(text, voice, rate=rate,
                                                boundary="WordBoundary")
                    audio = bytearray()
                    events = []
                    async for chunk in comm.stream():
                        if chunk["type"] == "audio":
                            audio.extend(chunk["data"])
                        elif chunk["type"] == "WordBoundary":
                            events.append((chunk["offset"] / 1e7,
                                           chunk["duration"] / 1e7,
                                           chunk["text"]))
                if not audio:
                    raise RuntimeError("no audio received")
                seg_path.write_bytes(bytes(audio))
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ERROR synthesizing segment {i}: {e}")
                    raise
                await asyncio.sleep(2 ** attempt)
        tag = speaker or "narrator"
        print(f"  [{i:03d}] {tag:>14} -> {voice_name} ({len(events)} words)")
        return ((seg_path, voice_name), events)

    results = await asyncio.gather(
        *(synth_one(i, *seg) for i, seg in enumerate(segments)))
    files = [r[0] for r in results]
    all_events = [r[1] for r in results]
    return files, all_events


# ── Alignment: prepared words -> original fragments ─────────────────────────

def norm_word(w):
    return re.sub(r"[^a-zà-ÿ0-9]", "", html_mod.unescape(w).lower())


def pair_word_times(text, events, seg_start):
    """Pair tokens of a segment's text with its WordBoundary events.

    Returns a list of (norm_key, abs_time) for confidently paired words.
    """
    tokens = TOKEN.findall(text)
    keys = [norm_word(t) for t in tokens]
    ekeys = [norm_word(e[2]) for e in events]
    if len(events) == len(tokens):
        pairs = list(zip(range(len(tokens)), range(len(events))))
    else:
        sm = difflib.SequenceMatcher(None, keys, ekeys, autojunk=False)
        pairs = []
        for b in sm.get_matching_blocks():
            for j in range(b.size):
                pairs.append((b.a + j, b.b + j))
    out = []
    for ti, ei in pairs:
        if keys[ti] and keys[ti] == ekeys[ei]:
            out.append((keys[ti], seg_start + events[ei][0]))
    return out


def align_fragments(frags, segments, offsets, word_events):
    """Map original fragments to audio start times via word alignment.

    Returns (frag_begin, n_orig_words, n_matched, n_prep_words).
    """
    orig = []  # (frag_idx, key)
    for fi, f in enumerate(frags):
        for w in TOKEN.findall(f["text"]):
            k = norm_word(w)
            if k:
                orig.append((fi, k))
    prep = []  # (norm_key, abs_time)
    for seg, (start, _end), events in zip(segments, offsets, word_events):
        prep.extend(pair_word_times(seg[2], events, start))

    sm = difflib.SequenceMatcher(None,
                                  [k for _, k in orig],
                                  [k for k, _t in prep],
                                  autojunk=False)
    frag_begin = {}
    matched = 0
    for b in sm.get_matching_blocks():
        for j in range(b.size):
            fi = orig[b.a + j][0]
            t = prep[b.b + j][1]
            matched += 1
            if fi not in frag_begin or t < frag_begin[fi]:
                frag_begin[fi] = t
    return frag_begin, len(orig), matched, len(prep)


def build_clips(frags, frag_begin, total_dur):
    """Tile (frag_idx, clip_begin, clip_end) continuously, clamped monotonic."""
    clipped = [(fi, frag_begin[fi]) for fi in sorted(frag_begin)]
    clips = []
    prev_end = 0.0
    for j, (fi, t) in enumerate(clipped):
        begin = max(t, prev_end)
        if j + 1 < len(clipped):
            end = max(clipped[j + 1][1], begin + 0.05)
            end = min(end, total_dur)
        else:
            end = total_dur
        if end <= begin:
            end = min(begin + 0.05, total_dur)
        clips.append((fi, begin, end))
        prev_end = end
    return clips


# ── XHTML span injection ────────────────────────────────────────────────────

def inject_spans(raw, frags, clips):
    """Wrap clipped fragments in <span id="mo-N">…</span> (reverse order)."""
    insertions = []  # (pos, text, is_close)
    for fi, _b, _e in clips:
        insertions.append((frags[fi]["inj_start"], f'<span id="mo-{fi}">', 0))
        insertions.append((frags[fi]["inj_end"], "</span>", 1))
    # descending position; at equal positions opens are inserted first so the
    # close tag ends up before the open tag in the final string
    for pos, text, _is_close in sorted(insertions, key=lambda x: (-x[0], x[2])):
        raw = raw[:pos] + text + raw[pos:]
    return raw


# ── SMIL / OPF / nav documents ──────────────────────────────────────────────

def clock_value(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def smil_doc(stem, clips):
    pars = []
    for fi, b, e in clips:
        pars.append(
            f'  <par id="par-{fi}">'
            f'<text src="{stem}.html#mo-{fi}"/>'
            f'<audio src="audio/{stem}.mp3" clipBegin="{b:.3f}s" clipEnd="{e:.3f}s"/>'
            f'</par>'
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<smil xmlns="http://www.w3.org/ns/SMIL"'
        ' xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">\n'
        f'<body epub:textref="{stem}.html">\n'
        + "\n".join(pars)
        + "\n</body>\n</smil>\n"
    )


def upgrade_opf(opf, chapter_entries, durations, total_dur):
    """String surgery: EPUB 2.0 -> 3.0 with Media Overlays metadata and items.

    chapter_entries: list of (stem, smil_id, audio_id).
    """
    opf = opf.replace('version="2.0"', 'version="3.0"', 1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metas = [f'    <meta property="dcterms:modified">{now}</meta>']
    for stem, smil_id, _audio_id in chapter_entries:
        metas.append(
            f'    <meta property="media:duration" refines="#{smil_id}">'
            f'{clock_value(durations[stem])}</meta>')
        metas.append(
            f'    <meta property="media:narrator" refines="#{smil_id}">{escape(NARRATOR)}</meta>')
    metas.append(f'    <meta property="media:duration">{clock_value(total_dur)}</meta>')
    metas.append('    <meta property="media:active-class">mo-active</meta>')
    metas.append('    <meta property="media:playback-active-class">mo-playing</meta>')
    opf = opf.replace("</metadata>", "\n".join(metas) + "\n  </metadata>", 1)

    for stem, smil_id, _audio_id in chapter_entries:
        opf, n = re.subn(
            r'(<item\s+href="' + re.escape(stem + ".html") + r'"[^>]*?)/>',
            r'\1 media-overlay="' + smil_id + '"/>',
            opf, count=1)
        if n != 1:
            raise ValueError(f"could not attach media-overlay to {stem}.html item")

    items = []
    for stem, smil_id, audio_id in chapter_entries:
        items.append(f'<item href="{stem}.smil" id="{smil_id}" media-type="application/smil+xml"/>')
        items.append(f'<item href="audio/{stem}.mp3" id="{audio_id}" media-type="audio/mpeg"/>')
    items.append('<item href="nav.xhtml" id="nav-xhtml"'
                 ' media-type="application/xhtml+xml" properties="nav"/>')
    opf = opf.replace("</manifest>", "    " + "\n    ".join(items) + "\n  </manifest>", 1)
    return opf


def nav_doc(chapters):
    """EPUB 3 navigation document from the chapter list."""
    lis = []
    for _idx, fname, _size, first in chapters:
        title = first.strip() or fname
        lis.append(f'    <li><a href={quoteattr(fname)}>{escape(title)}</a></li>')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<head>\n<title>Indice</title>\n'
        '<link href="stylesheet.css" type="text/css" rel="stylesheet"/>\n</head>\n'
        '<body>\n  <nav epub:type="toc" id="toc">\n'
        '    <h1>Indice</h1>\n    <ol>\n'
        + "\n".join(lis)
        + "\n    </ol>\n  </nav>\n</body>\n</html>\n"
    )


# ── Packaging ────────────────────────────────────────────────────────────────

def package(src_epub, out_epub, replacements, additions):
    """Rebuild the EPUB zip: mimetype first (stored), everything else deflated."""
    with zipfile.ZipFile(src_epub) as zin:
        names = zin.namelist()
        with zipfile.ZipFile(out_epub, "w") as zout:
            if "mimetype" in names:
                zout.writestr("mimetype", zin.read("mimetype"), zipfile.ZIP_STORED)
            for name in names:
                if name == "mimetype" or name.endswith("/"):
                    continue
                data = replacements.get(name)
                if data is None:
                    data = zin.read(name)
                zout.writestr(name, data, zipfile.ZIP_DEFLATED)
            for name, data in additions.items():
                zout.writestr(name, data, zipfile.ZIP_DEFLATED)


# ── Validation ──────────────────────────────────────────────────────────────

def validate(out_epub):
    """Structural checks; returns list of error strings."""
    errors = []
    ns_opf = "{http://www.idpf.org/2007/opf}"
    with zipfile.ZipFile(out_epub) as z:
        names = set(z.namelist())
        opf_root = ET.fromstring(z.read("content.opf"))
        if opf_root.get("version") != "3.0":
            errors.append("OPF version is not 3.0")
        manifest = opf_root.find(f"{ns_opf}manifest")
        items = {i.get("id"): i for i in manifest.findall(f"{ns_opf}item")}
        nav_items = [i for i in items.values() if "nav" in (i.get("properties") or "")]
        if not nav_items:
            errors.append("no nav document in manifest")
        elif nav_items[0].get("href") not in names:
            errors.append(f"nav document missing from zip: {nav_items[0].get('href')}")

        smil_items = {i.get("id"): i.get("href") for i in items.values()
                      if i.get("media-type") == "application/smil+xml"}
        overlay_refs = 0
        for i in items.values():
            mo = i.get("media-overlay")
            if mo:
                overlay_refs += 1
                if mo not in smil_items:
                    errors.append(f"media-overlay '{mo}' has no SMIL item")
        if not overlay_refs:
            errors.append("no content documents reference a media overlay")

        for smil_id, href in smil_items.items():
            if href not in names:
                errors.append(f"SMIL missing from zip: {href}")
                continue
            smil_root = ET.fromstring(z.read(href))
            ns_smil = "{http://www.w3.org/ns/SMIL}"
            body = smil_root.find(f"{ns_smil}body")
            if body is None or len(body) == 0:
                errors.append(f"{href}: empty body")
                continue
            prev_end = 0.0
            for par in body.findall(f"{ns_smil}par"):
                text_el = par.find(f"{ns_smil}text")
                audio_el = par.find(f"{ns_smil}audio")
                if text_el is None or audio_el is None:
                    errors.append(f"{href}: par without text/audio")
                    continue
                src = text_el.get("src", "")
                fname, _, frag_id = src.partition("#")
                if fname not in names:
                    errors.append(f"{href}: text src missing from zip: {fname}")
                    continue
                if f'id="{frag_id}"' not in z.read(fname).decode("utf-8", "replace"):
                    errors.append(f"{href}: anchor #{frag_id} not found in {fname}")
                asrc = audio_el.get("src", "")
                if asrc not in names:
                    errors.append(f"{href}: audio src missing from zip: {asrc}")
                try:
                    b = float(audio_el.get("clipBegin", "0s").rstrip("s"))
                    e = float(audio_el.get("clipEnd", "0s").rstrip("s"))
                except ValueError:
                    errors.append(f"{href}: bad clock values in par {par.get('id')}")
                    continue
                if e <= b:
                    errors.append(f"{href}: clipEnd <= clipBegin in par {par.get('id')}")
                if b < prev_end - 0.001:
                    errors.append(f"{href}: non-monotonic clip at par {par.get('id')}")
                prev_end = e
    return errors


# ── Per-chapter pipeline ─────────────────────────────────────────────────────

def process_chapter(z, client, args, fname, work_dir):
    """Full pipeline for one chapter. Returns a dict of results."""
    stem = Path(fname).stem
    ch_dir = work_dir / stem
    ch_dir.mkdir(parents=True, exist_ok=True)

    raw = z.read(fname).decode("utf-8")
    runs = text_runs(raw)
    frags = apply_slice(extract_fragments(raw, runs), args.slice)
    src = source_text(frags)
    print(f"  {len(frags)} fragments, {len(src)} source chars")

    chunks = chunk_text(src, max_chars=args.max_chars)
    prepared_parts = []
    for i, chunk in enumerate(chunks):
        print(f"  preparing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        prepared_parts.append(llm_prepare(client, args.model, chunk))
    prepared = "\n\n".join(prepared_parts)
    (ch_dir / "prepared_text.txt").write_text(prepared)

    lines = split_long_narration(parse_lines(prepared))
    segments = assign_voices(lines, andrew_short=args.andrew_short)
    cast = {}
    for _s, _g, _t, _v, voice_name in segments:
        cast[voice_name] = cast.get(voice_name, 0) + 1
    print(f"  {len(segments)} lines: " + ", ".join(f"{k} x{v}" for k, v in cast.items()))

    print("  synthesizing with edge-tts...")
    files, word_events = asyncio.run(
        synth_word_timed(segments, ch_dir, args.rate, args.workers))
    audio_path = ch_dir / "audio.mp3"
    offsets = concatenate(files, audio_path)
    total_dur = offsets[-1][1] if offsets else 0.0
    print(f"  audio: {total_dur:.1f}s ({clock_value(total_dur)})")

    frag_begin, n_orig, n_matched, n_prep = align_fragments(
        frags, segments, offsets, word_events)
    clips = build_clips(frags, frag_begin, total_dur)
    print(f"  alignment: {len(clips)}/{len(frags)} fragments clipped, "
          f"{n_matched}/{n_orig} source words matched "
          f"({100 * n_matched / max(n_orig, 1):.0f}%)")

    new_raw = inject_spans(raw, frags, clips)
    return {
        "stem": stem,
        "fname": fname,
        "xhtml": new_raw,
        "smil": smil_doc(stem, clips),
        "audio": audio_path.read_bytes(),
        "duration": total_dur,
        "n_frags": len(frags),
        "n_clips": len(clips),
        "word_match": (n_matched, n_orig),
    }


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="epub_mo: EPUB 3 Media Overlays read-along generator")
    parser.add_argument("--epub", help="Path to the source EPUB")
    parser.add_argument("--chapter", type=int,
                        help="Chapter index to process (see --list-chapters)")
    parser.add_argument("--all", action="store_true", help="Process all chapters")
    parser.add_argument("--slice", type=int,
                        help="Max source chars per chapter (test mode)")
    parser.add_argument("--output", help="Output EPUB path")
    parser.add_argument("--work-dir", default="out/mo_work",
                        help="Directory for intermediate segment files")
    parser.add_argument("--rate", default=RATE_DEFAULT,
                        help="edge-tts rate, e.g. -8%% (default)")
    parser.add_argument("--workers", type=int, default=WORKERS_DEFAULT,
                        help="Concurrent edge-tts requests (default %(default)s)")
    parser.add_argument("--model", default=LLM_MODEL_DEFAULT,
                        help="Mistral model for preparation")
    parser.add_argument("--max-chars", type=int, default=4000,
                        help="Max chars per LLM chunk")
    parser.add_argument("--andrew-short", action="store_true",
                        help="Use Andrew for one-line, very short male side roles")
    parser.add_argument("--list-chapters", action="store_true",
                        help="List EPUB chapters and exit")
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
        selected = chapters
    elif args.chapter is not None:
        if args.chapter < 0 or args.chapter >= len(chapters):
            print(f"ERROR: chapter index {args.chapter} out of range (0-{len(chapters) - 1})")
            sys.exit(1)
        selected = [chapters[args.chapter]]
    else:
        print("ERROR: provide --chapter N, --all, or --list-chapters")
        sys.exit(1)
    if not args.output:
        print("ERROR: --output is required for generation")
        sys.exit(1)

    load_env()
    if not os.environ.get("MISTRAL_API_KEY"):
        print("ERROR: MISTRAL_API_KEY not set (env or .env). Get one at https://console.mistral.ai")
        sys.exit(1)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    replacements = {}
    additions = {}
    chapter_entries = []
    durations = {}
    t0 = time.time()

    with zipfile.ZipFile(args.epub) as z:
        for pos, (idx, fname, size, first) in enumerate(selected):
            print(f"\n=== Chapter {idx} ({fname}) ===")
            result = process_chapter(z, client, args, fname, work_dir)
            stem = result["stem"]
            smil_id = f"mo-smil-{idx:03d}"
            audio_id = f"mo-audio-{idx:03d}"
            replacements[fname] = result["xhtml"]
            additions[f"{stem}.smil"] = result["smil"]
            additions[f"audio/{stem}.mp3"] = result["audio"]
            chapter_entries.append((stem, smil_id, audio_id))
            durations[stem] = result["duration"]

        css = z.read("stylesheet.css").decode("utf-8")
        opf = z.read("content.opf").decode("utf-8")

    if "mo-active" not in css:
        replacements["stylesheet.css"] = css + CSS_MO
    total_dur = sum(durations.values())
    replacements["content.opf"] = upgrade_opf(opf, chapter_entries, durations, total_dur)
    additions["nav.xhtml"] = nav_doc(chapters)

    print(f"\nPackaging {out_path}...")
    package(args.epub, out_path, replacements, additions)

    errors = validate(out_path)
    print(f"\n{'=' * 60}")
    print(f"DONE in {time.time() - t0:.0f}s -> {out_path}")
    print(f"  chapters with media overlays: {len(chapter_entries)}")
    print(f"  total audio: {clock_value(total_dur)}")
    if errors:
        print(f"  VALIDATION ERRORS ({len(errors)}):")
        for e in errors[:20]:
            print(f"    - {e}")
        sys.exit(1)
    print("  validation: OK")


if __name__ == "__main__":
    main()
