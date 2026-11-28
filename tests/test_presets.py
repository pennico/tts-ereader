"""Approach-preset selector tests (issue #26).

--preset expands to the underlying --lines-per-request so choosing an
approach is one flag; the expansion must be printed in the run log and
an explicit --lines-per-request must win over the preset. Mocked only —
no network, no API key, no 3.8 spend.
"""
from __future__ import annotations

import subprocess
import sys
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import gemini_readaloud as gr  # noqa: E402


def _args(preset=None, lines_per_request=None):
    return Namespace(preset=preset, lines_per_request=lines_per_request)


def test_presets_are_the_documented_mapping():
    assert gr.PRESETS == {"quality": 1, "balanced": 10, "fast": 20}


def test_preset_expands_to_lines_per_request():
    for name, npr in gr.PRESETS.items():
        args = _args(preset=name)
        line = gr.apply_preset(args)
        assert args.lines_per_request == npr
        assert line == f"preset: {name} -> --lines-per-request {npr}"


def test_no_preset_keeps_owner_auto_sizing_default():
    # Without a preset nothing is touched: the default is the owner's
    # --daily-requests auto-sizing (2026-10-07), so lines_per_request
    # stays None and plan_batch_counts sizes from the daily budget.
    args = _args()
    assert gr.apply_preset(args) is None
    assert args.lines_per_request is None


def test_explicit_lines_per_request_wins_over_preset():
    args = _args(preset="balanced", lines_per_request=3)
    line = gr.apply_preset(args)
    assert args.lines_per_request == 3
    assert line == "preset: balanced -> --lines-per-request 3"


def test_preset_expansion_printed_in_run_log(capsys):
    # The expansion must reach the run log before any work starts.
    args = _args(preset="fast")
    print(gr.apply_preset(args), flush=True)
    assert "preset: fast -> --lines-per-request 20" in capsys.readouterr().out


def test_help_surfaces_presets_and_supported_models():
    # --help is the model/approach documentation for newcomers: it must
    # list the preset choices and the supported models without any key.
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "gemini_readaloud.py"), "--help"],
        capture_output=True, text=True, check=True, timeout=20)
    for needle in ("--preset", "quality", "balanced", "fast",
                   "gemini-3.8-flash-lite-tts", "--lines-per-request"):
        assert needle in out.stdout
