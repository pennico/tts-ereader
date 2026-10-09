"""Request-efficient synthesis tests (issue #25).

The per-day quota that blocks chapter runs is the REQUEST count (100/day
on gemini-3.8-flash-tts), not tokens: one request per prepared line spends
the whole bucket on a single chapter. --lines-per-request N batches lines
into one multi-speaker request; these tests pin the pieces that must not
regress, with mocked engines only — no network, no API key, no 3.8 spend.

- silence-gap splitting of a batch take back into per-line segments
  (the SMIL offsets stay per-line)
- per-batch cache keys and resume; re-use of per-line-cached batches
- per-line fallbacks: unalignable audio, recitation filter, daily-quota
  abort (exit 75)
- request/token instrumentation and the quota ledger
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
sys.path.insert(0, str(REPO_ROOT / "backend"))

import gemini_readaloud as gr  # noqa: E402
from shared import quota_ledger  # noqa: E402

RATE = 24000


def _silence(seconds, rate=RATE):
    return b"\x00" * int(rate * seconds) * 2


def _burst(seconds, rate=RATE, amp=8000):
    """Loud square-wave 'speech' PCM (16-bit mono little-endian)."""
    n = int(rate * seconds)
    return b"".join(
        int(amp if (i // 2) % 2 == 0 else -amp).to_bytes(2, "little", signed=True)
        for i in range(n)
    )


def _speech_pcm(seconds, rate=RATE):
    """A single line's take: brief lead/tail silence around the speech,
    like a real Gemini response (clean_pcm trims a take that is loud
    right up to the end as an end-of-response noise burst)."""
    return _silence(0.05, rate) + _burst(seconds, rate) + _silence(0.3, rate)


def _batch_pcm(line_durs, gap_s=0.4, rate=RATE):
    """Speech bursts separated by silence gaps — a fake batch take."""
    pcm = _silence(0.05, rate)
    for i, dur in enumerate(line_durs):
        pcm += _burst(dur, rate)
        if i < len(line_durs) - 1:
            pcm += _silence(gap_s, rate)
    return pcm + _silence(0.3, rate)


def _wav(pcm, rate=RATE, width=2):
    out = io.BytesIO()
    with wave.open(out, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


class _FakeEngine:
    """Engine double: counts requests, returns queued responses."""

    def __init__(self, responses, model="gemini-3.8-flash-tts"):
        self.model = model
        self._responses = list(responses)
        self.calls = []
        self.request_count = 0
        self.token_count = 0

    async def synthesize(self, text, voice):
        self.calls.append(("line", voice, text))
        self.request_count += 1
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return types.SimpleNamespace(audio=r, usage=None)

    async def synthesize_multi(self, turns, style=None):
        self.calls.append(("batch", tuple(turns), style))
        self.request_count += 1
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return types.SimpleNamespace(audio=r, usage=None)


def _quota_error(metric="generate_requests_per_model_per_day"):
    from app.engines.base import EngineError
    return EngineError(
        "Gemini API error 429: {'error': {'code': 429, 'message': "
        f'"Quota exceeded for metric {metric}, limit 100"}}')


def _filter_error():
    from app.engines.base import EngineError
    return EngineError(
        "unexpected Gemini response shape after 3 attempts: 'content' "
        '[response: {"keys": ["candidates", "usageMetadata"], '
        '"candidate_count": 1, "finish_reasons": ["OTHER"], '
        '"candidate_keys": [["finishMessage", "finishReason", "index"]], '
        '"prompt_feedback": null}]')


# ── silence-gap splitting ──────────────────────────────────────────────────


def test_split_batch_pcm_splits_at_gaps():
    # Three lines of 1.0/2.0/1.0 s separated by 0.4 s gaps: the split
    # must return one chunk per line, cut inside the gaps.
    pcm = _batch_pcm([1.0, 2.0, 1.0])
    chunks = gr.split_batch_pcm(pcm, 2, RATE, [50, 100, 50])
    assert chunks is not None and len(chunks) == 3
    durs = [len(c) / (RATE * 2) for c in chunks]
    # each chunk = its line + half of each surrounding gap (+ edge silence)
    assert durs[0] == pytest.approx(1.25, abs=0.05)
    assert durs[1] == pytest.approx(2.4, abs=0.05)
    assert durs[2] == pytest.approx(1.5, abs=0.05)


def test_split_batch_pcm_needs_a_gap_per_boundary():
    # Two lines but no silence between them: no confident split exists.
    pcm = _burst(1.0) + _burst(1.0)
    assert gr.split_batch_pcm(pcm, 2, RATE, [50, 50]) is None


def test_split_batch_pcm_rejects_far_boundaries():
    # Durations wildly out of proportion with the text lengths: the gap
    # closest to the expected position is still too far — refuse to
    # split rather than emit misaligned SMIL offsets.
    pcm = _batch_pcm([0.3, 5.0, 0.3])
    assert gr.split_batch_pcm(pcm, 2, RATE, [50, 10, 50]) is None


def test_split_batch_pcm_rejects_tiny_segments(monkeypatch):
    # Defense in depth: even if boundaries pass the tolerance, a split
    # that leaves a "line" on near-zero audio is refused.
    monkeypatch.setattr(gr, "BATCH_MIN_SEGMENT_S", 10.0)
    pcm = _batch_pcm([1.0, 1.0, 1.0])
    assert gr.split_batch_pcm(pcm, 2, RATE, [50, 50, 50]) is None


def test_silence_gap_min_duration():
    # Pauses shorter than BATCH_SPLIT_MIN_GAP_MS (sentence pauses inside
    # a line) are not boundary candidates; real inter-line pauses are.
    short = _burst(0.5) + _silence(0.15) + _burst(0.5)
    assert gr._silence_gaps(short, RATE) == []
    long = _burst(0.5) + _silence(0.25) + _burst(0.5)
    assert len(gr._silence_gaps(long, RATE)) == 1


def test_split_batch_pcm_ignores_short_sentence_pauses():
    # Line 1 contains a 150 ms sentence pause; the boundary must be the
    # real 400 ms inter-line gap, not the sentence pause.
    pcm = (_burst(0.3) + _silence(0.15) + _burst(0.3)
           + _silence(0.4) + _burst(1.5))
    chunks = gr.split_batch_pcm(pcm, 2, RATE, [30, 70])
    assert chunks is not None and len(chunks) == 2
    # chunk 0 covers both bursts of line 1 (0.75 s) plus half the gap
    assert len(chunks[0]) / (RATE * 2) == pytest.approx(0.95, abs=0.05)


def test_assign_boundaries_picks_optimal_monotone_assignment():
    # Boundary j+1 always after boundary j; among monotone assignments
    # the total distance to the expected positions is minimized.
    mids = [100, 130, 900]
    expected = [120, 880]
    chosen = gr._assign_boundaries(mids, expected)
    assert chosen is not None
    picked = [mids[i] for i in chosen]
    assert picked == sorted(picked)
    # (130, 900) beats (100, 900): total distance 30 vs 40
    assert picked == [130, 900]


def test_assign_boundaries_needs_enough_gaps():
    assert gr._assign_boundaries([10, 20], [1, 2, 3]) is None


# ── synth_batch ────────────────────────────────────────────────────────────


def _batch(turns):
    return list(turns)


BATCH3 = [("Rami", "prima riga di prova"), ("Kore", "seconda"),
          ("Rami", "terza ed ultima riga")]


@pytest.mark.asyncio
async def test_synth_batch_single_line_uses_per_line_path(tmp_path):
    # A 1-line batch is just a line: per-line request, per-line cache key.
    eng = _FakeEngine([_wav(_speech_pcm(1.0))])
    paths = await gr.synth_batch(eng, [("Kore", "una riga")], tmp_path, pace=0)
    assert len(paths) == 1
    assert eng.calls[0][0] == "line"
    key = hashlib.sha1(b"gemini-3.8-flash-tts|Kore|una riga").hexdigest()[:16]
    assert paths[0] == tmp_path / f"Kore-{key}.wav"


@pytest.mark.asyncio
async def test_synth_batch_one_request_and_split_files(tmp_path):
    # The point of the feature: three lines, ONE request, three cached
    # per-line segments with per-batch cache keys.
    durs = [1.0, 0.8, 1.2]
    eng = _FakeEngine([_wav(_batch_pcm(durs))])
    paths = await gr.synth_batch(eng, _batch(BATCH3), tmp_path, pace=0)
    assert len(eng.calls) == 1
    assert eng.calls[0][0] == "batch"
    assert eng.calls[0][1] == tuple(BATCH3)
    assert eng.calls[0][2] == gr.BATCH_STYLE  # 2 voices: labeled conversation
    assert len(paths) == 3
    for p in paths:
        assert p.exists() and p.stat().st_size > 1000
        assert p.name.startswith("batch-")
    # resume: the split files are the cache — no second request
    eng2 = _FakeEngine([])
    paths2 = await gr.synth_batch(eng2, _batch(BATCH3), tmp_path, pace=0)
    assert paths2 == paths
    assert eng2.calls == []


@pytest.mark.asyncio
async def test_synth_batch_one_voice_group_sent_bare(tmp_path):
    # A 1-voice batch is a plain single-voice request (the API's
    # multi-speaker config requires exactly 2 speakers): no labels,
    # no conversation instruction — the box method, multi-paragraph.
    batch = [("Rami", "prima riga"), ("Rami", "seconda riga"),
             ("Rami", "terza riga")]
    eng = _FakeEngine([_wav(_batch_pcm([1.0, 1.0, 1.0]))])
    paths = await gr.synth_batch(eng, _batch(batch), tmp_path, pace=0)
    assert len(eng.calls) == 1
    assert eng.calls[0][2] == ""  # bare text, no BATCH_STYLE
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_synth_batch_splits_three_voice_batches(tmp_path):
    # The API takes at most 2 voices per request: a batch spanning 3
    # voices is split into voice-compatible sub-batches, one request
    # each, and the returned paths stay in reading order.
    batch = [("Rami", "riga uno"), ("Kore", "riga due"),
             ("Leda", "riga tre"), ("Rami", "riga quattro")]
    eng = _FakeEngine([
        _wav(_batch_pcm([1.0, 1.0])),    # [Rami, Kore]
        _wav(_batch_pcm([1.0, 1.0])),    # [Leda, Rami]
    ])
    paths = await gr.synth_batch(eng, _batch(batch), tmp_path, pace=0)
    assert len(eng.calls) == 2
    assert eng.calls[0][1] == (("Rami", "riga uno"), ("Kore", "riga due"))
    assert eng.calls[1][1] == (("Leda", "riga tre"), ("Rami", "riga quattro"))
    assert len(paths) == 4
    assert all(p.exists() and p.stat().st_size > 1000 for p in paths)


@pytest.mark.asyncio
async def test_synth_batch_reuses_per_line_cache(tmp_path):
    # A batch whose every line was already synthesized per-line in an
    # earlier run must not re-spend a request (the ch1 case: 115/117
    # lines already paid for when the scheduled run switches to batching).
    for voice, text in BATCH3:
        key = hashlib.sha1(
            f"gemini-3.8-flash-tts|{voice}|{text}".encode()).hexdigest()[:16]
        (tmp_path / f"{voice}-{key}.wav").write_bytes(_wav(_speech_pcm(0.5)))
    eng = _FakeEngine([])  # any call fails the test via pop(0) on empty list
    paths = await gr.synth_batch(eng, _batch(BATCH3), tmp_path, pace=0)
    assert eng.calls == []
    assert all(p.exists() for p in paths)


@pytest.mark.asyncio
async def test_synth_batch_unalignable_audio_falls_back_per_line(tmp_path):
    # Batch audio with no usable gaps: fall back to per-line synthesis
    # (a few extra requests beat misaligned highlighting), and the
    # per-line fallback keeps its own caching.
    eng = _FakeEngine([
        _wav(_speech_pcm(3.0)),  # one solid take, no gaps
        _wav(_speech_pcm(1.0)), _wav(_speech_pcm(1.0)), _wav(_speech_pcm(1.0)),
    ])
    paths = await gr.synth_batch(eng, _batch(BATCH3), tmp_path, pace=0)
    assert [c[0] for c in eng.calls] == ["batch", "line", "line", "line"]
    assert len(paths) == 3
    # the per-line segments are cached: a re-run spends nothing
    eng2 = _FakeEngine([])
    await gr.synth_batch(eng2, _batch(BATCH3), tmp_path, pace=0)
    assert eng2.calls == []


@pytest.mark.asyncio
async def test_synth_batch_recitation_filter_falls_back_per_line(tmp_path):
    # The recitation filter can block a whole batch: fall back to lines,
    # which keeps the sentence-splitting fallback inside synth_line.
    text = "Una frase piuttosto lunga. E un'altra frase ancora."
    batch = [("Rami", text), ("Kore", text)]
    eng = _FakeEngine([
        _filter_error(),
        _filter_error(), _wav(_speech_pcm(1.0)), _wav(_speech_pcm(1.0)),
        _filter_error(), _wav(_speech_pcm(1.0)), _wav(_speech_pcm(1.0)),
    ])
    paths = await gr.synth_batch(eng, batch, tmp_path, pace=0)
    assert len(paths) == 2
    # each blocked line was split into its two sentences and stitched
    assert [c[0] for c in eng.calls].count("line") == 6
    for p in paths:
        with wave.open(str(p)) as w:
            assert w.getnframes() > 0


@pytest.mark.asyncio
async def test_synth_batch_daily_quota_aborts(tmp_path):
    # Exit-75 behavior is kept: a hard daily-quota 429 on a batch
    # aborts at once, resumable via the cache.
    eng = _FakeEngine([_quota_error(), _quota_error()])
    with pytest.raises(gr.QuotaExhausted, match="daily quota"):
        await gr.synth_batch(eng, _batch(BATCH3), tmp_path, pace=0)
    assert len(eng.calls) == 1


@pytest.mark.asyncio
async def test_synth_batch_per_minute_429_retries(tmp_path, monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    eng = _FakeEngine([
        _quota_error("GenerateRequestsPerMinutePerProjectPerModel"),
        _wav(_batch_pcm([1.0, 1.0, 1.0])),
    ])
    paths = await gr.synth_batch(eng, _batch(BATCH3), tmp_path, pace=0)
    assert len(paths) == 3
    assert sleeps == [60, 0]  # one backoff wait, then the pace sleep


# ── quota ledger + instrumentation ─────────────────────────────────────────


def test_ledger_add_entry_and_day_totals(tmp_path):
    ledger = tmp_path / "nested" / "quota_ledger.json"
    quota_ledger.add_entry(ledger, model="gemini-3.8-flash-tts",
                           run_id="r1", requests=12, tokens=8451,
                           date="2026-10-06")
    quota_ledger.add_entry(ledger, model="gemini-2.5-flash-preview-tts",
                           run_id="r2", requests=3, tokens=900,
                           date="2026-10-06")
    quota_ledger.add_entry(ledger, model="gemini-3.8-flash-tts",
                           run_id="r3", requests=5, tokens=100,
                           date="2026-10-05")
    totals = quota_ledger.day_totals(ledger, model="gemini-3.8-flash-tts",
                                     date="2026-10-06")
    assert totals == {"requests": 12, "tokens": 8451}
    all_models = quota_ledger.day_totals(ledger, date="2026-10-06")
    assert all_models == {"requests": 15, "tokens": 9351}


def test_ledger_survives_corrupt_file(tmp_path):
    ledger = tmp_path / "quota_ledger.json"
    ledger.write_text("{not json")
    quota_ledger.add_entry(ledger, model="m", run_id="r", requests=1, tokens=2)
    assert quota_ledger.day_totals(ledger, model="m")["requests"] == 1


def test_run_generation_records_usage_on_quota_abort(tmp_path, capsys):
    # A run that hits the daily quota still spent its earlier requests:
    # the ledger hook must run on the abort path too (issue #25).
    eng = _FakeEngine([])
    eng.request_count = 7
    eng.token_count = 1234
    ledger = tmp_path / "quota_ledger.json"
    recorded = []

    async def run():
        raise gr.QuotaExhausted("daily quota exhausted")

    def on_finish():
        recorded.append((eng.request_count, eng.token_count))
        quota_ledger.add_entry(ledger, model=eng.model, run_id="r",
                               requests=eng.request_count,
                               tokens=eng.token_count)

    with pytest.raises(SystemExit) as ei:
        gr.run_generation(run, on_finish=on_finish)
    assert ei.value.code == 75
    assert recorded == [(7, 1234)]
    assert quota_ledger.day_totals(ledger, model=eng.model)["requests"] == 7


def test_run_generation_records_usage_on_success():
    seen = []

    async def run():
        return None

    gr.run_generation(run, on_finish=lambda: seen.append(1))
    assert seen == [1]


def test_run_generation_records_usage_on_real_failure():
    # Real failures propagate, but the spent requests are still recorded.
    seen = []

    async def run():
        raise RuntimeError("broke")

    with pytest.raises(RuntimeError, match="broke"):
        gr.run_generation(run, on_finish=lambda: seen.append(1))
    assert seen == [1]


def test_run_generation_quota_abort_runs_on_quota_hook():
    # Issue #39: on the quota abort the caller packages the completed
    # chapters and shares the partial — on_quota runs before the exit,
    # and never on success or real failure.
    calls = []

    async def quota_run():
        raise gr.QuotaExhausted("daily quota exhausted")

    async def ok_run():
        return None

    async def broke_run():
        raise RuntimeError("broke")

    with pytest.raises(SystemExit) as ei:
        gr.run_generation(quota_run, on_quota=lambda: calls.append("quota"))
    assert ei.value.code == 75
    assert calls == ["quota"]
    gr.run_generation(ok_run, on_quota=lambda: calls.append("never"))
    assert calls == ["quota"]
    with pytest.raises(RuntimeError, match="broke"):
        gr.run_generation(broke_run, on_quota=lambda: calls.append("never"))
    assert calls == ["quota"]


# ── process_chapter, batched end to end ────────────────────────────────────


def _fixture_epub(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))
    from make_fixture_epub import make_all_fixtures
    epubs_dir = tmp_path / "epubs"
    make_all_fixtures(epubs_dir)
    epubs = sorted(epubs_dir.glob("*.epub"))
    return epubs[0]


def _chapter_args(tmp_path, epub, lines_per_request, idx=0):
    return types.SimpleNamespace(
        epub=str(epub), slice=None, max_chars=4000,
        model_llm="mistral-large-latest", reprepare=False,
        model="gemini-3.8-flash-tts", pace=0, gap_ms=250,
        narrator="Rami", voice_m="Rami", voice_f="Kore", single=None,
        lines_per_request=lines_per_request, daily_requests=90,
        max_request_chars=2000,
    )


@pytest.mark.asyncio
async def test_process_chapter_batched_counts_requests_and_keeps_offsets(tmp_path):
    # 11 prepared lines with --lines-per-request 5 = 3 batches (5+5+1)
    # = 2 multi-speaker requests + 1 single-line request = 3 requests
    # total, where the per-line method would spend 11 — and the SMIL
    # still carries one par per line.
    epub = _fixture_epub(tmp_path)
    args = _chapter_args(tmp_path, epub, lines_per_request=5)
    work_dir = tmp_path / "work"

    prepared = "\n\n".join(f"Riga numero {i} del capitolo di prova." for i in
                          range(11))
    from epub_readaloud import slice_text, source_metadata, strip_title_leak
    from poc_reader import extract_epub_chapter
    book_title, _ = source_metadata(args.epub)
    text = strip_title_leak(
        slice_text(extract_epub_chapter(args.epub, 0), args.slice), book_title)
    fingerprint = "|".join(str(x) for x in
                          (Path(args.epub).resolve(), 0, args.slice,
                           args.max_chars, args.model_llm,
                           hashlib.sha1(text.encode()).hexdigest()))
    ch_dir = work_dir / "ch000"
    ch_dir.mkdir(parents=True)
    (ch_dir / "prepared_text.txt").write_text(prepared)
    (ch_dir / "prepared_meta.txt").write_text(fingerprint)

    lines = gr.split_long_narration(gr.parse_lines(prepared))
    assert len(lines) == 11

    def batch_wav(turns):
        durs = [0.4 + 0.02 * len(t) for _v, t in turns]
        return _wav(_batch_pcm(durs))

    responses = []
    n = 11
    i = 0
    while i < n:
        size = min(5, n - i)
        if size == 1:
            responses.append(_wav(_speech_pcm(1.0)))
        else:
            responses.append(batch_wav([("Rami", f"Riga numero {j} del capitolo di prova.")
                                       for j in range(i, i + size)]))
        i += size
    eng = _FakeEngine(responses)

    class _RaisingClient:
        def chat(self):  # pragma: no cover - prepared text is cached
            raise AssertionError("llm_prepare must not be called")

    result = await gr.process_chapter(_RaisingClient(), args, 0, work_dir, eng)
    assert eng.request_count == 3  # 11 lines in 3 requests, not 11
    kinds = [c[0] for c in eng.calls]
    assert kinds == ["batch", "batch", "line"]
    # one SMIL par and one xhtml paragraph per prepared line
    assert result["smil"].count("<par") == 11
    assert result["xhtml"].count("<p") == 11
    # resume: a second run spends nothing (all batches cached)
    eng2 = _FakeEngine([])
    await gr.process_chapter(_RaisingClient(), args, 0, work_dir, eng2)
    assert eng2.request_count == 0


def _seg(text):
    # (speaker, gender, text, voice, voice_name)
    return (None, None, text, "Rami", "Rami")


def _segs(n, size):
    return [_seg("x" * size) for _ in range(n)]


def test_plan_batch_counts_splits_budget_over_chapters():
    # Owner policy (2026-10-09): hard on count — the planned request
    # count never exceeds the daily budget, whatever the line lengths.
    args = types.SimpleNamespace(lines_per_request=None, daily_requests=90,
                                 max_request_chars=2000)
    assert gr.plan_batch_counts(args, {0: _segs(100, 400)}) == {0: 90}
    # multiple chapters share the budget proportionally (equal text)
    segs = {0: _segs(100, 200), 1: _segs(100, 200)}
    assert gr.plan_batch_counts(args, segs) == {0: 45, 1: 45}
    # proportional with remainder: 3:1 text -> 68/22 (ties go to the
    # lower chapter index), still exactly the 90-request budget
    segs = {0: _segs(90, 300), 1: _segs(30, 300)}
    assert gr.plan_batch_counts(args, segs) == {0: 68, 1: 22}
    # a chapter cannot use more batches than it has lines
    segs = {0: [_seg("x" * 40000), _seg("y" * 40000)]}
    assert gr.plan_batch_counts(args, segs) == {0: 2}
    # every chapter with text keeps at least one batch even when the
    # budget is smaller than the chapter count
    args = types.SimpleNamespace(lines_per_request=None, daily_requests=2,
                                 max_request_chars=2000)
    segs = {0: _segs(5, 100), 1: _segs(5, 100), 2: _segs(5, 100)}
    assert gr.plan_batch_counts(args, segs) == {0: 1, 1: 1, 2: 1}


def test_plan_batch_counts_disables():
    args = types.SimpleNamespace(lines_per_request=None, daily_requests=90,
                                 max_request_chars=2000)
    segs = {0: [_seg("x" * 40000)]}
    # --lines-per-request overrides the auto-sizing
    args = types.SimpleNamespace(lines_per_request=10, daily_requests=90,
                                 max_request_chars=2000)
    assert gr.plan_batch_counts(args, segs) is None
    # --daily-requests 0 = the per-line box method
    args = types.SimpleNamespace(lines_per_request=None, daily_requests=0,
                                 max_request_chars=2000)
    assert gr.plan_batch_counts(args, segs) is None
    # nothing to read
    args = types.SimpleNamespace(lines_per_request=None, daily_requests=90,
                                 max_request_chars=2000)
    assert gr.plan_batch_counts(args, {0: []}) is None


def test_pack_batches_by_count_hard_count_soft_length():
    segs = [_seg("a" * 100), _seg("b" * 100), _seg("c" * 100),
            _seg("d" * 100)]
    # exactly n batches however the lengths fall
    batches = gr.pack_batches_by_count(segs, 2, 2000)
    assert [len(b) for b in batches] == [2, 2]
    batches = gr.pack_batches_by_count(segs, 3, 2000)
    assert [len(b) for b in batches] == [2, 1, 1]
    batches = gr.pack_batches_by_count(segs, 4, 2000)
    assert [len(b) for b in batches] == [1, 1, 1, 1]
    # n larger than the line count: one batch per line, never empty
    batches = gr.pack_batches_by_count(segs, 9, 2000)
    assert [len(b) for b in batches] == [1, 1, 1, 1]
    # the hard char cap bites: a line that would overflow starts a new
    # batch, so the count can exceed n (resumable via exit 75)
    batches = gr.pack_batches_by_count(segs, 2, 150)
    assert [len(b) for b in batches] == [1, 1, 1, 1]
    # a single line longer than the cap becomes its own batch
    segs = [_seg("a" * 100), _seg("b" * 500), _seg("c" * 100)]
    batches = gr.pack_batches_by_count(segs, 2, 250)
    assert [len(b) for b in batches] == [1, 1, 1]
    # empty input
    assert gr.pack_batches_by_count([], 3, 2000) == []


@pytest.mark.asyncio
async def test_process_chapter_auto_batched_fits_daily_budget(tmp_path):
    # 11 lines of ~36 chars (~400 total): a 3-request budget sizes
    # batches at ceil(total/3) chars, so lines pack into ~4 char-sized
    # batches instead of one request per line.
    epub = _fixture_epub(tmp_path)
    args = _chapter_args(tmp_path, epub, lines_per_request=None)
    work_dir = tmp_path / "work"

    line = "Riga numero {} del capitolo di prova."
    prepared = "\n\n".join(line.format(i) for i in range(11))
    from epub_readaloud import slice_text, source_metadata, strip_title_leak
    from poc_reader import extract_epub_chapter
    book_title, _ = source_metadata(args.epub)
    text = strip_title_leak(
        slice_text(extract_epub_chapter(args.epub, 0), args.slice), book_title)
    fingerprint = "|".join(str(x) for x in
                          (Path(args.epub).resolve(), 0, args.slice,
                           args.max_chars, args.model_llm,
                           hashlib.sha1(text.encode()).hexdigest()))
    ch_dir = work_dir / "ch000"
    ch_dir.mkdir(parents=True)
    (ch_dir / "prepared_text.txt").write_text(prepared)
    (ch_dir / "prepared_meta.txt").write_text(fingerprint)

    segments = gr.prepare_chapter(None, args, 0, work_dir)
    assert len(segments) == 11
    batches = gr.pack_batches_by_count(segments, 3, args.max_request_chars)
    assert 1 < len(batches) < 11  # batched, not per-line

    def batch_wav(turns):
        durs = [0.4 + 0.02 * len(t) for _v, t in turns]
        return _wav(_batch_pcm(durs))

    responses = [batch_wav([(seg[3], seg[2]) for seg in b])
                 for b in batches]
    eng = _FakeEngine(responses)

    result = await gr.process_chapter(None, args, 0, work_dir, eng,
                                      segments=segments,
                                      batch_count=3)
    assert eng.request_count == len(batches)
    assert result["smil"].count("<par") == 11
    assert result["xhtml"].count("<p") == 11
