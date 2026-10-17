"""Claude Code CLI adapter for text preparation (shared/claude_cli.py)."""
import json
import subprocess

import pytest

from shared import claude_cli
from shared.text_preparation import llm_prepare


def _fake_run(seen, stdout, code=0):
    def run(cmd, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="")
    return run


def test_complete_runs_locked_down_cli(monkeypatch):
    seen = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "api-key")
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(
        seen, json.dumps({"result": "TESTO [f]: ciao", "is_error": False})))
    client = claude_cli.ClaudeCLIClient()
    resp = client.chat.complete(model="claude-sonnet-5-5", messages=[
        {"role": "user", "content": "prompt\n\n---\n\ntesto"}])
    assert resp.choices[0].message.content == "TESTO [f]: ciao"
    cmd, kw = seen[0]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--no-session-persistence" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert kw["input"].endswith("testo")
    assert "ANTHROPIC_API_KEY" not in kw["env"]


def test_complete_raises_on_error(monkeypatch):
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(
        [], json.dumps({"result": "usage limit", "is_error": True}), code=1))
    with pytest.raises(claude_cli.ClaudeCLIError):
        claude_cli.ClaudeCLIClient().chat.complete(
            model="claude-haiku-5-5", messages=[{"role": "user", "content": "x"}])


def test_llm_prepare_works_with_the_adapter(monkeypatch):
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(
        [], json.dumps({"result": "*Ecco* il testo", "is_error": False})))
    out = llm_prepare(claude_cli.ClaudeCLIClient(), "claude-sonnet-5-5", "testo")
    assert out == "Ecco il testo"


def test_is_claude_model():
    assert claude_cli.is_claude_model("claude-haiku-5-5")
    assert not claude_cli.is_claude_model("mistral-large-latest")
    assert not claude_cli.is_claude_model(None)


@pytest.mark.parametrize("raw,expected", [
    ("Ecco il testo preparato:\nIl revisore tacque.", "Il revisore tacque."),
    ("Here is the prepared text:\nHe said nothing.", "He said nothing."),
    ("Il revisore guardò la finestra, poi disse:\nREVISORE [m]: Non so.",
     "Il revisore guardò la finestra, poi disse:\nREVISORE [m]: Non so."),
])
def test_only_real_preambles_are_dropped(monkeypatch, raw, expected):
    monkeypatch.setattr(claude_cli.subprocess, "run", _fake_run(
        [], json.dumps({"result": raw, "is_error": False})))
    assert llm_prepare(claude_cli.ClaudeCLIClient(), "claude-sonnet-5-5",
                       "x") == expected
