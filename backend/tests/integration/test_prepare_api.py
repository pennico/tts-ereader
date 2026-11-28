"""Integration tests for chapter preparation + voice cast (AC-305, AC-401,
AC-403, AC-405..AC-407). The LLM client is faked; no network."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engines import factory
from app.services import llm_service

from tests.mock_engine import MockTTSEngine

PREPARED_IT = (
    "La città dormiva ancora.\n"
    "MADONNA [f]: Chi è là?\n"
    "RAIMUNDO [m]: Sono io.\n"
    "LUCIA [f]: Ascolta bene."
)


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = 0
        self.chat = self

    def complete(self, model, messages):
        self.calls += 1
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=self.content))]
        )


@pytest.fixture()
def fake_llm(monkeypatch):
    client = FakeClient(PREPARED_IT)
    monkeypatch.setattr(llm_service, "client_factory", lambda: client)
    return client


@pytest.fixture()
def no_llm(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    factory_ = llm_service.client_factory
    monkeypatch.setattr(llm_service, "client_factory", None)
    yield
    llm_service.client_factory = factory_


@pytest.fixture()
def mock_engine():
    saved = dict(factory._REGISTRY)
    engine = MockTTSEngine()
    factory.register(engine)
    yield engine
    factory._REGISTRY.clear()
    factory._REGISTRY.update(saved)


def _import(client, epub_path: Path):
    with open(epub_path, "rb") as f:
        return client.post(
            "/api/books", files={"file": (epub_path.name, f, "application/epub+zip")}
        ).json()["id"]


def _prepare(client, book_id, **extra):
    return client.post(
        f"/api/books/{book_id}/chapters/0/prepare",
        json={"engine": "edge", **extra},
    )


def test_prepare_returns_cast_resolved_segments(client, fixture_epubs, fake_llm):
    book_id = _import(client, fixture_epubs["dialogue_it"])
    resp = _prepare(client, book_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is False
    assert body["language"] == "it"
    segs = body["segments"]
    # Narration + MADONNA (first female) + RAIMUNDO (male=narrator) + LUCIA
    assert [s["role"] for s in segs] == [
        "narrator",
        "female_1",
        "narrator",
        "female_other",
    ]
    assert segs[1]["speaker"] == "MADONNA"
    assert segs[1]["gender"] == "f"
    # Default Italian edge cast (AC-305: different voices per character).
    assert segs[0]["voice"] == "it-IT-GiuseppeMultilingualNeural"
    assert segs[1]["voice"] == "fr-FR-VivienneMultilingualNeural"
    assert segs[3]["voice"] == "en-US-EmmaMultilingualNeural"


def test_prepare_is_cached_after_first_call(client, fixture_epubs, fake_llm):
    book_id = _import(client, fixture_epubs["dialogue_it"])
    first = _prepare(client, book_id).json()
    assert first["cached"] is False
    assert fake_llm.calls == 1
    second = _prepare(client, book_id).json()
    assert second["cached"] is True
    assert fake_llm.calls == 1  # no re-billing
    assert [s["voice"] for s in second["segments"]] == [
        s["voice"] for s in first["segments"]
    ]


def test_prepare_cast_overrides(client, fixture_epubs, fake_llm):
    book_id = _import(client, fixture_epubs["dialogue_it"])
    body = _prepare(
        client, book_id, cast={"female_1": "da-DK-ChristelNeural"}
    ).json()
    voices = {s["role"]: s["voice"] for s in body["segments"]}
    assert voices["female_1"] == "da-DK-ChristelNeural"
    assert voices["female_other"] == "en-US-EmmaMultilingualNeural"  # untouched


def test_prepare_force_reruns_llm(client, fixture_epubs, fake_llm):
    book_id = _import(client, fixture_epubs["dialogue_it"])
    _prepare(client, book_id)
    assert fake_llm.calls == 1
    body = _prepare(client, book_id, force=True).json()
    assert body["cached"] is False
    assert fake_llm.calls == 2


def test_prepare_without_key_is_503(client, fixture_epubs, no_llm):
    book_id = _import(client, fixture_epubs["dialogue_it"])
    resp = _prepare(client, book_id)
    assert resp.status_code == 503
    assert "MISTRAL_API_KEY" in resp.json()["detail"]


def test_get_prepared_404_then_cached(client, fixture_epubs, fake_llm):
    book_id = _import(client, fixture_epubs["dialogue_it"])
    assert (
        client.get(f"/api/books/{book_id}/chapters/0/prepared").status_code == 404
    )
    _prepare(client, book_id)
    resp = client.get(
        f"/api/books/{book_id}/chapters/0/prepared", params={"engine": "edge"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is True
    assert body["segments"][1]["voice"] == "fr-FR-VivienneMultilingualNeural"


def test_prepare_unknown_book_or_chapter_404(client, fixture_epubs, fake_llm):
    book_id = _import(client, fixture_epubs["dialogue_it"])
    assert _prepare(client, 999).status_code == 404
    resp = client.post(f"/api/books/{book_id}/chapters/99/prepare", json={})
    assert resp.status_code == 404


def test_danish_book_uses_danish_prompt_and_cast(client, fixture_epubs, fake_llm):
    """AC-403/AC-406: Danish preparation + Danish default cast."""
    book_id = _import(client, fixture_epubs["dialogue_da"])
    resp = _prepare(client, book_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["language"] == "da"
    voices = {s["role"]: s["voice"] for s in body["segments"]}
    assert voices["narrator"] == "da-DK-JeppeNeural"
    assert voices["female_1"] == "da-DK-ChristelNeural"


def test_cast_defaults_endpoint(client):
    resp = client.get("/api/tts/cast-defaults", params={"engine": "edge", "language": "da"})
    assert resp.status_code == 200
    body = resp.json()
    by_role = {r["role"]: r for r in body["roles"]}
    assert by_role["narrator"]["voice"] == "da-DK-JeppeNeural"
    assert by_role["female_1"]["voice_display_name"] == "Christel"
    assert by_role["narrator"]["display_name"] == "Narrator / male characters"

    resp = client.get("/api/tts/cast-defaults")
    body = resp.json()
    assert body["engine"] == "gemini"  # documented default engine
    assert {r["role"] for r in body["roles"]} == {
        "narrator",
        "female_1",
        "female_other",
        "male_short",
    }


def test_synthesize_batch_with_per_text_voices(client, mock_engine):
    """AC-305 playback: each segment synthesized with its cast voice."""
    resp = client.post(
        "/api/tts/synthesize-batch",
        json={
            "texts": ["Prima.", "Seconda."],
            "engine": "mock",
            "voice": "mock-voice",
            "voices": ["mock-voice-da", ""],
        },
    )
    assert resp.status_code == 200
    segments = resp.json()["segments"]
    assert [s["text"] for s in segments] == ["Prima.", "Seconda."]
    assert mock_engine.voice_calls == [("mock-voice-da", "Prima."), ("mock-voice", "Seconda.")]


def test_synthesize_batch_voices_length_mismatch_422(client, mock_engine):
    resp = client.post(
        "/api/tts/synthesize-batch",
        json={
            "texts": ["Prima.", "Seconda."],
            "engine": "mock",
            "voice": "mock-voice",
            "voices": ["mock-voice-da"],
        },
    )
    assert resp.status_code == 422
