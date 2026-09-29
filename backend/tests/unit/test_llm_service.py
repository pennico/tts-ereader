"""Unit tests for the LLM preparation service (AC-401, AC-403)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services import llm_service


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = []
        self.chat = self

    def complete(self, model, messages):
        self.calls.append(messages[0]["content"])
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=self.content))]
        )


PREPARED = "Narrazione pura.\n\nMADONNA [f]: Non è vero."


def test_prepare_text_chunks_long_chapters():
    # chunk_text splits at paragraph boundaries, like the v0 pipeline
    text = "\n\n".join(["Paragrafo uno. " * 20] * 5)
    client = FakeClient("Pulito.")
    out = llm_service.prepare_text(text, language="it", client=client, max_chars=400)
    assert len(client.calls) == 5  # one LLM call per chunk
    assert out == "\n\n".join(["Pulito."] * 5)


def test_prepare_text_uses_book_language():
    client = FakeClient("Renset.")
    llm_service.prepare_text("Der var engang.", language="da-DK", client=client)
    assert client.calls[0].startswith("Du er en tekstforbereder")


def test_segment_lines_parses_speakers():
    lines = llm_service.segment_lines(PREPARED)
    assert lines == [
        (None, None, "Narrazione pura."),
        ("MADONNA", "f", "Non è vero."),
    ]


def test_get_client_raises_without_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    factory = llm_service.client_factory
    llm_service.client_factory = None
    try:
        with pytest.raises(llm_service.LLMUnavailableError):
            llm_service.get_client()
    finally:
        llm_service.client_factory = factory


def test_get_client_uses_injected_factory():
    sentinel = object()
    llm_service.client_factory = lambda: sentinel
    try:
        assert llm_service.get_client() is sentinel
    finally:
        llm_service.client_factory = None


def test_prepared_cache_roundtrip(settings):
    data = llm_service.save_prepared(
        settings, 3, 0, "it", PREPARED
    )
    assert data["language"] == "it"
    assert data["lines"][1] == ["MADONNA", "f", "Non è vero."]
    loaded = llm_service.load_prepared(settings, 3, 0)
    assert loaded == data
    assert llm_service.load_prepared(settings, 3, 1) is None
    assert llm_service.load_prepared(settings, 9, 0) is None
