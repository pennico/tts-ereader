"""Chapter numbering (review C221, finding 1): --list-chapters, --chapter N
and --all must share one index, in the book's reading order (OPF spine).

Before the fix the list numbered every HTML file while --chapter counted
only the substantive ones, so a short cover page shifted every chapter by
one; and files were taken in file-name order ("ch10" before "ch2").
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poc_reader import extract_epub_chapter, list_epub_chapters

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title></metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="c10" href="text/ch%2010.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="cover"/><itemref idref="c2"/><itemref idref="c10"/></spine>
</package>"""


def _page(text):
    return f"<html><body><p>{text}</p></body></html>"


def _epub(path, with_opf=True):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        if with_opf:
            z.writestr("META-INF/container.xml", CONTAINER)
            z.writestr("OEBPS/content.opf", OPF)
        # Long nav page that is not in the spine: never a chapter.
        z.writestr("OEBPS/nav.xhtml", _page("Indice " * 60))
        z.writestr("OEBPS/cover.xhtml", _page("Cover"))
        z.writestr("OEBPS/text/ch2.xhtml", _page("Primo capitolo. " * 20))
        z.writestr("OEBPS/text/ch 10.xhtml", _page("Secondo capitolo. " * 20))
    return path


def test_list_and_extract_share_one_index_in_spine_order(tmp_path):
    epub = _epub(tmp_path / "b.epub")
    chapters = list_epub_chapters(epub)
    assert [c[0] for c in chapters] == [0, 1]
    assert [c[1] for c in chapters] == ["OEBPS/text/ch2.xhtml",
                                        "OEBPS/text/ch 10.xhtml"]
    for idx, _f, _n, first in chapters:
        assert extract_epub_chapter(epub, idx).startswith(first)
    assert extract_epub_chapter(epub, 0).startswith("Primo")
    assert extract_epub_chapter(epub, 1).startswith("Secondo")


def test_without_opf_falls_back_to_sorted_file_names(tmp_path):
    epub = _epub(tmp_path / "b.epub", with_opf=False)
    chapters = list_epub_chapters(epub)
    # No spine: every long HTML file, in name order, numbered from 0.
    assert [c[0] for c in chapters] == list(range(len(chapters)))
    for idx, _f, _n, first in chapters:
        assert extract_epub_chapter(epub, idx).startswith(first)


def test_metadata_follows_container_xml(tmp_path):
    """Title and language come from the OPF that container.xml names
    (here OEBPS/content.opf, not the root), for the prep prompt."""
    from epub_readaloud import source_language, source_metadata

    epub = tmp_path / "b.epub"
    opf = OPF.replace("<dc:title>T</dc:title>",
                      "<dc:title>Libro</dc:title><dc:creator>Autore</dc:creator>"
                      "<dc:language>it</dc:language>")
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
    assert source_metadata(epub) == ("Libro", "Autore")
    assert source_language(epub) == "it"
    assert source_language(_epub(tmp_path / "c.epub", with_opf=False)) is None
