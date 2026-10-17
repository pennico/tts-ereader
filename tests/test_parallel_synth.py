"""Tests for parallel edge-tts synthesis (edge_reader.synthesize and
epub_mo.synth_word_timed) with a mocked edge_tts module.

No network: a fake Communicate records concurrency, writes dummy bytes,
and (for epub_mo) yields fake WordBoundary events.
"""

import asyncio
import unittest
from pathlib import Path

import edge_reader
import epub_mo

TMP = Path("/tmp/tts_ereader_test_parallel")


def make_segments(n):
    """n narration segments with distinct texts."""
    return [(None, None, f"line number {i} of the test", "voice-x", "Test")
            for i in range(n)]


class Tracker:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.attempts = {}  # text -> number of attempts so far
        self.fail_first = set()  # texts whose first attempt raises


class FakeCommunicate:
    tracker = None

    def __init__(self, text, voice, rate=None, boundary=None):
        self.text = text
        self.voice = voice
        self.boundary = boundary

    async def save(self, path):
        t = FakeCommunicate.tracker
        t.attempts[self.text] = t.attempts.get(self.text, 0) + 1
        if self.text in t.fail_first and t.attempts[self.text] == 1:
            raise RuntimeError("simulated transient failure")
        t.active += 1
        t.max_active = max(t.max_active, t.active)
        await asyncio.sleep(0.01)
        Path(path).write_bytes(b"fake audio")
        t.active -= 1

    async def stream(self):
        t = FakeCommunicate.tracker
        t.attempts[self.text] = t.attempts.get(self.text, 0) + 1
        if self.text in t.fail_first and t.attempts[self.text] == 1:
            raise RuntimeError("simulated transient failure")
        t.active += 1
        t.max_active = max(t.max_active, t.active)
        await asyncio.sleep(0.01)
        t.active -= 1
        for word in self.text.split():
            yield {"type": "WordBoundary", "offset": 0, "duration": int(1e7),
                   "text": word}
        yield {"type": "audio", "data": b"fake audio"}


class FakeEdgeTts:
    Communicate = FakeCommunicate


class ParallelSynthTest(unittest.TestCase):
    def setUp(self):
        self._real = edge_reader.edge_tts, epub_mo.edge_tts
        self.tracker = Tracker()
        FakeCommunicate.tracker = self.tracker
        edge_reader.edge_tts = FakeEdgeTts
        epub_mo.edge_tts = FakeEdgeTts
        TMP.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        edge_reader.edge_tts, epub_mo.edge_tts = self._real

    def test_order_preserved(self):
        segments = make_segments(10)
        files = asyncio.run(edge_reader.synthesize(segments, TMP, "-8%", workers=4))
        self.assertEqual(len(files), 10)
        for i, (path, voice_name) in enumerate(files):
            self.assertEqual(path.name, f"seg_{i:03d}.mp3")
            self.assertEqual(voice_name, segments[i][4])

    def test_concurrency_capped(self):
        segments = make_segments(12)
        asyncio.run(edge_reader.synthesize(segments, TMP, "-8%", workers=3))
        self.assertLessEqual(self.tracker.max_active, 3)
        # parallelism actually happens with more segments than workers
        self.assertGreater(self.tracker.max_active, 1)

    def test_workers_one_is_sequential(self):
        segments = make_segments(6)
        asyncio.run(edge_reader.synthesize(segments, TMP, "-8%", workers=1))
        self.assertEqual(self.tracker.max_active, 1)

    def test_transient_failure_retried(self):
        segments = make_segments(4)
        self.tracker.fail_first = {segments[2][2]}
        files = asyncio.run(edge_reader.synthesize(segments, TMP, "-8%", workers=2))
        self.assertEqual(len(files), 4)
        self.assertEqual(self.tracker.attempts[segments[2][2]], 2)
        self.assertTrue(Path(files[2][0]).exists())

    def test_word_timed_order_and_events(self):
        segments = make_segments(5)
        files, events = asyncio.run(
            epub_mo.synth_word_timed(segments, TMP, "-8%", workers=2))
        self.assertEqual(len(files), 5)
        for i, (path, voice_name) in enumerate(files):
            self.assertEqual(path.name, f"seg_{i:03d}.mp3")
            self.assertEqual(voice_name, segments[i][4])
            # events belong to their own segment: same words, same order
            self.assertEqual([e[2] for e in events[i]],
                             segments[i][2].split())
            self.assertTrue(path.exists())

    def test_word_timed_concurrency_capped(self):
        segments = make_segments(9)
        asyncio.run(epub_mo.synth_word_timed(segments, TMP, "-8%", workers=2))
        self.assertLessEqual(self.tracker.max_active, 2)
        self.assertGreater(self.tracker.max_active, 1)

    def test_word_timed_transient_failure_retried(self):
        segments = make_segments(3)
        self.tracker.fail_first = {segments[0][2]}
        files, events = asyncio.run(
            epub_mo.synth_word_timed(segments, TMP, "-8%", workers=2))
        self.assertEqual(len(files), 3)
        self.assertEqual(self.tracker.attempts[segments[0][2]], 2)
        self.assertEqual([e[2] for e in events[0]], segments[0][2].split())


if __name__ == "__main__":
    unittest.main()
