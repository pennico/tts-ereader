"""Loyal-mode tests (owner decision, 2026-10-09).

The prepared mode's LLM pass keeps every word but rewrites the rhythm
(merged clauses, added periods, dialogue lifted onto speaker lines) —
wrong for authors whose rhythm IS the work. The loyal mode keeps the
text VERBATIM: the only interventions are removing the edition's
footnote apparatus and splitting paragraphs at the author's own
sentence boundaries so one segment stays under the ~400-char
recitation-filter threshold. These tests pin that contract with no
network, no API key, no spend.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))

import gemini_readaloud as gr  # noqa: E402
from shared.text_preparation import loyal_prepare  # noqa: E402


def test_loyal_prepare_defers_footnotes_to_first_available_point():
    # Owner decision, 2026-10-10: the edition embeds note bodies inline,
    # mid-sentence; a verbatim read hears them at a wrong time. The
    # body must be lifted out and re-read at the first available point
    # (here: the comma + capital dialogue break), prefixed with a
    # recall of the word the reference attached to.
    text = ("Parla del fiume [1] nella città, 1 - Il fiume è il Tago.\n\n"
            "e la città dormiva, Poi venne l'alba.")
    out = loyal_prepare(text)
    assert "[1]" not in out and "1 -" not in out
    assert "nella città, e la città dormiva," in " ".join(out.split())
    assert "Nota 1, fiume: Il fiume è il Tago." in out
    # the note lands between the break ("dormiva,") and the flow resume
    flat = " ".join(out.split())
    assert flat.index("dormiva,") < flat.index("Nota 1,") < flat.index("Poi venne")


def test_loyal_prepare_keeps_note_already_on_a_break_in_place():
    # A body that already sits on a break (comma + capital) is read in
    # place, only wrapped in the recall prefix.
    text = ("Lei è irrimediabilmente scettico, come disse Camões [2], "
            "2 - Luis Vas de Camões, esule in India.\n\n"
            "Tutti gli autori sono Apelle.")
    out = loyal_prepare(text)
    flat = " ".join(out.split())
    assert "Camões, Nota 2, Camões: Luis Vas de Camões," in flat
    assert flat.index("Nota 2,") < flat.index("Tutti gli autori")


def test_loyal_prepare_ref_without_body_is_just_stripped():
    text = "La città era lì, con le sue case[3], e il fiume[12] passava."
    out = loyal_prepare(text)
    assert "[3]" not in out and "[12]" not in out
    assert "case, e il fiume passava." in " ".join(out.split())
    assert "Nota" not in out


def test_loyal_prepare_body_dates_do_not_spawn_false_notes():
    # "1845 - Parigi" inside a body must not be taken for the marker of
    # another pending reference: the (?<!\d) guard blocks it.
    text = ("Ricorda Eça [1] e Camões [2] a lungo, 1 - Il narratore "
            "(Minho 1845 - Parigi 1900) fu un revisore.\n\n"
            "e la città dormiva, Poi venne l'alba.")
    out = loyal_prepare(text)
    assert out.count("Nota ") == 1
    assert "Nota 1, Eça:" in out


def test_loyal_prepare_is_verbatim():
    prose = ("La città era lì, con le sue case, e il fiume passava, "
             "lento, come se non avesse fretta alcuna.")
    out = loyal_prepare(prose)
    assert out.strip() == prose  # no repunctuation, no speaker tags


def test_loyal_prepare_splits_long_paragraphs_at_sentences():
    sentence = "La casa era grande e piena di porte che si aprivano su altre porte."
    # 6 sentences x 68 chars = 408 chars: must split, each piece <= 300
    paragraph = " ".join([sentence] * 6)
    out = loyal_prepare(paragraph, max_chars=300)
    pieces = [p for p in out.split("\n\n") if p.strip()]
    assert len(pieces) > 1
    assert all(len(p) <= 300 for p in pieces)
    # split only at the author's own sentence boundaries
    assert all(p.rstrip().endswith(".") for p in pieces)
    # nothing added, nothing lost (whitespace-normalized: the split
    # point drops the one space that joined the two halves)
    assert "".join("".join(p.split()) for p in pieces) == paragraph.replace(" ", "")


def test_loyal_prepare_splits_comma_chain_sentences_at_clauses():
    # Saramago: a 3123-char "sentence" with no period at all. The
    # split must fall back to the author's own clause punctuation and
    # still keep every piece under the recitation-filter threshold.
    clause = "la casa era grande," + " e piena di porte che si aprivano su altre stanze," * 30
    assert len(clause) > 900 and "." not in clause
    out = loyal_prepare(clause, max_chars=300)
    pieces = [p for p in out.split("\n\n") if p.strip()]
    assert len(pieces) > 3
    assert all(len(p) <= 300 for p in pieces)
    # verbatim: the commas survive, nothing added or lost
    assert "".join("".join(p.split()) for p in pieces) == clause.replace(" ", "")


def _loyal_args(epub, **overrides):
    base = dict(epub=str(epub), slice=0, max_chars=4000,
                model_llm="mistral-large-latest", prepare_mode="loyal",
                reprepare=False, single="Rami", cast=False,
                narrator="Kore", voice_f="Aoede", voice_m="Puck")
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _fixture_epub(tmp_path):
    from make_fixture_epub import make_all_fixtures
    epubs_dir = tmp_path / "epubs"
    make_all_fixtures(epubs_dir)
    return epubs_dir / "saramago_style.epub"


def test_prepare_chapter_loyal_needs_no_llm(tmp_path, monkeypatch):
    # client=None must be fine: the loyal path never touches the LLM.
    epub = _fixture_epub(tmp_path)

    def _no_llm(*a, **k):
        raise AssertionError("loyal mode must not call the LLM")

    monkeypatch.setattr(gr, "llm_prepare", _no_llm)
    args = _loyal_args(epub)
    segments = gr.prepare_chapter(None, args, 0, tmp_path / "work")
    assert segments
    for speaker, gender, text, voice, _ in segments:
        assert speaker is None  # verbatim prose: no invented speakers
        assert voice == "Rami"
        assert len(text) <= 300  # under the recitation-filter threshold


def test_prepared_fingerprint_separates_prepare_modes(tmp_path, monkeypatch):
    # Same source, two prepare modes: the cached prepared text of one
    # mode must never be reused for the other.
    epub = _fixture_epub(tmp_path)

    monkeypatch.setattr(gr, "llm_prepare",
                        lambda client, model, chunk: chunk.upper())
    fingerprints = []
    for mode in ("prepared", "loyal"):
        ch_dir = tmp_path / "work" / mode
        ch_dir.mkdir(parents=True)
        args = _loyal_args(epub, prepare_mode=mode, reprepare=True)
        gr.prepared_chapter_text(object(), args, 0, ch_dir, "same text")
        fingerprints.append((ch_dir / "prepared_meta.txt").read_text())
    assert fingerprints[0] != fingerprints[1]
