"""Unit tests for the app-side performance harness (QA, AC-601/602/605).

Runs benchmark_app against the MockTTSEngine — no network, no API keys.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import benchmark_app


def test_budgets_cover_all_measured_acs():
    rows = ["AC-601", "AC-602", "AC-605"]
    assert set(benchmark_app.BUDGET_MS) == set(rows)


def test_run_measurements_with_mock_engine(tmp_path: Path):
    rows = benchmark_app.run_measurements(books=3, repeats=1, work_dir=tmp_path)
    assert [r["ac"] for r in rows] == ["AC-601", "AC-602", "AC-605"]
    for row in rows:
        assert row["median_ms"] > 0
        assert row["median_ms"] <= benchmark_app.BUDGET_MS[row["ac"]]
        assert row["repeats"] == 1
    # The AC-601 row names the library size it measured.
    assert "3 books" in rows[0]["measurement"]


def test_run_measurements_restores_environment(tmp_path: Path):
    import os

    assert "TTSEREADER_DATA_DIR" not in os.environ
    benchmark_app.run_measurements(books=2, repeats=1, work_dir=tmp_path)
    assert "TTSEREADER_DATA_DIR" not in os.environ


def test_run_measurements_restores_preexisting_data_dir(tmp_path: Path, monkeypatch):
    import os

    monkeypatch.setenv("TTSEREADER_DATA_DIR", "/tmp/owner-data-dir")
    benchmark_app.run_measurements(books=1, repeats=1, work_dir=tmp_path)
    assert os.environ["TTSEREADER_DATA_DIR"] == "/tmp/owner-data-dir"


def test_run_measurements_cleans_up_on_failure(tmp_path: Path, monkeypatch):
    import os

    from app.engines import factory

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure inside the measurement block")

    monkeypatch.setattr(benchmark_app, "make_plain_narration_epub", boom)
    engines_before = sorted(factory._REGISTRY)
    with pytest.raises(RuntimeError):
        benchmark_app.run_measurements(books=1, repeats=1, work_dir=tmp_path)
    assert "TTSEREADER_DATA_DIR" not in os.environ
    assert sorted(factory._REGISTRY) == engines_before
    assert "mock" not in factory._REGISTRY
