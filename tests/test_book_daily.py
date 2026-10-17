"""book-daily.sh configuration tests.

The scheduled job calls `bash book-daily.sh` with no arguments, so the
defaults must stay exactly what the running book uses (its work dir is
the segment cache of every chapter read so far). Other books come in
through a positional EPUB argument or environment variables. DRY_RUN=1
prints the resolved configuration and exits before any synthesis.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "book-daily.sh"

KNOBS = (
    "EPUB", "BOOK", "APPROACH", "FIRST_CH", "LAST_CH", "TTS_MODEL",
    "TTS_VOICE", "DAILY_BUDGET", "MIN_USEFUL", "BATCH_CHARS", "WORK_DIR",
    "OUT_EPUB", "LEDGER", "BOOK_DAILY_LOG",
    # generic names the script must ignore
    "MODEL", "VOICE", "WORK", "OUT", "LOG",
)

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _run(*args: str, **env: str) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in KNOBS}
    base.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args], env=base, capture_output=True,
        text=True, timeout=20, check=False,
    )


def _config(*args: str, **env: str) -> dict:
    r = _run(*args, DRY_RUN="1", **env)
    assert r.returncode == 0, r.stderr
    return dict(line.split("=", 1) for line in r.stdout.splitlines())


def test_defaults_are_the_running_book():
    cfg = _config()
    assert cfg["EPUB"] == "out/archive/saramago.epub"
    assert cfg["APPROACH"] == "prepared"
    assert cfg["FIRST_CH"] == "3"
    assert cfg["LAST_CH"] == "21"
    assert cfg["MODEL"] == "gemini-3.8-flash-lite-tts"
    assert cfg["VOICE"] == "Rami"
    assert cfg["DAILY_BUDGET"] == "90"
    assert cfg["WORK"] == "out/readings/prepared-gemini38/work"
    assert cfg["OUT"] == "out/readings/prepared-gemini38/readalong-saramago-full.epub"
    assert cfg["LOG"] == "out/book-daily.log"


def test_scheduled_command_keeps_legacy_paths():
    # The exact shape the dispatcher runs: APPROACH=prepared, no args.
    cfg = _config(APPROACH="prepared")
    assert cfg["WORK"] == "out/readings/prepared-gemini38/work"


def test_positional_epub_gets_its_own_dirs():
    cfg = _config("books/other.epub", LAST_CH="9")
    assert cfg["EPUB"] == "books/other.epub"
    assert cfg["BOOK"] == "other"
    assert cfg["FIRST_CH"] == "0"
    assert cfg["LAST_CH"] == "9"
    assert cfg["WORK"] == "out/readings/other/prepared-gemini38/work"
    assert cfg["OUT"] == "out/readings/other/prepared-gemini38/readalong-other-full.epub"


def test_env_epub_and_overrides():
    cfg = _config(
        EPUB="books/x.epub", BOOK="mybook", FIRST_CH="2", LAST_CH="5",
        TTS_MODEL="gemini-3.8-flash-tts", TTS_VOICE="Kore", APPROACH="loyal",
    )
    assert cfg["EPUB"] == "books/x.epub"
    assert cfg["WORK"] == "out/readings/mybook/loyal-gemini38/work"
    assert cfg["MODEL"] == "gemini-3.8-flash-tts"
    assert cfg["VOICE"] == "Kore"
    assert (cfg["FIRST_CH"], cfg["LAST_CH"]) == ("2", "5")


def test_positional_argument_wins_over_env():
    cfg = _config("books/arg.epub", EPUB="books/env.epub", LAST_CH="1")
    assert cfg["EPUB"] == "books/arg.epub"


def test_generic_env_names_are_ignored():
    cfg = _config(MODEL="evil", OUT="/tmp/evil.epub", LOG="/tmp/evil.log", WORK="/tmp/w")
    assert cfg["MODEL"] == "gemini-3.8-flash-lite-tts"
    assert cfg["OUT"].startswith("out/readings/")
    assert cfg["LOG"] == "out/book-daily.log"
    assert cfg["WORK"] == "out/readings/prepared-gemini38/work"


def test_other_book_requires_last_chapter():
    r = _run("books/other.epub", DRY_RUN="1")
    assert r.returncode == 2
    assert "LAST_CH is required" in r.stderr


def test_prep_llm_defaults_to_claude_and_is_overridable():
    assert _config()["PREP_LLM"] == "claude-sonnet-5-5"
    assert _config(PREP_LLM="mistral-large-latest")["PREP_LLM"] == \
        "mistral-large-latest"
