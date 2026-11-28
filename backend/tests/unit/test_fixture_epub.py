"""Unit tests for the synthetic fixture generator itself (AC-901)."""
from __future__ import annotations

import zipfile

import make_fixture_epub as m


def test_all_fixtures_are_valid_epub_zips(tmp_path):
    paths = m.make_all_fixtures(tmp_path)
    assert len(paths) == 7
    for path in paths:
        assert path.exists() and path.stat().st_size > 0
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            assert names[0] == "mimetype"  # first entry, per EPUB spec
            assert z.read("mimetype") == b"application/epub+zip"
            assert "META-INF/container.xml" in names
            assert "OEBPS/content.opf" in names


def test_plain_narration_covers_both_languages(tmp_path):
    it = m.make_plain_narration_epub("it", 600, tmp_path)
    da = m.make_plain_narration_epub("da", 600, tmp_path)
    with zipfile.ZipFile(it) as z:
        assert "it-IT" in z.read("OEBPS/content.opf").decode()
    with zipfile.ZipFile(da) as z:
        assert "da-DK" in z.read("OEBPS/content.opf").decode()


def test_dialogue_fixtures_have_distinct_styles(tmp_path):
    it = m.make_dialogue_epub("it", 0.7, tmp_path)
    da = m.make_dialogue_epub("da", 0.7, tmp_path)
    with zipfile.ZipFile(it) as z:
        body = z.read("OEBPS/chapter1.xhtml").decode()
        assert "disse la donna" in body  # unmarked dialogue
    with zipfile.ZipFile(da) as z:
        body = z.read("OEBPS/chapter1.xhtml").decode()
        assert "„" in body  # dash/quote-marked dialogue


def test_edge_cases_fixture_contains_empty_paragraphs(tmp_path):
    path = m.make_edge_cases_epub(tmp_path)
    with zipfile.ZipFile(path) as z:
        body = z.read("OEBPS/chapter1.xhtml").decode()
        assert "<p></p>" in body


def test_cli_list_smoke(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["make_fixture_epub.py", "--list"])
    m.main()
    out = capsys.readouterr().out
    assert "plain_it" in out and "edge_cases" in out
