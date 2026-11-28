#!/usr/bin/env python3
"""Generate synthetic EPUB fixtures for testing (AC-901, SPEC_v1 §4).

No copyrighted books in the repo: every fixture is generated programmatically
with original placeholder text. Covers the cases SPEC_v1 §4.1 requires:

1. Plain narration (Italian, Danish)
2. Dialogue heavy (Italian Saramago-style, Danish Adler-Olsen-style)
3. Mixed content (narration + dialogue + footnotes)
4. Edge cases (empty paragraphs, special characters, mixed languages)

Usage:
    python3 tests/fixtures/make_fixture_epub.py --out-dir tests/fixtures/epubs
    python3 tests/fixtures/make_fixture_epub.py --list
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

NAV_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>{title}</title></head>
<body>
  <nav epub:type="toc">
    <h1>{title}</h1>
    <ol>
{items}
    </ol>
  </nav>
</body>
</html>
"""

CHAPTER_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title></head>
<body>
{body}
</body>
</html>
"""


def _opf(title: str, author: str, language: str, chapters: list, cover: str | None = None) -> str:
    manifest = ['    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
    if cover:
        manifest.append(
            f'    <item id="cover-image" href="{cover}" media-type="image/png" properties="cover-image"/>'
        )
    spine = []
    for fname, _chapter_title, _paras in chapters:
        item_id = fname.stem
        manifest.append(
            f'    <item id="{item_id}" href="{fname.name}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'    <itemref idref="{item_id}"/>')
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:fixture-{title.lower().replace(' ', '-')}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>{language}</dc:language>
  </metadata>
  <manifest>
{chr(10).join(manifest)}
  </manifest>
  <spine>
{chr(10).join(spine)}
  </spine>
</package>
"""


def _chapter_body(paragraphs: list) -> str:
    return "\n".join(f"    <p>{p}</p>" if p else "    <p></p>" for p in paragraphs)


def _tiny_png(width: int, height: int, rgb: tuple) -> bytes:
    """Minimal valid PNG (stdlib only) used as a synthetic cover image."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + bytes(rgb) * width for _ in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def write_epub(
    path: Path,
    title: str,
    author: str,
    language: str,
    chapters: list,
    cover: bool = False,
) -> Path:
    """Write a synthetic EPUB 3.

    chapters: list of (filename, chapter_title, [paragraphs]) — paragraphs may
    contain "" for the empty-paragraph edge case. cover=True embeds a tiny
    generated PNG declared with the EPUB3 cover-image property.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    cover_href = "cover.png" if cover else None
    with zipfile.ZipFile(path, "w") as z:
        # mimetype must be the first entry, uncompressed (EPUB spec)
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("OEBPS/content.opf", _opf(title, author, language, chapters, cover_href))
        if cover:
            z.writestr("OEBPS/cover.png", _tiny_png(64, 96, (63, 81, 120)))
        nav_items = "\n".join(
            f'      <li><a href="{fname.name}">{chapter_title}</a></li>'
            for fname, chapter_title, _paras in chapters
        )
        z.writestr("OEBPS/nav.xhtml", NAV_XHTML.format(title=title, items=nav_items))
        for fname, chapter_title, paras in chapters:
            z.writestr(
                f"OEBPS/{fname.name}",
                CHAPTER_XHTML.format(title=chapter_title, body=_chapter_body(paras)),
            )
    return path


# ── Synthetic text (original placeholder sentences, both languages) ──────────

_IT_NARRATION = [
    "La mattina scendeva lenta sulla valle, e la nebbia si alzava dai tetti come un respiro.",
    "L'uomo camminava lungo il fiume, contando i passi senza alcun motivo preciso.",
    "Ogni estate la piazza si riempiva di voci, di bambini che correvano tra i tavolini.",
    "La vecchia libreria all'angolo profumava di carta e di polvere, un odore che non cambiava mai.",
    "Quando il treno arrivò, la stazione era quasi vuota e il silenzio era pieno di attesa.",
]

_DA_NARRATION = [
    "Morgenen lå grå over byen, og regnet trommede stille mod ruderne.",
    "Han gik langs vandet og tænkte på alt det, han aldrig havde fået sagt.",
    "Om sommeren samledes byens børn på havnen, hvor fiskerne fortalte deres historier.",
    "Boghandelen på hjørnet duftede af papir og støv, en lugt der aldrig forandrede sig.",
    "Da toget endelig kom, var perronen næsten tom og stilheden fuld af forventning.",
]

# Saramago-style: long sentences, dialogue unmarked by quotes, speaker changes
# signalled only by commas and capital letters.
_IT_SARAMAGO = [
    "Forse non lo sapeva ancora, disse la donna, ma la verità era che nessuno di loro aveva mai davvero ascoltato, "
    "non ascoltato davvero, e questo, concluse l'uomo, è il modo in cui le famiglie si disfano, "
    "una parola non detta qui, un'altra non udita là, finché un giorno non resta più niente da dire.",
    "La città era strana quella sera, disse il ragazzo, le strade sembravano più lunghe del solito, "
    "e la donna annuì, perché anche lei lo aveva notato, eppure nessuno dei due volle dirlo ad alta voce, "
    "come se nominare la cosa potesse renderla permanente.",
]

# Adler-Olsen-style: dash-marked dialogue with clear speaker changes.
_DA_ADLER = [
    "„Hvad laver du her?“ spurgte hun og lukkede døren bag sig.\n"
    "„Jeg ventede på dig,“ svarede han. „Det tog længere tid end ventet.“",
    "„Vi skal tale om den nat,“ sagde hun.\n"
    "„Der findes ikke mere at tale om,“ svarede han koldt og vendte sig mod vinduet.",
]


def _repeat(sentences: list, paragraphs: int) -> list:
    out = []
    for i in range(paragraphs):
        out.append(" ".join(sentences[(i + j) % len(sentences)] for j in range(3)))
    return out


def _repeat_multiline(blocks: list, paragraphs: int) -> list:
    out = []
    for i in range(paragraphs):
        out.append(blocks[i % len(blocks)])
    return out


# ── Fixture builders (SPEC_v1 §4.2 signatures) ──────────────────────────────


def make_plain_narration_epub(language: str, word_count: int, out_dir: Path) -> Path:
    """Generate a synthetic EPUB with plain narration text."""
    sentences = _IT_NARRATION if language == "it" else _DA_NARRATION
    lang = "it-IT" if language == "it" else "da-DK"
    title = "Plain Narration (IT)" if language == "it" else "Plain Narration (DA)"
    paras = _repeat(sentences, max(2, word_count // 60))
    chapters = [
        (Path("chapter1.xhtml"), "Chapter 1", paras[: len(paras) // 2]),
        (Path("chapter2.xhtml"), "Chapter 2", paras[len(paras) // 2 :]),
    ]
    # The Italian plain-narration fixture carries a cover (AC-002 test path).
    return write_epub(
        out_dir / f"plain_{language}.epub",
        title,
        "Fixture Author",
        lang,
        chapters,
        cover=(language == "it"),
    )


def make_dialogue_epub(language: str, dialogue_ratio: float, out_dir: Path) -> Path:
    """Generate a synthetic EPUB with dialogue-heavy text."""
    if language == "it":
        blocks, lang, title = _IT_SARAMAGO, "it-IT", "Dialogue Heavy (IT, Saramago-style)"
    else:
        blocks, lang, title = _DA_ADLER, "da-DK", "Dialogue Heavy (DA, Adler-Olsen-style)"
    dialogue_paras = _repeat_multiline(blocks, 4)
    narration_paras = _repeat(_IT_NARRATION if language == "it" else _DA_NARRATION, 4)
    # interleave narration and dialogue according to dialogue_ratio (roughly)
    paras = []
    for d, n in zip(dialogue_paras, narration_paras):
        if dialogue_ratio >= 0.5:
            paras.extend([d, n])
        else:
            paras.extend([n, d])
    chapters = [(Path("chapter1.xhtml"), "Chapter 1", paras)]
    return write_epub(out_dir / f"dialogue_{language}.epub", title, "Fixture Author", lang, chapters)


def make_saramago_style_epub(word_count: int, out_dir: Path) -> Path:
    """Generate a synthetic EPUB mimicking Saramago's unmarked-dialogue style."""
    paras = _repeat_multiline(_IT_SARAMAGO, max(2, word_count // 80))
    chapters = [(Path("chapter1.xhtml"), "Capitolo primo", paras)]
    return write_epub(out_dir / "saramago_style.epub", "Saramago-style (synthetic)", "Fixture Author", "it-IT", chapters)


def make_mixed_content_epub(out_dir: Path) -> Path:
    """Narration + dialogue + footnotes in one EPUB."""
    paras = (
        _repeat(_IT_NARRATION, 2)
        + _repeat_multiline(_IT_SARAMAGO, 1)
        + ["Il termine «bibliofobia» designa la paura dei libri. [1]"]
        + ["[1] Nota dell'editore: la parola appare per la prima volta in un saggio del diciannovesimo secolo."]
    )
    chapters = [(Path("chapter1.xhtml"), "Capitolo misto", paras)]
    return write_epub(out_dir / "mixed_content.epub", "Mixed Content (synthetic)", "Fixture Author", "it-IT", chapters)


def make_edge_cases_epub(out_dir: Path) -> Path:
    """Empty paragraphs, special characters, mixed languages."""
    paras = [
        "",
        "Caratteri speciali: àèìòù «caporali» — apostrofi, cifre 123 e simboli §.",
        "Danske tegn: æøå og Århus, plus tankestreg — og citationstegn „sådan“.",
        "Mixed languages: la città var quiet, og regnen faldt stille over piazza.",
        "",
    ]
    chapters = [(Path("chapter1.xhtml"), "Edge cases", paras)]
    return write_epub(out_dir / "edge_cases.epub", "Edge Cases (synthetic)", "Fixture Author", "it-IT", chapters)


def make_all_fixtures(out_dir: Path) -> list:
    """Generate every required fixture; returns the list of paths."""
    return [
        make_plain_narration_epub("it", 600, out_dir),
        make_plain_narration_epub("da", 600, out_dir),
        make_dialogue_epub("it", 0.7, out_dir),
        make_dialogue_epub("da", 0.7, out_dir),
        make_saramago_style_epub(400, out_dir),
        make_mixed_content_epub(out_dir),
        make_edge_cases_epub(out_dir),
    ]


FIXTURES = {
    "plain_it": "Plain narration, Italian (2 chapters)",
    "plain_da": "Plain narration, Danish (2 chapters)",
    "dialogue_it": "Dialogue heavy, Saramago-style unmarked dialogue",
    "dialogue_da": "Dialogue heavy, Adler-Olsen-style dash dialogue",
    "saramago_style": "Long unmarked-dialogue sentences (Italian)",
    "mixed_content": "Narration + dialogue + footnotes",
    "edge_cases": "Empty paragraphs, special characters, mixed languages",
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic EPUB test fixtures")
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "epubs")
    ap.add_argument("--list", action="store_true", help="list fixtures and exit")
    args = ap.parse_args()
    if args.list:
        for name, desc in FIXTURES.items():
            print(f"{name:16} {desc}")
        return
    for path in make_all_fixtures(args.out_dir):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
