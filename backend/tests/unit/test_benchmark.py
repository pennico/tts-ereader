"""Unit tests for the benchmark harness (M4, ARCHITECTURE_v1 §5.6).

Runs benchmark_tts against the MockTTSEngine — no network, no API keys.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import benchmark_tts
from app.engines import factory
from tests.mock_engine import MockTTSEngine


@pytest.fixture()
def registry():
    """Snapshot the registry so the mock can be registered safely."""
    saved = dict(factory._REGISTRY)
    yield
    factory._REGISTRY.clear()
    factory._REGISTRY.update(saved)


def test_parse_voices():
    assert benchmark_tts.parse_voices(None) == {}
    assert benchmark_tts.parse_voices("") == {}
    parsed = benchmark_tts.parse_voices("gemini=Charon, Kore; edge=da-DK-JeppeNeural")
    assert parsed == {
        "gemini": ["Charon", "Kore"],
        "edge": ["da-DK-JeppeNeural"],
    }


def test_parse_voices_rejects_garbage():
    with pytest.raises(SystemExit):
        benchmark_tts.parse_voices("gemini-Charon")


@pytest.mark.asyncio
async def test_run_benchmark_with_mock_engine(registry, tmp_path: Path):
    factory.register(MockTTSEngine())
    rows = await benchmark_tts.run_benchmark(
        ["mock"], {"it": "Ciao mondo, che bella giornata."}, tmp_path
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ok"
    assert row["engine"] == "mock"
    assert row["voice"] == "mock-voice"  # list_voices fallback (no defaults)
    assert row["audio_s"] > 0
    assert row["realtime_factor"] is not None and row["realtime_factor"] >= 0
    assert row["word_boundaries"] is True
    audio = tmp_path / row["audio_file"]
    assert audio.exists() and audio.read_bytes()[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_run_benchmark_reports_unavailable_and_unknown(registry, tmp_path: Path):
    rows = await benchmark_tts.run_benchmark(
        ["gemini", "nope"], {"it": "Ciao."}, tmp_path
    )
    by_engine = {r["engine"]: r for r in rows}
    # No GEMINI_API_KEY in tests -> skipped as unavailable, not a crash.
    assert by_engine["gemini"]["status"] == "unavailable"
    assert by_engine["nope"]["status"] == "unknown-engine"


@pytest.mark.asyncio
async def test_run_benchmark_voice_override_and_repeats(registry, tmp_path: Path):
    factory.register(MockTTSEngine())
    rows = await benchmark_tts.run_benchmark(
        ["mock"],
        {"da": "Hej med dig."},
        tmp_path,
        voices_override={"mock": ["custom-voice"]},
        repeats=2,
    )
    assert len(rows) == 2
    assert {r["voice"] for r in rows} == {"custom-voice"}
    assert {r["repeat"] for r in rows} == {1, 2}


@pytest.mark.asyncio
async def test_report_and_table(registry, tmp_path: Path):
    factory.register(MockTTSEngine())
    rows = await benchmark_tts.run_benchmark(["mock"], {"it": "Ciao."}, tmp_path)
    report_path = benchmark_tts.write_report(rows, tmp_path)
    saved = json.loads(report_path.read_text())
    assert saved == rows

    table = benchmark_tts.markdown_table(rows)
    assert "| Engine | Voice | Lang |" in table
    assert "mock" in table and "mock-voice" in table
    # Non-ok rows render their reason instead of measurements.
    skip_table = benchmark_tts.markdown_table([{"engine": "gemini", "status": "unavailable"}])
    assert "unavailable" in skip_table


def test_cli_main_with_mock_engine(registry, tmp_path: Path, capsys):
    factory.register(MockTTSEngine())
    out_dir = tmp_path / "bench"
    code = benchmark_tts.main(["--engines", "mock", "--samples", "it", "--out-dir", str(out_dir)])
    assert code == 0
    out = capsys.readouterr().out
    assert "mock" in out and "Report:" in out
    assert (out_dir / "benchmark_report.json").exists()
