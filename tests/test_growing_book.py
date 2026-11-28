"""Growing-book tests (owner decision, 2026-10-09).

The whole book lives in ONE output EPUB that grows day by day:
--growing rebuilds the output from every completed chapter's persisted
artifacts in the work dir, so completed chapters are never
re-synthesized, and --package-only rebuilds it with no synthesis at
all. These tests pin the pieces with synthetic artifacts only — no
network, no API key, no Gemini spend.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))

import gemini_readaloud as gr  # noqa: E402


def _fixture_epub(tmp_path):
    from make_fixture_epub import make_all_fixtures
    epubs_dir = tmp_path / "epubs"
    make_all_fixtures(epubs_dir)
    return sorted(epubs_dir.glob("*.epub"))[0]


def _seed_chapter(work_dir, ch_id, idx, duration=60.0):
    """Persist a minimal completed-chapter artifact set."""
    ch_dir = work_dir / ch_id
    ch_dir.mkdir(parents=True)
    (ch_dir / f"{ch_id}.xhtml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        f"<head><title>Capitolo {idx}</title></head>"
        '<body><p id="p1">testo</p></body></html>')
    (ch_dir / f"{ch_id}.smil").write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<smil xmlns="http://www.w3.org/ns/SMIL"><body>'
        f'<par id="par1"><text src="{ch_id}.xhtml#p1"/>'
        f'<audio src="audio/{ch_id}.mp3" clipBegin="0s" '
        f'clipEnd="{duration}s"/></par>'
        "</body></smil>")
    (ch_dir / "audio.mp3").write_bytes(b"ID3 dummy mp3")
    (ch_dir / "chapter.json").write_text(
        json.dumps({"idx": idx, "duration": duration}))


def _run_cli(epub, *extra):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "gemini_readaloud.py"),
         "--epub", str(epub), *extra],
        capture_output=True, text=True, timeout=60)


def test_completed_chapters_requires_full_artifacts(tmp_path):
    work = tmp_path / "work"
    _seed_chapter(work, "ch003", 3)
    _seed_chapter(work, "ch004", 4)
    (work / "ch004" / "audio.mp3").unlink()  # interrupted chapter
    _seed_chapter(work, "ch005", 5)
    (work / "ch005" / "chapter.json").unlink()
    (work / "ch006").mkdir()  # prepared but never synthesized
    done = gr.completed_chapters(work)
    assert [c["ch_id"] for c in done] == ["ch003"]
    assert done[0]["idx"] == 3
    assert done[0]["duration"] == 60.0


def test_package_only_rebuilds_the_growing_epub(tmp_path):
    # Day 1: chapters 3 and 4 completed (spine 3,4 = book chapters
    # 1,2). --package-only rebuilds the output from the artifacts with
    # no synthesis and no API keys.
    epub = _fixture_epub(tmp_path)
    work = tmp_path / "work"
    _seed_chapter(work, "ch003", 3)
    _seed_chapter(work, "ch004", 4)
    out = tmp_path / "book.epub"
    r = _run_cli(epub, "--package-only", "--growing",
                 "--work-dir", str(work), "--output", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "ch003.xhtml" in names and "ch004.xhtml" in names
        assert "audio/ch003.mp3" in names and "audio/ch004.mp3" in names
        nav = z.read("nav.xhtml").decode()
        assert "Capitolo 1" in nav and "Capitolo 2" in nav
        ch3 = z.read("ch003.xhtml")

    # Day 2: chapter 5 completed. The rebuild keeps the old chapters
    # byte-identical and appends the new one — nothing re-synthesized,
    # one growing file.
    _seed_chapter(work, "ch005", 5)
    r = _run_cli(epub, "--package-only", "--growing",
                 "--work-dir", str(work), "--output", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "ch005.xhtml" in names
        assert z.read("ch003.xhtml") == ch3  # old read untouched
        nav = z.read("nav.xhtml").decode()
        assert "Capitolo 3" in nav


def test_package_only_needs_growing(tmp_path):
    epub = _fixture_epub(tmp_path)
    r = _run_cli(epub, "--package-only",
                 "--work-dir", str(tmp_path / "w"),
                 "--output", str(tmp_path / "o.epub"))
    assert r.returncode == 1
    assert "--growing" in r.stdout


def test_package_only_without_completed_chapters(tmp_path):
    epub = _fixture_epub(tmp_path)
    r = _run_cli(epub, "--package-only", "--growing",
                 "--work-dir", str(tmp_path / "empty"),
                 "--output", str(tmp_path / "o.epub"))
    assert r.returncode == 1
    assert "no completed chapters" in r.stdout
