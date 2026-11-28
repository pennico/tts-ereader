"""EPUB parsing for the v1 reader (ARCHITECTURE_v1 §2.1 services/epub_parser.py).

Spine-based parsing via META-INF/container.xml + the OPF package, with the
v0 heuristic (sorted HTML files, as in poc_reader.py) as a fallback for EPUBs
without a readable OPF. Stdlib only: zipfile + html.parser + xml.etree.
"""
from __future__ import annotations

import html.parser
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

XHTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}
IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/svg+xml"}

CONTAINER_NS = "{urn:oasis:names:tc:opendocument:xmlns:container}"
OPF_NS = "{http://www.idpf.org/2007/opf}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"


@dataclass
class ParsedChapter:
    href: str
    title: str
    text: str


@dataclass
class ParsedBook:
    title: str
    author: str
    language: str
    chapters: list[ParsedChapter] = field(default_factory=list)
    cover: bytes | None = None
    cover_media_type: str | None = None


class _HTMLStripper(html.parser.HTMLParser):
    """Extract visible text, preserving paragraph breaks (as in poc_reader.py)."""

    def __init__(self):
        super().__init__()
        self.text = []
        self._skip = False
        self._in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag == "title":
            self._in_title = False
        if tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self.text.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        elif not self._skip:
            self.text.append(data)


def _strip_html(html_content: str):
    """Return (text, title): text with paragraphs joined by blank lines."""
    s = _HTMLStripper()
    s.feed(html_content)
    raw = "".join(s.text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
    lines = [line for line in lines if line]
    title = " ".join("".join(s.title_parts).split())
    return "\n\n".join(lines), title


def _read_text(z: zipfile.ZipFile, name: str) -> str:
    return z.read(name).decode("utf-8", errors="replace")


def _opf_path(z: zipfile.ZipFile) -> str | None:
    """Locate the OPF via META-INF/container.xml, or None."""
    try:
        container = _read_text(z, "META-INF/container.xml")
    except KeyError:
        return None
    try:
        root = ET.fromstring(container)
    except ET.ParseError:
        return None
    for rootfile in root.iter(f"{CONTAINER_NS}rootfile"):
        path = rootfile.get("full-path")
        if path and path in z.namelist():
            return path
    return None


def _parse_opf(opf_xml: str):
    """Return (title, author, language, manifest, spine).

    manifest: id -> (href, media_type, properties); spine: ordered item ids.
    """
    root = ET.fromstring(opf_xml)
    title = author = language = None
    for el in root.iter():
        if el.tag == f"{DC_NS}title" and el.text:
            title = el.text.strip()
        elif el.tag == f"{DC_NS}creator" and el.text:
            author = el.text.strip()
        elif el.tag == f"{DC_NS}language" and el.text:
            language = el.text.strip()
    manifest = {}
    for item in root.iter(f"{OPF_NS}item"):
        manifest[item.get("id")] = (
            item.get("href"),
            item.get("media-type") or "",
            item.get("properties") or "",
        )
    spine = [ref.get("idref") for ref in root.iter(f"{OPF_NS}itemref")]
    return title, author, language, manifest, spine


def _fallback_chapter_hrefs(z: zipfile.ZipFile) -> list[str]:
    """v0 heuristic (poc_reader.py): all HTML files, sorted by name."""
    return sorted(
        name for name in z.namelist()
        if name.endswith((".html", ".xhtml", ".htm"))
    )


def _chapter_title(text: str, doc_title: str, index: int) -> str:
    if doc_title:
        return doc_title
    first_line = text.split("\n", 1)[0]
    if first_line:
        return first_line[:80]
    return f"Chapter {index + 1}"


def parse_epub(epub_path: Path) -> ParsedBook:
    """Parse an EPUB into metadata, ordered chapters, and optional cover."""
    with zipfile.ZipFile(epub_path) as z:
        names = set(z.namelist())
        opf_name = _opf_path(z)
        title = author = language = None
        manifest = {}
        spine = []
        cover_href = None

        if opf_name:
            title, author, language, manifest, spine = _parse_opf(_read_text(z, opf_name))
            opf_dir = opf_name.rsplit("/", 1)[0] + "/" if "/" in opf_name else ""
            # Cover: EPUB3 cover-image property, else the conventional id.
            for item_id, (href, media_type, properties) in manifest.items():
                if "cover-image" in properties and media_type in IMAGE_MEDIA_TYPES:
                    cover_href = href
                    break
            if cover_href is None:
                for item_id, (href, media_type, _props) in manifest.items():
                    if "cover" in (item_id or "").lower() and media_type in IMAGE_MEDIA_TYPES:
                        cover_href = href
                        break

            chapter_hrefs = []
            for item_id in spine:
                entry = manifest.get(item_id)
                if not entry:
                    continue
                href, media_type, _props = entry
                if media_type in XHTML_MEDIA_TYPES or href.endswith((".html", ".xhtml", ".htm")):
                    chapter_hrefs.append(opf_dir + href)
            # Skip the nav document if it carries the nav property.
            nav_hrefs = {
                opf_dir + href
                for _id, (href, _mt, props) in manifest.items()
                if "nav" in props
            }
            chapter_hrefs = [h for h in chapter_hrefs if h not in nav_hrefs]
        else:
            opf_dir = ""
            chapter_hrefs = _fallback_chapter_hrefs(z)

        chapters: list[ParsedChapter] = []
        for index, href in enumerate(chapter_hrefs):
            if href not in names:
                continue
            text, doc_title = _strip_html(_read_text(z, href))
            chapters.append(
                ParsedChapter(
                    href=href,
                    title=_chapter_title(text, doc_title, index),
                    text=text,
                )
            )

        cover = cover_media_type = None
        if cover_href:
            full = cover_href if cover_href in names else opf_dir + cover_href
            if full in names:
                cover = z.read(full)
                for _id, (href, media_type, _props) in manifest.items():
                    if href == cover_href:
                        cover_media_type = media_type
                        break

        return ParsedBook(
            title=title or _fallback_title(chapters),
            author=author or "Unknown author",
            language=language or "",
            chapters=chapters,
            cover=cover,
            cover_media_type=cover_media_type,
        )


def _fallback_title(chapters: list[ParsedChapter]) -> str:
    """AC-005: graceful fallback when metadata is missing."""
    if chapters:
        return chapters[0].title
    return "Untitled"
