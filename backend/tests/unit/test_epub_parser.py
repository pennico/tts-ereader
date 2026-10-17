"""Unit tests for the EPUB parser (spine order, metadata, fallbacks)."""
from __future__ import annotations

import zipfile

from app.services.epub_parser import parse_epub


def test_parses_metadata_and_spine_order(fixture_epubs):
    book = parse_epub(fixture_epubs["plain_it"])
    assert book.title == "Plain Narration (IT)"
    assert book.author == "Fixture Author"
    assert book.language == "it-IT"
    # Spine order: chapter1 before chapter2, nav document excluded.
    assert [c.href for c in book.chapters] == [
        "OEBPS/chapter1.xhtml",
        "OEBPS/chapter2.xhtml",
    ]


def test_chapter_text_is_extracted_with_paragraphs(fixture_epubs):
    book = parse_epub(fixture_epubs["plain_da"])
    text = book.chapters[0].text
    assert "Morgenen lå grå over byen" in text
    assert "\n\n" in text  # paragraph breaks preserved


def test_chapter_titles_come_from_document_title(fixture_epubs):
    book = parse_epub(fixture_epubs["plain_it"])
    assert book.chapters[0].title == "Chapter 1"
    assert book.chapters[1].title == "Chapter 2"


def test_danish_special_characters_survive(fixture_epubs):
    book = parse_epub(fixture_epubs["edge_cases"])
    text = book.chapters[0].text
    assert "æøå" in text
    assert "Århus" in text
    assert "«caporali»" in text


def test_empty_paragraphs_are_dropped_not_crash(fixture_epubs):
    book = parse_epub(fixture_epubs["edge_cases"])
    assert all(par for par in book.chapters[0].text.split("\n\n"))


def test_fallback_when_no_opf(tmp_path):
    """EPUB without container.xml/OPF falls back to the v0 heuristic."""
    epub = tmp_path / "no_opf.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("b.xhtml", "<html><head><title>B</title></head><body><p>Secondo</p></body></html>")
        z.writestr("a.xhtml", "<html><head><title>A</title></head><body><p>Primo</p></body></html>")
    book = parse_epub(epub)
    assert [c.href for c in book.chapters] == ["a.xhtml", "b.xhtml"]
    assert book.chapters[0].text == "Primo"
    # AC-005: graceful fallback title when metadata is missing.
    assert book.title == "A"
    assert book.author == "Unknown author"


def test_missing_metadata_falls_back_to_first_line(tmp_path):
    epub = tmp_path / "bare.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "<rootfiles><rootfile full-path='content.opf' media-type='application/oebps-package+xml'/>"
            "</rootfiles></container>",
        )
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            "<manifest><item id='c1' href='c1.xhtml' media-type='application/xhtml+xml'/></manifest>"
            "<spine><itemref idref='c1'/></spine></package>",
        )
        z.writestr(
            "c1.xhtml",
            "<html><body><p>La porta era chiusa da tempo.</p></body></html>",
        )
    book = parse_epub(epub)
    assert book.title == "La porta era chiusa da tempo."
    assert book.author == "Unknown author"


def test_saramago_style_fixture_has_unmarked_dialogue(fixture_epubs):
    book = parse_epub(fixture_epubs["saramago_style"])
    text = book.chapters[0].text
    # Long sentence with comma-separated dialogue, no quote marks.
    assert "disse la donna" in text
    assert '"' not in text and "„" not in text
