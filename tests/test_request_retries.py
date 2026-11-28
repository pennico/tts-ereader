"""Request handling (review C221, findings 10-11): a batch blocked by the
recitation filter is halved instead of re-bought line by line, and a
request that got no answer (timeout, reset) is retried, not fatal.
"""
from __future__ import annotations

import pytest
from test_request_efficiency import (
    _batch_pcm,
    _FakeEngine,
    _filter_error,
    _speech_pcm,
    _wav,
)

import gemini_readaloud as gr


@pytest.mark.asyncio
async def test_blocked_batch_is_halved(tmp_path):
    turns = [("Rami", f"Riga numero {i}.") for i in range(4)]
    eng = _FakeEngine([
        _filter_error(),                      # 4 lines: blocked
        _wav(_batch_pcm([1.0, 1.0])),         # lines 0-1
        _wav(_batch_pcm([1.0, 1.0])),         # lines 2-3
    ])
    paths = await gr.synth_batch(eng, turns, tmp_path, pace=0,
                                 para_ends=[False, True, False, True])
    assert [c[0] for c in eng.calls] == ["batch", "batch", "batch"]
    assert [len(c[1]) for c in eng.calls] == [4, 2, 2]
    # Each half keeps its own separators.
    assert eng.separators == [[" ", "\n\n", " "], [" "], [" "]]
    assert len(paths) == 4


@pytest.mark.asyncio
async def test_blocked_half_halves_again_down_to_lines(tmp_path):
    turns = [("Rami", f"Riga {i}.") for i in range(3)]
    eng = _FakeEngine([
        _filter_error(),                 # 3 lines
        _wav(_speech_pcm(1.0)),          # line 0 alone (synth_line)
        _filter_error(),                 # lines 1-2
        _wav(_speech_pcm(1.0)),          # line 1
        _wav(_speech_pcm(1.0)),          # line 2
    ])
    paths = await gr.synth_batch(eng, turns, tmp_path, pace=0)
    assert [c[0] for c in eng.calls] == ["batch", "line", "batch", "line", "line"]
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_network_error_is_retried(monkeypatch):
    from app.engines.base import EngineError

    waits = []

    async def _sleep(s):
        waits.append(s)

    monkeypatch.setattr(gr.asyncio, "sleep", _sleep)
    calls = {"n": 0}

    async def _request():
        calls["n"] += 1
        if calls["n"] == 1:
            raise EngineError("Gemini request failed: ReadTimeout('')")
        return "ok"

    assert await gr._request_with_quota_retries(_request) == "ok"
    assert calls["n"] == 2 and waits == [60]


def test_other_engine_errors_are_not_retried():
    from app.engines.base import EngineError
    assert gr._transient_code(EngineError("Gemini API error 400: bad")) is None
    assert gr._transient_code(
        EngineError("Gemini request failed: ConnectError")) == "network"
