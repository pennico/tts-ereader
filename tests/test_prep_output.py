"""Prepared-text safety (review C221): speaker labels are never spoken
(finding 4), and a chunk the LLM shortened or rewrote is caught (finding 3).
"""
from __future__ import annotations

import pytest

from shared import text_preparation as tp


@pytest.mark.parametrize("raw,expected", [
    ("PRESIDENTE [M]: Signori.", ("PRESIDENTE", "m", "Signori.")),
    ("IL MINISTRO DELL’INTERNO [m]: No.", ("IL MINISTRO DELL’INTERNO", "m", "No.")),
    ("DR. ROSSI [F]: Sì.", ("DR. ROSSI", "f", "Sì.")),
    ("BØRGE [m]: Hej.", ("BØRGE", "m", "Hej.")),
    ("X [?]: boh.", ("X", None, "boh.")),
])
def test_speaker_label_variants_are_never_spoken(raw, expected):
    assert tp.parse_lines(raw) == [expected]


def test_two_line_label_with_hyphenated_name():
    assert tp.parse_lines("JEAN-PAUL [M]:\nCiao.") == [("JEAN-PAUL", "m", "Ciao.")]


def test_narration_with_a_colon_stays_narration():
    line = "Poi il presidente disse: ecco."
    assert tp.parse_lines(line) == [(None, None, line)]


SOURCE = ("Pioveva sulla città da tre giorni, e gli elettori arrivavano ai seggi "
          "con gli ombrelli gocciolanti, salutavano il presidente, firmavano il "
          "registro, entravano nella cabina e ne uscivano senza dire una parola. "
          "Il segretario contava le schede, il vicepresidente guardava la porta, "
          "e fuori la strada restava vuota come una domenica d'agosto.")


class _Client:
    """Mistral-shaped fake that answers from a list, in order."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0
        self.chat = self

    def complete(self, model, messages):
        from types import SimpleNamespace as NS
        text = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return NS(choices=[NS(message=NS(content=text))])


def test_prep_drift_accepts_faithful_and_flags_cut_or_padded_text():
    assert tp.prep_drift(SOURCE, SOURCE.replace(", e gli", ". Gli")) is None
    assert "kept only" in tp.prep_drift(SOURCE, SOURCE[: len(SOURCE) // 2])
    assert "word count" in tp.prep_drift(SOURCE, SOURCE + " " + SOURCE)
    # Speaker labels are not counted as words.
    labelled = "PRESIDENTE [m]: " + SOURCE
    assert tp.prep_drift(SOURCE, labelled) is None


def test_verify_retries_a_drifting_answer(monkeypatch):
    monkeypatch.setattr(tp.time, "sleep", lambda _s: None)
    client = _Client([SOURCE[:80], SOURCE])
    assert tp.llm_prepare(client, "m", SOURCE, verify=True) == SOURCE
    assert client.calls == 2


def test_verify_raises_when_every_answer_drifts(monkeypatch):
    monkeypatch.setattr(tp.time, "sleep", lambda _s: None)
    client = _Client([SOURCE[:80]])
    with pytest.raises(tp.PrepDrift):
        tp.llm_prepare(client, "m", SOURCE, verify=True)
    assert client.calls == 3


def test_without_verify_the_answer_is_returned_as_before():
    assert tp.llm_prepare(_Client([SOURCE[:80]]), "m", SOURCE) == SOURCE[:80]


def test_gemini_falls_back_to_verbatim_for_a_drifting_chunk(tmp_path, monkeypatch):
    import types

    import gemini_readaloud as gr

    def _drifting(*_a, **_kw):
        raise tp.PrepDrift("kept only 40% of the source words")

    monkeypatch.setattr(gr, "llm_prepare", _drifting)
    args = types.SimpleNamespace(epub=str(tmp_path / "missing.epub"), slice=0,
                                 max_chars=4000, model_llm="m",
                                 prepare_mode="prepared", reprepare=True)
    out = gr.prepared_chapter_text(None, args, 0, tmp_path, SOURCE)
    assert out == tp.loyal_prepare(SOURCE)
