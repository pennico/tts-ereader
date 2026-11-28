"""Claude as the text-preparation LLM, through the Claude Code CLI.

A drop-in for the Mistral client's `client.chat.complete(model=...,
messages=[...])` used by text_preparation.llm_prepare, so the prepared
pipeline can run on the owner's Claude subscription
(CLAUDE_CODE_OAUTH_TOKEN, from `claude setup-token`) instead of the
Mistral API (2026-10-17: Mistral monthly spending limit reached).

Each call is one `claude -p` turn with no tools, no settings, no session
file, run from an empty temp dir; the prompt goes in on stdin.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from types import SimpleNamespace

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
TIMEOUT_S = int(os.environ.get("PREP_LLM_TIMEOUT_S", "600"))
SYSTEM = ("You are a careful text preparer. Follow the user's instructions "
          "exactly and return only the requested text.")


def is_claude_model(model: str | None) -> bool:
    return bool(model) and model.startswith("claude")


class ClaudeCLIError(RuntimeError):
    pass


class _Completions:
    def complete(self, model, messages):
        prompt = "\n\n".join(m["content"] for m in messages
                             if m.get("role") == "user")
        cmd = [CLAUDE_BIN, "-p", "--model", model, "--output-format", "json",
               "--tools", "", "--system-prompt", SYSTEM, "--max-turns", "1",
               "--permission-mode", "dontAsk", "--setting-sources", "",
               "--no-session-persistence"]
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)  # bill the subscription, never the API
        with tempfile.TemporaryDirectory(prefix="prep-llm-") as cwd:
            try:
                r = subprocess.run(cmd, input=prompt, capture_output=True,
                                   text=True, timeout=TIMEOUT_S, cwd=cwd,
                                   env=env)
            except subprocess.TimeoutExpired as e:
                raise ClaudeCLIError(f"claude timed out after {TIMEOUT_S}s") from e
        try:
            res = json.loads(r.stdout or "{}")
        except ValueError:
            res = {}
        text = res.get("result") if isinstance(res, dict) else None
        if r.returncode != 0 or res.get("is_error") or not text:
            detail = (str(text or "") or r.stderr or r.stdout)[:300]
            raise ClaudeCLIError(f"claude failed (exit {r.returncode}): {detail}")
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=text))])


class ClaudeCLIClient:
    """`client.chat.complete(model, messages)` like the Mistral SDK."""

    def __init__(self):
        self.chat = _Completions()
