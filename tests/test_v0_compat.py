"""v0 CLI backward-compatibility tests (AC-801..AC-803).

edge_reader.py now delegates preparation + voice cast to shared/ (M3); these
tests pin the CLI surface and the Italian cast output so the refactor cannot
silently change v0 behavior. No network: the LLM client is never constructed
(MISTRAL_API_KEY is a dummy used only to pass the CLI's key check for
--list-chapters).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TESTS_DIR / "fixtures"))

from make_fixture_epub import make_all_fixtures  # noqa: E402

import edge_reader  # noqa: E402
from shared import text_preparation, voice_cast  # noqa: E402

SARAMAGO_PREPARED = (
    "Se il mondo fosse semplice, disse la voce, non servirebbero le parole.\n"
    "MADONNA [f]: Chi è là?\n"
    "RAIMUNDO [m]:\nSono io, disse lui, e aggiunse che era tornato per restare "
    "questa volta, forse per sempre, chi poteva saperlo.\n"
    "PORTINAIO: Sì?"
)


def test_edge_reader_reuses_shared_modules():
    """AC-803: the cast/preparation logic is the shared implementation."""
    assert edge_reader.parse_lines is text_preparation.parse_lines
    assert edge_reader.split_long_narration is text_preparation.split_long_narration
    assert edge_reader._assign_voices is voice_cast.assign_voices


def test_v0_voice_constants_unchanged():
    assert edge_reader.VOICE_NARRATOR == "it-IT-GiuseppeMultilingualNeural"
    assert edge_reader.VOICE_FEMALE_1 == "fr-FR-VivienneMultilingualNeural"
    assert edge_reader.VOICE_FEMALE_2 == "en-US-EmmaMultilingualNeural"
    assert edge_reader.VOICE_SHORT_MALE == "en-US-AndrewMultilingualNeural"
    assert edge_reader.RATE_DEFAULT == "-8%"
    assert edge_reader.LLM_MODEL_DEFAULT == "mistral-large-latest"


def test_v0_pipeline_output_unchanged():
    """The full prepare->parse->cast chain reproduces the v0 assignments."""
    lines = edge_reader.split_long_narration(edge_reader.parse_lines(SARAMAGO_PREPARED))
    segments = edge_reader.assign_voices(lines, andrew_short=True)
    by_speaker = {s: (voice, name) for s, _g, _t, voice, name in segments if s}
    assert by_speaker["MADONNA"] == ("fr-FR-VivienneMultilingualNeural", "Vivienne")
    assert by_speaker["RAIMUNDO"] == ("it-IT-GiuseppeMultilingualNeural", "Giuseppe")
    assert by_speaker["PORTINAIO"] == ("en-US-AndrewMultilingualNeural", "Andrew")
    # Narration reads with the narrator voice.
    assert segments[0][3] == "it-IT-GiuseppeMultilingualNeural"


def test_cli_help_lists_all_v0_options(capsys):
    """AC-802: the CLI options are unchanged."""
    with mock.patch.object(sys, "argv", ["edge_reader.py", "--help"]):
        with pytest.raises(SystemExit) as exc:
            edge_reader.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in (
        "--text", "--file", "--epub", "--chapter", "--list-chapters",
        "--label", "--output-dir", "--rate", "--workers", "--model",
        "--max-chars", "--andrew-short",
    ):
        assert flag in out, f"missing v0 CLI option {flag}"


def test_cli_list_chapters(tmp_path, capsys, monkeypatch):
    """AC-801: --list-chapters still runs end to end (no network)."""
    monkeypatch.setenv("MISTRAL_API_KEY", "dummy-key-for-cli-check")
    epub = make_all_fixtures(tmp_path)[0]
    with mock.patch.object(
        sys, "argv", ["edge_reader.py", "--epub", str(epub), "--list-chapters"]
    ):
        edge_reader.main()
    out = capsys.readouterr().out
    assert "[ 0]" in out
    assert "chars" in out


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeClient:
    def __init__(self, content):
        self._content = content
        self.chat = self

    def complete(self, model, messages):
        return _FakeResponse(self._content)


def test_llm_prepare_strips_markdown_emphasis():
    """Markdown emphasis the model adds (*parola*) must not reach the
    engines: the read-along build read asterisks aloud (owner report,
    Saramago full-book run 2026-09-19)."""
    raw = ("Il correttore sta leggendo *Storia dell'assedio di Lisbona*, "
           "e la parola è *sì*, che cambia in *no*.\n"
           "MADONNA [f]: Chi è là?")
    out = text_preparation.llm_prepare(_FakeClient(raw), "mistral-large-latest",
                                       "testo grezzo", language="it")
    assert "*" not in out
    assert "Storia dell'assedio di Lisbona," in out
    assert "sì," in out
    assert "no." in out
    assert "MADONNA [f]: Chi è là?" in out
