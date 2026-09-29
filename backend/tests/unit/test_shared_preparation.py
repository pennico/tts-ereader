"""Unit tests for the shared text-preparation pipeline (AC-401, AC-403,
AC-405..AC-407, AC-803). No network: the LLM client is faked."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import text_preparation as tp


class FakeChat:
    def __init__(self, client):
        self.client = client

    def complete(self, model, messages):
        self.client.calls.append({"model": model, "messages": messages})
        if self.client.error:
            raise self.client.error
        resp = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=self.client.content))]
        )
        return resp


class FakeClient:
    """Mistral-like client returning a canned completion."""

    def __init__(self, content: str, error: Exception | None = None):
        self.chat = FakeChat(self)
        self.content = content
        self.error = error
        self.calls = []


# ── parse_lines (moved verbatim from edge_reader.py, AC-803) ────────────────


def test_parse_lines_one_line_tags():
    lines = tp.parse_lines("MADONNA [f]: Non è vero.\nNarrazione pura.")
    assert lines == [
        ("MADONNA", "f", "Non è vero."),
        (None, None, "Narrazione pura."),
    ]


def test_parse_lines_two_line_tag_format():
    lines = tp.parse_lines("RAIMUNDO [m]:\nSì, è così.")
    assert lines == [("RAIMUNDO", "m", "Sì, è così.")]


def test_parse_lines_untagged_speaker_label():
    lines = tp.parse_lines("MADONNA:\nChe dici?")
    assert lines == [("MADONNA", None, "Che dici?")]


def test_parse_lines_saramago_style_prepared():
    """Saramago's unmarked dialogue comes back speaker-tagged (AC-405)."""
    prepared = (
        "La città dormiva ancora, disse la voce.\n"
        "MADONNA [f]: Chi è là?\n"
        "RAIMUNDO [m]: Sono io, il raimondo."
    )
    lines = tp.parse_lines(prepared)
    speakers = [s for s, _g, _t in lines]
    assert speakers == [None, "MADONNA", "RAIMUNDO"]
    assert lines[1][1] == "f"
    assert lines[2][1] == "m"


def test_split_long_narration_splits_at_sentences():
    narration = "Frase una. " * 40  # > 300 chars, no speaker
    out = tp.split_long_narration([(None, None, narration.strip())])
    assert len(out) > 1
    assert all(s is None for s, _g, _t in out)
    assert all(len(t) <= 300 for _s, _g, t in out)


def test_split_long_narration_keeps_dialogue_intact():
    long_dialogue = "x" * 400
    out = tp.split_long_narration([("MADONNA", "f", long_dialogue)])
    assert out == [("MADONNA", "f", long_dialogue)]


# ── language handling (AC-403, AC-407) ──────────────────────────────────────


def test_normalize_language():
    assert tp.normalize_language("it-IT") == "it"
    assert tp.normalize_language("da") == "da"
    assert tp.normalize_language("da-DK") == "da"
    assert tp.normalize_language(None) == "en"
    assert tp.normalize_language("fr") == "en"  # generic prompt fallback


def test_detect_language():
    assert tp.detect_language("Der var noget om æblet og øen.") == "da"
    assert tp.detect_language("La città dormiva, lontana.") == "it"
    assert tp.detect_language("The city slept.") == "en"
    assert tp.detect_language("") == "en"


def test_prepare_prompt_selects_language():
    assert "Saramago" in tp.prepare_prompt("it")
    assert "Alfabethuset" in tp.prepare_prompt("da-DK")
    assert tp.prepare_prompt("fr") == tp.PREPARE_PROMPT_EN


# ── llm_prepare with a faked client ─────────────────────────────────────────


def test_llm_prepare_returns_content_and_uses_language_prompt():
    client = FakeClient("Testo preparato.")
    out = tp.llm_prepare(client, "mistral-large-latest", "Testo grezzo", language="da")
    assert out == "Testo preparato."
    prompt = client.calls[0]["messages"][0]["content"]
    assert prompt.startswith(tp.PREPARE_PROMPT_DA)
    assert "Testo grezzo" in prompt


def test_llm_prepare_strips_markdown_fence_and_preamble():
    client = FakeClient("```\nEcco il testo preparato:\n\nFrase pulita.\n```")
    out = tp.llm_prepare(client, "m", "grezzo", language="it")
    assert out == "Frase pulita."


def test_llm_prepare_keeps_speaker_tag_preamble():
    """A first line that IS a speaker tag must not be dropped."""
    client = FakeClient("MADONNA [f]: Non è vero.\nAltro.")
    out = tp.llm_prepare(client, "m", "grezzo", language="it")
    assert out.startswith("MADONNA [f]:")


def test_llm_prepare_retries_then_raises(monkeypatch):
    monkeypatch.setattr(tp.time, "sleep", lambda _s: None)
    client = FakeClient("", error=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        tp.llm_prepare(client, "m", "grezzo", retries=3, language="it")
    assert len(client.calls) == 3


def test_llm_prepare_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(tp.time, "sleep", lambda _s: None)

    class Flaky:
        def __init__(self):
            self.chat = self
            self.n = 0

        def complete(self, model, messages):
            self.n += 1
            if self.n < 3:
                raise RuntimeError("transient")
            return types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        message=types.SimpleNamespace(content="Ok.")
                    )
                ]
            )

    assert tp.llm_prepare(Flaky(), "m", "grezzo", language="it") == "Ok."


def test_chunk_text_respects_max_chars():
    text = "\n\n".join(["parola " * 20] * 5)
    chunks = tp.chunk_text(text, max_chars=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert " ".join(chunks).count("parola") == 100
