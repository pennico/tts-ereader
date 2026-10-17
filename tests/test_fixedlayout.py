"""Tests for epub_fixedlayout: pagination, packaging, and validation.

No network, no LLM, no real audio: chapters are built from synthetic
segments with hand-computed offsets and dummy audio bytes (validate only
checks structure, it never decodes audio).
"""

import unittest
import zipfile
from pathlib import Path

from edge_reader import assign_voices, parse_lines
from epub_fixedlayout import (
    DEMO_TEXT,
    build_book,
    page_smil,
    paginate,
    parse_viewport,
    validate_fixed,
)

TMP = Path("/tmp/tts_ereader_test_fixed")


def make_segments(text):
    return assign_voices(parse_lines(text))


def fake_offsets(n, seg_len=2.0, gap=0.25):
    """Monotonic offsets like concatenate() would produce."""
    offsets, t = [], 0.0
    for _ in range(n):
        offsets.append((t + gap, t + gap + seg_len))
        t += gap + seg_len + gap
    return offsets


def make_chapter(ch_id, text, chars_per_page=100):
    segments = make_segments(text)
    offsets = fake_offsets(len(segments))
    return {
        "ch_id": ch_id,
        "title": f"Capitolo {ch_id}",
        "segments": segments,
        "offsets": offsets,
        "audio": b"fake mp3 bytes",
        "duration": offsets[-1][1] if offsets else 0.0,
        "chars_per_page": chars_per_page,
    }


class TestPaginate(unittest.TestCase):
    def test_single_page_under_budget(self):
        segs = [(None, None, "a" * 10), (None, None, "b" * 10)]
        pages = paginate(segs, 100)
        self.assertEqual(len(pages), 1)
        self.assertEqual([i for i, _s in pages[0]], [0, 1])

    def test_splits_at_budget(self):
        segs = [(None, None, "x" * 60), (None, None, "y" * 60), (None, None, "z" * 60)]
        pages = paginate(segs, 130)
        self.assertEqual(len(pages), 2)
        self.assertEqual([i for i, _s in pages[0]], [0, 1])
        self.assertEqual([i for i, _s in pages[1]], [2])

    def test_oversized_segment_gets_own_page(self):
        segs = [(None, None, "x" * 500), (None, None, "y" * 10)]
        pages = paginate(segs, 100)
        self.assertEqual(len(pages), 2)
        self.assertEqual([i for i, _s in pages[0]], [0])
        self.assertEqual([i for i, _s in pages[1]], [1])

    def test_order_preserved(self):
        segs = [(None, None, f"line {i} " + "w" * 40) for i in range(10)]
        pages = paginate(segs, 100)
        flat = [i for page in pages for i, _s in page]
        self.assertEqual(flat, list(range(10)))

    def test_empty(self):
        self.assertEqual(paginate([], 100), [])


class TestViewport(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_viewport("768x1024"), (768, 1024))
        self.assertEqual(parse_viewport("1024X768"), (1024, 768))

    def test_invalid(self):
        with self.assertRaises(Exception):
            parse_viewport("1024")
        with self.assertRaises(Exception):
            parse_viewport("axb")
        with self.assertRaises(Exception):
            parse_viewport("10x10")


class TestBuildAndValidate(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(parents=True, exist_ok=True)
        self.out = TMP / "test.epub"
        self.chapters = [
            make_chapter("ch000", DEMO_TEXT, chars_per_page=150),
            make_chapter("ch001", DEMO_TEXT, chars_per_page=1000),
        ]

    def test_build_and_validate_ok(self):
        n_ch, total = build_book(self.chapters, "Test (lettura)", "Autore",
                                 768, 1024, self.out)
        self.assertEqual(n_ch, 2)
        self.assertGreater(total, 0)
        errors = validate_fixed(self.out, 768, 1024)
        self.assertEqual(errors, [])

    def test_pages_and_anchors(self):
        build_book(self.chapters, "Test", "Autore", 768, 1024, self.out)
        with zipfile.ZipFile(self.out) as z:
            names = z.namelist()
            # chapter 0 budget 150 -> several pages; chapter 1 -> one page
            c0_pages = [n for n in names
                        if n.startswith("ch000-p") and n.endswith(".xhtml")]
            c1_pages = [n for n in names
                        if n.startswith("ch001-p") and n.endswith(".xhtml")]
            self.assertGreater(len(c0_pages), 1)
            self.assertEqual(len(c1_pages), 1)
            # every SMIL anchor exists in its page document
            for smil_name in [n for n in names if n.endswith(".smil")]:
                smil = z.read(smil_name).decode("utf-8")
                doc_name = smil_name.replace(".smil", ".xhtml")
                doc = z.read(doc_name).decode("utf-8")
                for anchor in __import__("re").findall(r"#(mo-\d+)", smil):
                    self.assertIn(f'id="{anchor}"', doc)

    def test_clips_monotonic_per_page(self):
        build_book(self.chapters, "Test", "Autore", 768, 1024, self.out)
        with zipfile.ZipFile(self.out) as z:
            for smil_name in [n for n in z.namelist() if n.endswith(".smil")]:
                smil = z.read(smil_name).decode("utf-8")
                clips = __import__("re").findall(
                    r'clipBegin="([\d.]+)s" clipEnd="([\d.]+)s"', smil)
                prev_end = 0.0
                for b, e in clips:
                    b, e = float(b), float(e)
                    self.assertGreater(e, b)
                    self.assertGreaterEqual(b, prev_end - 0.001)
                    prev_end = e

    def test_validation_catches_missing_viewport_meta(self):
        build_book(self.chapters, "Test", "Autore", 768, 1024, self.out)
        # rewrite the zip with a broken page (viewport meta removed)
        broken = TMP / "broken.epub"
        with zipfile.ZipFile(self.out) as zin, \
                zipfile.ZipFile(broken, "w") as zout:
            for name in zin.namelist():
                data = zin.read(name)
                if name.endswith(".xhtml") and name != "nav.xhtml":
                    data = data.replace(
                        b'<meta name="viewport" content="width=768, height=1024"/>', b"")
                if name == "mimetype":
                    zout.writestr(name, data, zipfile.ZIP_STORED)
                else:
                    zout.writestr(name, data, zipfile.ZIP_DEFLATED)
        errors = validate_fixed(broken, 768, 1024)
        self.assertTrue(any("viewport" in e for e in errors))

    def test_validation_catches_wrong_layout(self):
        build_book(self.chapters, "Test", "Autore", 768, 1024, self.out)
        broken = TMP / "broken2.epub"
        with zipfile.ZipFile(self.out) as zin, \
                zipfile.ZipFile(broken, "w") as zout:
            for name in zin.namelist():
                data = zin.read(name)
                if name == "content.opf":
                    data = data.replace(b"pre-paginated", b"reflowable")
                if name == "mimetype":
                    zout.writestr(name, data, zipfile.ZIP_STORED)
                else:
                    zout.writestr(name, data, zipfile.ZIP_DEFLATED)
        errors = validate_fixed(broken, 768, 1024)
        self.assertTrue(any("rendition:layout" in e for e in errors))

    def test_page_smil_references_chapter_audio(self):
        smil = page_smil("ch000", "ch000-p000",
                         [(0, (None, None, "a")), (1, (None, None, "b"))],
                         [(0.25, 2.25), (2.5, 4.5)])
        self.assertIn('src="audio/ch000.mp3"', smil)
        self.assertIn('clipBegin="0.250s"', smil)
        self.assertIn('clipEnd="4.500s"', smil)


if __name__ == "__main__":
    unittest.main()
