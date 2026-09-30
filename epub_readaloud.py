#!/usr/bin/env python3
"""epub_readaloud: simple read-along EPUB from the prepared reading text.

Unlike epub_mo.py (which injects overlays into the original book XHTML and
aligns cleaned words back to it), this builds a fresh, minimal EPUB whose
content IS the LLM-prepared reading text. Each line is a paragraph with an
id, paired in the SMIL to its exact audio segment (the offsets we computed
ourselves when concatenating). Displayed text and spoken text are identical
by construction — no alignment step that can make mistakes.

Usage:
  python3 epub_readaloud.py --epub book.epub --list-chapters
  python3 epub_readaloud.py --epub book.epub --chapter 4 --slice 4000 \
      --output out/readalong_test.epub
  python3 epub_readaloud.py --epub book.epub --all --output out/readalong.epub

NOTE on players: Apple Books (iPhone and Mac) ignores Media Overlays in
reflowable EPUBs, so it shows no read-aloud controls for any output of this
script. Test in Thorium Reader (Mac, free) which fully supports them.

Requires: MISTRAL_API_KEY (env or .env in the script directory), edge-tts,
pydub, ffmpeg.
"""

import argparse
import asyncio
import html as html_mod
import os
import re
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

try:
    from mistralai import Mistral
except ImportError:  # mistralai 2.x: client moved off the top level
    from mistralai.client import Mistral

from poc_reader import chunk_text, extract_epub_chapter, list_epub_chapters
from edge_reader import (
    LLM_MODEL_DEFAULT,
    RATE_DEFAULT,
    WORKERS_DEFAULT,
    assign_voices,
    concatenate,
    llm_prepare,
    load_env,
    parse_lines,
    split_long_narration,
    synthesize,
)
from epub_mo import clock_value, validate

SCRIPT_DIR = Path(__file__).resolve().parent

CSS = """body { font-family: Georgia, serif; margin: 1em 1.5em; }
h1 { font-size: 1.3em; font-weight: normal; margin: 2em 0 1em 0; }
p { line-height: 1.6; margin: 0 0 0.6em 0; }
p.d { margin-left: 1.5em; }
.mo-active { background-color: #ffe89a; }
.mo-playing { color: inherit; }
"""

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def slice_text(text, budget):
    """Cut at a paragraph boundary so the budget is not exceeded mid-paragraph."""
    if not budget or len(text) <= budget:
        return text
    out, total = [], 0
    for para in text.split("\n\n"):
        if total + len(para) > budget and out:
            break
        out.append(para)
        total += len(para)
    return "\n\n".join(out)


def chapter_xhtml(title, segments):
    """One paragraph per prepared line, each wrapped in an id span."""
    paras = [f"  <h1>{escape(title)}</h1>"]
    for i, (speaker, _gender, text, _voice, _voice_name) in enumerate(segments):
        cls = ' class="d"' if speaker else ""
        paras.append(f'  <p{cls}><span id="mo-{i}">{escape(text)}</span></p>')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<head>\n"
        f"<title>{escape(title)}</title>\n"
        '<link href="styles.css" type="text/css" rel="stylesheet"/>\n'
        "</head>\n<body>\n"
        + "\n".join(paras)
        + "\n</body>\n</html>\n"
    )


def chapter_smil(ch_id, offsets):
    """One par per segment, clips = the exact concatenation offsets."""
    pars = []
    for i, (start, end) in enumerate(offsets):
        pars.append(
            f'  <par id="par-{i}">'
            f'<text src="{ch_id}.xhtml#mo-{i}"/>'
            f'<audio src="audio/{ch_id}.mp3" clipBegin="{start:.3f}s" clipEnd="{end:.3f}s"/>'
            f"</par>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<smil xmlns="http://www.w3.org/ns/SMIL"'
        ' xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">\n'
        f'<body epub:textref="{ch_id}.xhtml">\n'
        + "\n".join(pars)
        + "\n</body>\n</smil>\n"
    )


def nav_doc(entries):
    """entries: list of (ch_id, title)."""
    lis = [f'    <li><a href="{ch}.xhtml">{escape(title)}</a></li>'
           for ch, title in entries]
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<head>\n<title>Indice</title>\n"
        '<link href="styles.css" type="text/css" rel="stylesheet"/>\n</head>\n'
        '<body>\n  <nav epub:type="toc" id="toc">\n'
        "    <h1>Indice</h1>\n    <ol>\n"
        + "\n".join(lis)
        + "\n    </ol>\n  </nav>\n</body>\n</html>\n"
    )


def build_opf(title, creator, chapter_ids, durations):
    """EPUB 3 package document from scratch."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = sum(durations.values())
    metas = [
        f"    <dc:identifier id=\"pub-id\">urn:uuid:{uuid.uuid4()}</dc:identifier>",
        f"    <dc:title>{escape(title)}</dc:title>",
        '    <dc:language>it</dc:language>',
        f"    <dc:creator>{escape(creator)}</dc:creator>",
        f"    <meta property=\"dcterms:modified\">{now}</meta>",
        f"    <meta property=\"media:duration\">{clock_value(total)}</meta>",
        '    <meta property="media:active-class">mo-active</meta>',
        '    <meta property="media:playback-active-class">mo-playing</meta>',
    ]
    for ch in chapter_ids:
        metas.append(
            f'    <meta property="media:duration" refines="#ov-{ch}">'
            f"{clock_value(durations[ch])}</meta>")
    items = [
        '    <item href="nav.xhtml" id="nav" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item href="styles.css" id="css" media-type="text/css"/>',
    ]
    for ch in chapter_ids:
        items.append(f'    <item href="{ch}.xhtml" id="tx-{ch}"'
                     f' media-type="application/xhtml+xml" media-overlay="ov-{ch}"/>')
        items.append(f'    <item href="{ch}.smil" id="ov-{ch}" media-type="application/smil+xml"/>')
        items.append(f'    <item href="audio/{ch}.mp3" id="au-{ch}" media-type="audio/mpeg"/>')
    spine = [f'    <itemref idref="tx-{ch}"/>' for ch in chapter_ids]
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(metas)
        + "\n  </metadata>\n  <manifest>\n"
        + "\n".join(items)
        + "\n  </manifest>\n  <spine>\n"
        + "\n".join(spine)
        + "\n  </spine>\n</package>\n"
    )


def source_metadata(epub_path):
    """Title and first creator from the source EPUB's OPF, with fallbacks."""
    title, creator = Path(epub_path).stem, "Unknown"
    try:
        with zipfile.ZipFile(epub_path) as z:
            opf = z.read("content.opf").decode("utf-8", "replace")
        m = re.search(r"<dc:title>(.*?)</dc:title>", opf, re.S)
        if m:
            title = html_mod.unescape(m.group(1)).strip()
        m = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", opf, re.S)
        if m:
            creator = html_mod.unescape(m.group(1)).strip()
    except (KeyError, zipfile.BadZipFile):
        pass
    return title, creator


def _norm(s):
    return re.sub(r"[^a-zà-ÿ0-9]", "", s.lower())


def strip_title_leak(text, book_title):
    """Drop a leading paragraph that is just the book title.

    extract_epub_chapter includes the source <title> tag text, which would
    otherwise be read aloud at the start of every chapter.
    """
    paras = text.split("\n\n")
    if paras and len(_norm(paras[0])) > 10 and _norm(book_title).startswith(_norm(paras[0])):
        return "\n\n".join(paras[1:]).lstrip("\n")
    return text


def process_chapter(client, args, idx, work_dir):
    """Full pipeline for one chapter of the source EPUB."""
    ch_id = f"ch{idx:03d}"
    ch_dir = work_dir / ch_id
    ch_dir.mkdir(parents=True, exist_ok=True)

    book_title, _creator = source_metadata(args.epub)
    text = strip_title_leak(
        slice_text(extract_epub_chapter(args.epub, idx), args.slice), book_title)
    chunks = chunk_text(text, max_chars=args.max_chars)
    prepared_parts = []
    for i, chunk in enumerate(chunks):
        print(f"  preparing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        prepared_parts.append(llm_prepare(client, args.model, chunk))
    prepared = "\n\n".join(prepared_parts)
    (ch_dir / "prepared_text.txt").write_text(prepared)

    segments = assign_voices(
        split_long_narration(parse_lines(prepared)), andrew_short=args.andrew_short)
    cast = {}
    for _s, _g, _t, _v, voice_name in segments:
        cast[voice_name] = cast.get(voice_name, 0) + 1
    print(f"  {len(segments)} lines: " + ", ".join(f"{k} x{v}" for k, v in cast.items()))

    print("  synthesizing with edge-tts...")
    files = asyncio.run(synthesize(segments, ch_dir, args.rate, args.workers))
    audio_path = ch_dir / "audio.mp3"
    offsets = concatenate(files, audio_path)
    duration = offsets[-1][1] if offsets else 0.0
    print(f"  audio: {duration:.1f}s ({clock_value(duration)})")

    title = f"Capitolo {idx + 1}"
    return {
        "ch_id": ch_id,
        "title": title,
        "xhtml": chapter_xhtml(title, segments),
        "smil": chapter_smil(ch_id, offsets),
        "audio": audio_path.read_bytes(),
        "duration": duration,
    }


def main():
    parser = argparse.ArgumentParser(
        description="epub_readaloud: simple read-along EPUB from prepared text")
    parser.add_argument("--epub", help="Path to the source EPUB")
    parser.add_argument("--chapter", type=int,
                        help="Chapter index to process (see --list-chapters)")
    parser.add_argument("--all", action="store_true", help="Process all chapters")
    parser.add_argument("--slice", type=int,
                        help="Max source chars per chapter (test mode)")
    parser.add_argument("--output", help="Output EPUB path")
    parser.add_argument("--work-dir", default="out/readaloud_work",
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
        print("ERROR: MISTRAL_API_KEY not set (env or .env). Get one at https://console.mistral.ai")
        sys.exit(1)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    files = {"META-INF/container.xml": CONTAINER, "styles.css": CSS}
    chapter_ids = []
    durations = {}
    t0 = time.time()

    for idx in indices:
        print(f"\n=== Chapter {idx} ===")
        result = process_chapter(client, args, idx, work_dir)
        ch = result["ch_id"]
        files[f"{ch}.xhtml"] = result["xhtml"]
        files[f"{ch}.smil"] = result["smil"]
        files[f"audio/{ch}.mp3"] = result["audio"]
        chapter_ids.append(ch)
        durations[ch] = result["duration"]

    title, creator = source_metadata(args.epub)
    files["nav.xhtml"] = nav_doc(
        [(ch, f"Capitolo {i + 1}") for i, ch in zip(indices, chapter_ids)])
    files["content.opf"] = build_opf(f"{title} (lettura)", creator, chapter_ids, durations)

    print(f"\nPackaging {out_path}...")
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
    print("  NOTE: Apple Books ignores Media Overlays in reflowable EPUBs.")
    print("  Test in Thorium Reader (Mac) which supports them fully.")


if __name__ == "__main__":
    main()
