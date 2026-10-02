"""gemini_readaloud resume/quota tests (issue #17).

The E2E slice failed because every run regenerated the prepared text
(non-deterministic LLM output), invalidating the segment cache: each
daily run re-spent the whole chapter's Gemini quota against a hard
~10 requests/day free tier. These tests pin the two fixes — prepared-
text reuse and the daily-quota fast-abort — with mocked engines only;
no network, no API key.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import sys
import types
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import gemini_readaloud as gr  # noqa: E402


def _args(tmp_path, reprepare=False, slice_=1200, epub="book.epub"):
    return types.SimpleNamespace(
        epub=epub, slice=slice_, max_chars=4000,
        model_llm="mistral-large-latest", reprepare=reprepare,
    )


def _fingerprint(args, idx, text):
    """Mirror of gemini_readaloud.prepared_chapter_text's fingerprint."""
    return "|".join(str(x) for x in
                    (Path(args.epub).resolve(), idx, args.slice,
                     args.max_chars, args.model_llm,
                     hashlib.sha1(text.encode()).hexdigest()))


class _RaisingClient:
    """LLM client that fails the test if preparation is re-run."""

    def chat(self):  # pragma: no cover - never called
        raise AssertionError("llm_prepare must not be called")


class _FakeLLMClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(complete=self._complete)

    @staticmethod
    def _complete(model, messages):
        message = types.SimpleNamespace(content="FAKE [f]: preparato")
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])


def _speech_wav(seconds=1.0, rate=24000) -> bytes:
    """A WAV whose middle third is 'speech' (passes clean_pcm)."""
    n = int(rate * seconds)
    samples = bytearray()
    for i in range(n):
        amp = 8000 if n // 3 < i < 2 * n // 3 else 0
        v = amp if (i // 2) % 2 == 0 else -amp
        samples += int(v).to_bytes(2, "little", signed=True)
    out = io.BytesIO()
    with wave.open(out, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(samples))
    return out.getvalue()


class _FakeEngine:
    def __init__(self, responses):
        self.model = "gemini-2.5-flash-preview-tts"
        self._responses = list(responses)
        self.calls = 0

    async def synthesize(self, text, voice):
        self.calls += 1
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return types.SimpleNamespace(audio=r)


def _quota_error(metric="GenerateRequestsPerDayPerProjectPerModel"):
    from app.engines.base import EngineError
    return EngineError(
        "Gemini API error 429: {'error': {'code': 429, 'message': "
        "\"You exceeded your current quota ... \\n* Quota exceeded for "
        f"quota metric '{metric}' and limit '{metric}-freetier' ...\"}}")


# ── prepared-text reuse ───────────────────────────────────────────────────


def test_prepared_text_reused_when_fingerprint_matches(tmp_path, capsys):
    ch_dir = tmp_path / "ch003"
    ch_dir.mkdir()
    (ch_dir / "prepared_text.txt").write_text("cached preparation")
    args = _args(tmp_path)
    (ch_dir / "prepared_meta.txt").write_text(_fingerprint(args, 3, "raw"))

    # A client that explodes if touched proves no LLM call is made.
    text = gr.prepared_chapter_text(_RaisingClient(), args, 3, ch_dir, "raw")
    assert text == "cached preparation"
    assert "reusing prepared text" in capsys.readouterr().out


def test_prepared_text_regenerated_on_fingerprint_mismatch(tmp_path):
    ch_dir = tmp_path / "ch003"
    ch_dir.mkdir()
    (ch_dir / "prepared_text.txt").write_text("stale preparation")
    (ch_dir / "prepared_meta.txt").write_text("old|3|999|4000|old-model")

    args = _args(tmp_path)
    text = gr.prepared_chapter_text(_FakeLLMClient(), args, 3, ch_dir, "raw")
    assert text == "FAKE [f]: preparato"
    assert (ch_dir / "prepared_text.txt").read_text() == text
    assert (ch_dir / "prepared_meta.txt").read_text() == _fingerprint(args, 3, "raw")


def test_reprepare_flag_forces_regeneration(tmp_path):
    ch_dir = tmp_path / "ch003"
    ch_dir.mkdir()
    (ch_dir / "prepared_text.txt").write_text("cached preparation")
    args = _args(tmp_path)
    (ch_dir / "prepared_meta.txt").write_text(_fingerprint(args, 3, "raw"))

    text = gr.prepared_chapter_text(
        _FakeLLMClient(), _args(tmp_path, reprepare=True), 3, ch_dir, "raw")
    assert text == "FAKE [f]: preparato"


def test_prepared_text_reused_across_path_spellings(tmp_path):
    # Review finding 1: the same epub spelled differently on resume
    # (resolved path, a symlink, redundant components) must still hit
    # the cache — a fingerprint miss would re-spend the whole chapter's
    # Gemini quota (the exact #17 failure mode).
    ch_dir = tmp_path / "ch003"
    ch_dir.mkdir()
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")
    args = _args(tmp_path, epub=str(epub))
    gr.prepared_chapter_text(_FakeLLMClient(), args, 3, ch_dir, "raw")

    link = tmp_path / "link.epub"
    link.symlink_to(epub)
    for spelling in (str(epub.resolve()), str(link),
                     str(tmp_path / "sub" / ".." / "book.epub")):
        resume_args = _args(tmp_path, epub=spelling)
        text = gr.prepared_chapter_text(
            _RaisingClient(), resume_args, 3, ch_dir, "raw")
        assert text == "FAKE [f]: preparato"


def test_prepared_text_regenerated_when_source_content_changes(tmp_path):
    # Review finding 2: a replaced/re-downloaded epub at the same path
    # must not silently reuse the old book's prepared text — the
    # fingerprint binds to the sliced source content.
    ch_dir = tmp_path / "ch003"
    ch_dir.mkdir()
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub v1")
    args = _args(tmp_path, epub=str(epub))
    gr.prepared_chapter_text(_FakeLLMClient(), args, 3, ch_dir,
                             "OLD EDITION: the king died at dawn.")

    text = gr.prepared_chapter_text(
        _FakeLLMClient(), args, 3, ch_dir,
        "NEW EDITION, completely different content: the queen sailed east.")
    assert text == "FAKE [f]: preparato"  # regenerated, not the old text
    assert (ch_dir / "prepared_meta.txt").read_text() == _fingerprint(
        args, 3, "NEW EDITION, completely different content: the queen sailed east.")


# ── 429 handling ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_quota_429_aborts_without_retry(tmp_path):
    # A hard daily quota never recovers within a run: no backoff, no
    # re-spending, a clear resumable error instead of a traceback after
    # ten minutes of waiting (issue #17).
    eng = _FakeEngine([_quota_error(), _quota_error()])
    with pytest.raises(RuntimeError, match="daily quota"):
        await gr.synth_line(eng, "Kore", "test line", tmp_path, pace=0)
    assert eng.calls == 1  # aborted at once, no retries


@pytest.mark.asyncio
async def test_per_minute_429_keeps_backoff_retry(tmp_path, monkeypatch):
    # Per-minute 429s are transient: the existing backoff retry stays.
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    eng = _FakeEngine(
        [_quota_error("GenerateRequestsPerMinutePerProjectPerModel"),
         _quota_error("GenerateRequestsPerMinutePerProjectPerModel"),
         _speech_wav()])
    seg = await gr.synth_line(eng, "Kore", "test line", tmp_path, pace=0)
    assert eng.calls == 3
    assert sleeps == [60, 120, 0]  # two backoff waits, then the pace sleep
    assert seg.exists() and seg.stat().st_size > 1000


@pytest.mark.asyncio
async def test_cached_segment_skips_engine(tmp_path):
    key = hashlib.sha1(
        b"gemini-2.5-flash-preview-tts|Kore|test line").hexdigest()[:16]
    seg = tmp_path / f"Kore-{key}.wav"
    seg.write_bytes(b"\0" * 2000)
    eng = _FakeEngine([_quota_error()])
    out = await gr.synth_line(eng, "Kore", "test line", tmp_path, pace=0)
    assert out == seg
    assert eng.calls == 0
