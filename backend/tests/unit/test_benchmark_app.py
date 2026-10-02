"""Unit tests for the app-side performance harness (QA, AC-601/602/605).

Runs benchmark_app against the MockTTSEngine — no network, no API keys.
"""
from __future__ import annotations

from pathlib import Path

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
