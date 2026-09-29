#!/usr/bin/env python3
"""epub_fixedlayout: fixed-layout read-along EPUB (Apple Books compatible).

Apple Books (iPhone + Mac) ignores Media Overlays in reflowable EPUBs but
plays them in fixed-layout (pre-paginated) books. This script builds a
fixed-layout variant of the epub_readaloud output: the LLM-prepared reading
text paginated into fixed-size pages, one XHTML + SMIL per page, one audio
file per chapter (page SMILs clip into it), and the rendition:layout /
rendition:viewport metadata Apple Books requires.

Usage:
  python3 epub_fixedlayout.py --epub book.epub --list-chapters
  python3 epub_fixedlayout.py --epub book.epub --chapter 4 --slice 4000 \
      --output out/fx_test.epub
  python3 epub_fixedlayout.py --epub book.epub --all --output out/fx.epub

  # No API key needed: tiny demo book for Apple Books device QA
  python3 epub_fixedlayout.py --demo --output out/fx_demo.epub

Pagination is by character budget (--chars-per-page): consecutive lines are
grouped onto a page until the budget is exceeded; a line is never split
across pages. Real-device QA (does the text fit the viewport?) is expected
to tune --chars-per-page and --viewport per book.

Requires: MISTRAL_API_KEY for the full pipeline (not for --demo), edge-tts,
pydub, ffmpeg.
"""

import argparse
import asyncio
import os
import re
import sys
import time
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

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
from epub_readaloud import slice_text, source_metadata, strip_title_leak

SCRIPT_DIR = Path(__file__).resolve().parent

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

# Short original text in prepared format (speaker tags, no LLM needed).
# Used by --demo to produce a tiny test book for Apple Books device QA.
DEMO_TEXT = """NARRATORE [m]: La città si svegliò sotto una pioggia sottile, e le strade lucide riflettevano le vetrine spente dei negozi.
NARRATORE [m]: Al binario nove, il treno per Lisbona aspettava con le portiere aperte, e un odore di caffè usciva dal vagone ristorante.
MARIA [f]: Sei in ritardo, ti aspettavo da mezz'ora.
NARRATORE [m]: Lei aveva l'ombrello chiuso in mano e i capelli bagnati, come se avesse attraversato la pioggia senza accorgersene.
PAOLO [m]: Il traffico, lo sai com'è a quest'ora.
MARIA [f]: Andiamo, il posto che ho scelto ha una finestra che guarda i binari.
NARRATORE [m]: Salirono sul treno mentre la pioggia diventava più forte, e la città scivolò via dietro il vetro come una fotografia sfocata."""


def page_css(width, height):
    pad_x = int(width * 0.09)
    pad_y = int(height * 0.07)
    return f"""body {{ margin: 0; }}
.page {{
  box-sizing: border-box;
  width: {width}px;
  height: {height}px;
  padding: {pad_y}px {pad_x}px;
  overflow: hidden;
  font-family: Georgia, serif;
  font-size: 26px;
  line-height: 1.55;
}}
h1 {{
  font-size: 34px;
  font-weight: normal;
  margin: 0 0 1em 0;
  text-align: center;
}}
p {{ margin: 0 0 0.9em 0; }}
p.d {{ margin-left: 1.2em; text-indent: -1.2em; }}
.mo-active {{ background-color: #ffe89a; }}
.mo-playing {{ color: inherit; }}
"""


def paginate(segments, chars_per_page):
    """Group consecutive segments into pages under a character budget.

    Returns a list of pages; each page is a list of (global_index, segment).
    A single segment longer than the budget gets a page of its own; segments
    are never split across pages (each segment is one SMIL par/clip).
    """
    pages, cur, total = [], [], 0
    for i, seg in enumerate(segments):
        n = len(seg[2])
        if cur and total + n > chars_per_page:
            pages.append(cur)
            cur, total = [], 0
        cur.append((i, seg))
        total += n
    if cur:
        pages.append(cur)
    return pages


def page_xhtml(title, page_items, width, height):
    """One fixed page. page_items: list of (global_index, segment)."""
    paras = []
    for _i, (speaker, _gender, text, _voice, _voice_name) in page_items:
        cls = ' class="d"' if speaker else ""
        paras.append(f'  <p{cls}><span id="mo-{_i}">{escape(text)}</span></p>')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<head>\n"
        f"<title>{escape(title)}</title>\n"
        f'<meta name="viewport" content="width={width}, height={height}"/>\n'
        '<link href="styles.css" type="text/css" rel="stylesheet"/>\n'
        "</head>\n<body>\n"
        '<div class="page">\n'
        + "\n".join(paras)
        + "\n</div>\n</body>\n</html>\n"
    )


def page_smil(ch_id, page_id, page_items, offsets):
    """One par per segment on the page, clipping into the chapter audio."""
    pars = []
    for i, _seg in page_items:
        start, end = offsets[i]
        pars.append(
            f'  <par id="par-{i}">'
            f'<text src="{page_id}.xhtml#mo-{i}"/>'
            f'<audio src="audio/{ch_id}.mp3"'
            f' clipBegin="{start:.3f}s" clipEnd="{end:.3f}s"/>'
            f"</par>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<smil xmlns="http://www.w3.org/ns/SMIL"'
        ' xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">\n'
        f'<body epub:textref="{page_id}.xhtml">\n'
        + "\n".join(pars)
        + "\n</body>\n</smil>\n"
    )


def nav_doc(entries):
    """entries: list of (href, title) — one per chapter, pointing at its first page."""
    lis = [f'    <li><a href="{href}">{escape(title)}</a></li>'
           for href, title in entries]
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


def build_opf(title, creator, chapters, width, height):
    """EPUB 3 fixed-layout package document.

    chapters: list of dicts {ch_id, title, page_ids, duration}.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    total = sum(ch["duration"] for ch in chapters)
    metas = [
        f'    <dc:identifier id="pub-id">urn:uuid:{uuid.uuid4()}</dc:identifier>',
        f"    <dc:title>{escape(title)}</dc:title>",
        '    <dc:language>it</dc:language>',
        f"    <dc:creator>{escape(creator)}</dc:creator>",
        f"    <meta property=\"dcterms:modified\">{now}</meta>",
        '    <meta property="rendition:layout">pre-paginated</meta>',
        f'    <meta property="rendition:viewport">width={width}, height={height}</meta>',
        f'    <meta property="media:duration">{clock_value(total)}</meta>',
        '    <meta property="media:active-class">mo-active</meta>',
        '    <meta property="media:playback-active-class">mo-playing</meta>',
    ]
    for ch in chapters:
        for p in ch["page_ids"]:
            metas.append(
                f'    <meta property="media:duration" refines="#ov-{p}">'
                f"{clock_value(ch['page_durations'][p])}</meta>")
    items = [
        '    <item href="nav.xhtml" id="nav" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item href="styles.css" id="css" media-type="text/css"/>',
    ]
    for ch in chapters:
        for p in ch["page_ids"]:
            items.append(f'    <item href="{p}.xhtml" id="tx-{p}"'
                         f' media-type="application/xhtml+xml" media-overlay="ov-{p}"/>')
            items.append(f'    <item href="{p}.smil" id="ov-{p}" media-type="application/smil+xml"/>')
        items.append(f'    <item href="audio/{ch["ch_id"]}.mp3" id="au-{ch["ch_id"]}"'
                     f' media-type="audio/mpeg"/>')
    spine = []
    for ch in chapters:
        for p in ch["page_ids"]:
            spine.append(f'    <itemref idref="tx-{p}"/>')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf"'
        ' xmlns:rendition="http://www.idpf.org/vocab/rendition/"'
        ' version="3.0" unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(metas)
        + "\n  </metadata>\n  <manifest>\n"
        + "\n".join(items)
        + "\n  </manifest>\n  <spine>\n"
        + "\n".join(spine)
        + "\n  </spine>\n</package>\n"
    )


def build_book(chapters, title, creator, width, height, out_path):
    """Package the fixed-layout EPUB. chapters: dicts from process_chapter().

    Each chapter dict: {ch_id, title, segments, offsets, audio (bytes), duration}.
    """
    files = {"META-INF/container.xml": CONTAINER,
             "styles.css": page_css(width, height)}
    opf_chapters = []
    for ch in chapters:
        pages = paginate(ch["segments"], ch["chars_per_page"])
        page_ids = []
        page_durations = {}
        for pi, page_items in enumerate(pages):
            page_id = f"{ch['ch_id']}-p{pi:03d}"
            files[f"{page_id}.xhtml"] = page_xhtml(ch["title"], page_items, width, height)
            files[f"{page_id}.smil"] = page_smil(ch["ch_id"], page_id, page_items, ch["offsets"])
            first, last = page_items[0][0], page_items[-1][0]
            page_durations[page_id] = ch["offsets"][last][1] - ch["offsets"][first][0]
            page_ids.append(page_id)
        files[f"audio/{ch['ch_id']}.mp3"] = ch["audio"]
        opf_chapters.append({
            "ch_id": ch["ch_id"],
            "title": ch["title"],
            "page_ids": page_ids,
            "page_durations": page_durations,
            "duration": ch["duration"],
        })
    files["nav.xhtml"] = nav_doc([(c["page_ids"][0], c["title"]) for c in opf_chapters])
    files["content.opf"] = build_opf(title, creator, opf_chapters, width, height)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        for name, data in files.items():
            z.writestr(name, data, zipfile.ZIP_DEFLATED)
    return len(opf_chapters), sum(c["duration"] for c in opf_chapters)


def validate_fixed(out_epub, width, height):
    """epub_mo.validate plus fixed-layout specific checks."""
    errors = validate(out_epub)
    ns_opf = "{http://www.idpf.org/2007/opf}"
    with zipfile.ZipFile(out_epub) as z:
        names = set(z.namelist())
        opf_root = ET.fromstring(z.read("content.opf"))
        metas = opf_root.find(f"{ns_opf}metadata")
        props = {m.get("property"): (m.text or "").strip()
                 for m in metas.findall(f"{ns_opf}meta")}
        if props.get("rendition:layout") != "pre-paginated":
            errors.append("rendition:layout is not pre-paginated")
        if props.get("rendition:viewport") != f"width={width}, height={height}":
            errors.append(f"rendition:viewport mismatch: {props.get('rendition:viewport')!r}")
        spine = opf_root.find(f"{ns_opf}spine")
        spine_hrefs = []
        manifest = {i.get("id"): i.get("href")
                    for i in opf_root.find(f"{ns_opf}manifest").findall(f"{ns_opf}item")}
        for itemref in spine.findall(f"{ns_opf}itemref"):
            href = manifest.get(itemref.get("idref"))
            if href is None:
                errors.append(f"spine idref {itemref.get('idref')} not in manifest")
                continue
            spine_hrefs.append(href)
            if href not in names:
                errors.append(f"spine document missing from zip: {href}")
                continue
            doc = z.read(href).decode("utf-8", "replace")
            if f'content="width={width}, height={height}"' not in doc:
                errors.append(f"{href}: missing viewport meta {width}x{height}")
        if not spine_hrefs:
            errors.append("empty spine")
    return errors


def process_chapter(client, args, idx, work_dir):
    """Full pipeline for one chapter of the source EPUB (same as epub_readaloud)."""
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

    return {
        "ch_id": ch_id,
        "title": f"Capitolo {idx + 1}",
        "segments": segments,
        "offsets": offsets,
        "audio": audio_path.read_bytes(),
        "duration": duration,
        "chars_per_page": args.chars_per_page,
    }


def parse_viewport(spec):
    m = re.match(r"^(\d+)[xX](\d+)$", spec.strip())
    if not m:
        raise argparse.ArgumentTypeError(
            "viewport must be WIDTHxHEIGHT, e.g. 768x1024")
    w, h = int(m.group(1)), int(m.group(2))
    if w < 200 or h < 200 or w > 4096 or h > 4096:
        raise argparse.ArgumentTypeError("viewport dimensions out of range")
    return w, h


def run_demo(args, width, height):
    """Tiny fixed-layout book from bundled text: no LLM, no API key.

    Synthesizes a handful of short lines with edge-tts so the owner can check
    that Apple Books shows read-aloud controls and highlighting on device.
    """
    work_dir = Path(args.work_dir) / "demo"
    work_dir.mkdir(parents=True, exist_ok=True)
    segments = assign_voices(parse_lines(DEMO_TEXT))
    print(f"demo: {len(segments)} lines, synthesizing with edge-tts...")
    files = asyncio.run(synthesize(segments, work_dir, args.rate, args.workers))
    offsets = concatenate(files, work_dir / "audio.mp3")
    chapter = {
        "ch_id": "ch000",
        "title": "Demo lettura",
        "segments": segments,
        "offsets": offsets,
        "audio": (work_dir / "audio.mp3").read_bytes(),
        "duration": offsets[-1][1] if offsets else 0.0,
        "chars_per_page": args.chars_per_page,
    }
    n_ch, total = build_book([chapter], "Demo read-along (tts-ereader)",
                              "tts-ereader", width, height, args.output)
    return n_ch, total, len(segments)


def main():
    parser = argparse.ArgumentParser(
        description="epub_fixedlayout: fixed-layout read-along EPUB (Apple Books)")
    parser.add_argument("--epub", help="Path to the source EPUB")
    parser.add_argument("--chapter", type=int,
                        help="Chapter index to process (see --list-chapters)")
    parser.add_argument("--all", action="store_true", help="Process all chapters")
    parser.add_argument("--slice", type=int,
                        help="Max source chars per chapter (test mode)")
    parser.add_argument("--output", help="Output EPUB path")
    parser.add_argument("--work-dir", default="out/fixedlayout_work",
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
    parser.add_argument("--chars-per-page", type=int, default=900,
                        help="Character budget per fixed-layout page (default 900)")
    parser.add_argument("--viewport", type=parse_viewport, default=(768, 1024),
                        help="Page size as WIDTHxHEIGHT (default 768x1024)")
    parser.add_argument("--demo", action="store_true",
                        help="Build a tiny demo book (no API key needed) and exit")
    args = parser.parse_args()

    width, height = args.viewport

    if args.demo:
        if not args.output:
            print("ERROR: --output is required for --demo")
            sys.exit(1)
        t0 = time.time()
        n_ch, total, n_seg = run_demo(args, width, height)
        _finish(args.output, t0, n_ch, total, width, height,
                extra=f"  demo lines: {n_seg}")
        return

    if not args.epub:
        print("ERROR: --epub is required (or use --demo)")
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
        print("ERROR: provide --chapter N, --all, --list-chapters, or --demo")
        sys.exit(1)
    if not args.output:
        print("ERROR: --output is required for generation")
        sys.exit(1)

    load_env()
    if not os.environ.get("MISTRAL_API_KEY"):
        print("ERROR: MISTRAL_API_KEY not set (env or .env). Get one at https://console.mistral.ai")
        sys.exit(1)

    from mistralai import Mistral
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    results = []
    for idx in indices:
        print(f"\n=== Chapter {idx} ===")
        results.append(process_chapter(client, args, idx, work_dir))

    title, creator = source_metadata(args.epub)
    n_ch, total = build_book(results, f"{title} (lettura)", creator,
                             width, height, args.output)
    _finish(args.output, t0, n_ch, total, width, height)


def _finish(out_path, t0, n_ch, total, width, height, extra=None):
    errors = validate_fixed(out_path, width, height)
    print(f"\n{'=' * 60}")
    print(f"DONE in {time.time() - t0:.0f}s -> {out_path}")
    print(f"  chapters: {n_ch}, total audio: {clock_value(total)}")
    print(f"  fixed layout: {width}x{height}")
    if extra:
        print(extra)
    if errors:
        print(f"  VALIDATION ERRORS ({len(errors)}):")
        for e in errors[:20]:
            print(f"    - {e}")
        sys.exit(1)
    print("  validation: OK (structure + fixed-layout metadata)")
    print("  Next: open in Apple Books (iPhone/Mac) and look for the")
    print("  read-aloud play button. Tune --chars-per-page if text overflows.")


if __name__ == "__main__":
    main()
