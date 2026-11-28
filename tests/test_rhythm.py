"""Reading rhythm in prepared mode (review C221, findings 5-9): paragraph
ends, separators inside a request, pauses between requests, batch ends
snapped to paragraph/sentence ends, and chapters keep their batches.
"""
from __future__ import annotations

import json
import types

import pytest
from test_request_efficiency import _batch_pcm, _FakeEngine, _wav

import gemini_readaloud as gr
from shared import text_preparation as tp

PREPARED = """Uno.

PRESIDENTE [m]: Tempo pessimo per votare,
si lagnò il presidente entrando.
SEGRETARIO [m]: Siamo in orario,
lo tranquillizzò il segretario.

PRESIDENTE [m]: Per la verità,

aggiunse,

PRESIDENTE [m]: siamo qui come naufraghi."""


def _lines(prepared=PREPARED):
    return tp.split_long_narration(tp.parse_lines(prepared))


def test_paragraph_ends_only_after_a_finished_sentence():
    lines = _lines()
    ends = tp.paragraph_ends(PREPARED, lines)
    assert [t for (_s, _g, t), e in zip(lines, ends) if e] == [
        "Uno.", "lo tranquillizzò il segretario.",
        "siamo qui come naufraghi."]
    # A blank line after "Per la verità," / "aggiunse," is not a paragraph end.


def test_paragraph_ends_unknown_when_a_label_stands_before_a_blank_line():
    prepared = "ANNA [f]:\n\nCiao."
    assert tp.paragraph_ends(prepared, _lines(prepared)) is None


@pytest.mark.asyncio
async def test_synth_batch_joins_a_paragraph_into_one_passage(tmp_path):
    turns = [("Rami", "Tempo pessimo per votare,"),
             ("Rami", "si lagnò il presidente."),
             ("Rami", "Nuovo paragrafo.")]
    eng = _FakeEngine([_wav(_batch_pcm([1.0, 1.0, 1.0]))])
    await gr.synth_batch(eng, turns, tmp_path, pace=0,
                         para_ends=[False, True, True])
    assert eng.separators == [[" ", "\n\n"]]


def test_request_gaps(tmp_path):
    segs = [(None, None, t, "Rami", "Rami") for t in
            ("Una frase,", "fine frase.", "Fine paragrafo.", "dopo virgola,",
             "senza punto", "ultima.")]
    files = [tmp_path / "batch-aaaa-000.wav", tmp_path / "batch-aaaa-001.wav",
             tmp_path / "batch-bbbb-000.wav", tmp_path / "Rami-cccc.wav",
             tmp_path / "Rami-dddd.wav", tmp_path / "Rami-eeee.wav"]
    para_ends = [False, False, True, False, False, True]
    assert gr.request_gaps(files, segs, para_ends, 250) == [
        0,                   # same take: the take's own pause
        250,                 # sentence end
        500,                 # paragraph end
        gr.GAP_CLAUSE_MS,    # comma
        125,                 # no punctuation
        0]                   # last line


def _segs(texts):
    return [(None, None, t, "Rami", "Rami") for t in texts]


def test_snapped_packing_moves_the_cut_to_a_paragraph_end():
    texts = ["a" * 90 + ".", "b" * 90 + ",", "c" * 90 + ".", "d" * 90 + ".",
             "e" * 90 + ".", "f" * 90 + "."]
    segs = _segs(texts)
    para = [False, False, False, True, False, True]
    # 2 batches: the ideal cut is after line 2 (a comma); line 3 ends a
    # paragraph within reach, so the cut moves there.
    old = gr.pack_batches_by_count(segs, 2, 2000)
    new = gr.pack_batches_snapped(segs, 2, 2000, para)
    assert [len(b) for b in old] == [3, 3]
    assert [len(b) for b in new] == [4, 2]


def test_snapped_packing_keeps_count_and_cap():
    segs = _segs(["x" * 99 + "." for _ in range(20)])
    batches = gr.pack_batches_snapped(segs, 5, 2000)
    assert len(batches) == 5 and sum(map(len, batches)) == 20
    capped = gr.pack_batches_snapped(segs, 2, 450)
    assert all(sum(len(s[2]) + 1 for s in b) <= 450 for b in capped)
    assert [s for b in capped for s in b] == segs


def test_chapter_batches_keeps_a_started_chapter_on_the_old_packing(tmp_path):
    eng = types.SimpleNamespace(model="gemini-3.8-flash-lite-tts")
    texts = ["a" * 90 + ".", "b" * 90 + ",", "c" * 90 + ".", "d" * 90 + ".",
             "e" * 90 + ".", "f" * 90 + "."]
    segs = _segs(texts)
    para = [False, False, False, True, False, True]
    cache, ch = tmp_path / "cache", tmp_path / "ch"
    cache.mkdir()
    ch.mkdir()
    legacy = gr.pack_batches_by_count(segs, 2, 2000)
    turns = [(s[3], s[2]) for s in legacy[0]]
    (cache / f"batch-{gr._batch_key(eng, turns)}-000.wav").write_bytes(b"x" * 2000)
    batches = gr.chapter_batches(eng, segs, 2, 2000, ch, cache, para)
    assert batches == legacy
    plan = json.loads((ch / "batches.json").read_text())
    assert plan["packing"] == "legacy" and plan["counts"] == [3, 3]


def test_chapter_batches_new_chapter_is_snapped_and_the_plan_sticks(tmp_path):
    eng = types.SimpleNamespace(model="m")
    segs = _segs(["a" * 90 + ".", "b" * 90 + ",", "c" * 90 + ".",
                  "d" * 90 + ".", "e" * 90 + ".", "f" * 90 + "."])
    para = [False, False, False, True, False, True]
    cache, ch = tmp_path / "cache", tmp_path / "ch"
    cache.mkdir()
    ch.mkdir()
    first = gr.chapter_batches(eng, segs, 2, 2000, ch, cache, para)
    assert [len(b) for b in first] == [4, 2]
    # A later night with another request budget keeps the saved plan.
    again = gr.chapter_batches(eng, segs, 3, 2000, ch, cache, para)
    assert again == first
    # Changed lines (re-prepared text): a new plan.
    segs2 = segs[:-1] + _segs(["g" * 90 + "."])
    assert gr.chapter_batches(eng, segs2, 3, 2000, ch, cache, para) != first


def test_best_effort_split_returns_the_whole_take(tmp_path):
    from test_request_efficiency import _speech_pcm
    pcm = _speech_pcm(3.0)
    chunks = gr.split_batch_best_effort(pcm, 2, 24000, [10, 20, 30])
    assert len(chunks) == 3 and b"".join(chunks) == pcm
    assert all(len(c) > 0 for c in chunks)

