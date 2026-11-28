"""Unit tests for the resource profiling harness (QA, AC-606/AC-607).

Runs benchmark_profile against the MockTTSEngine — no network, no API keys.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import benchmark_profile


def test_budgets_cover_all_measured_acs():
    assert set(benchmark_profile.BUDGET_MB) == {"AC-606"}
    assert set(benchmark_profile.BUDGET_CPU_PCT) == {"AC-607"}


def test_parse_vm_rss_kb():
    status = "Name:\tpython3\nVmRSS:\t  123456 kB\nVmSwap:\t  0 kB\n"
    assert benchmark_profile._parse_vm_rss_kb(status) == 123456


def test_parse_vm_rss_kb_missing_line():
    with pytest.raises(ValueError):
        benchmark_profile._parse_vm_rss_kb("Name:\tpython3\n")


def test_parse_cpu_ticks_with_spaced_comm():
    # comm may contain spaces and parens; utime/stime sit after the final ") ".
    stat = "1234 (python3 -m pytest) R 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17"
    # fields after ") ": R(0) 1 2 3 4 5 6 7 8 9 10 11 12 ... -> utime=11, stime=12
    assert benchmark_profile._parse_cpu_ticks(stat) == 11 + 12


def test_rss_and_cpu_seconds_are_positive():
    assert benchmark_profile.rss_mb() > 0
    assert benchmark_profile.cpu_seconds() >= 0


def test_run_profile_with_mock_engine(tmp_path: Path):
    rows = benchmark_profile.run_profile(concurrency=3, window_s=0.2, work_dir=tmp_path)
    assert [r["ac"] for r in rows] == ["AC-606", "AC-607"]
    mem, cpu = rows
    assert mem["peak_mb"] >= mem["baseline_mb"] > 0
    assert mem["peak_mb"] < benchmark_profile.BUDGET_MB["AC-606"]
    assert "3 concurrent" in mem["measurement"]
    assert cpu["cpu_one_core_pct"] >= 0
    assert cpu["cpu_one_core_pct"] < benchmark_profile.BUDGET_CPU_PCT["AC-607"]
    assert cpu["cores"] >= 1
    assert cpu["cpu_machine_pct"] <= cpu["cpu_one_core_pct"] or cpu["cores"] == 1
    assert "read-along-paced synthesis" in cpu["measurement"]


def test_run_profile_restores_environment(tmp_path: Path):
    import os

    assert "TTSEREADER_DATA_DIR" not in os.environ
    benchmark_profile.run_profile(concurrency=1, window_s=0.1, work_dir=tmp_path)
    assert "TTSEREADER_DATA_DIR" not in os.environ


def test_run_profile_restores_preexisting_data_dir(tmp_path: Path, monkeypatch):
    import os

    monkeypatch.setenv("TTSEREADER_DATA_DIR", "/tmp/owner-data-dir")
    benchmark_profile.run_profile(concurrency=1, window_s=0.1, work_dir=tmp_path)
    assert os.environ["TTSEREADER_DATA_DIR"] == "/tmp/owner-data-dir"


def test_run_profile_cleans_up_on_failure(tmp_path: Path, monkeypatch):
    import os

    from app.engines import factory

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure inside the measurement block")

    monkeypatch.setattr(benchmark_profile.httpx.AsyncClient, "post", boom)
    engines_before = sorted(factory._REGISTRY)
    with pytest.raises(RuntimeError):
        benchmark_profile.run_profile(concurrency=1, window_s=0.1, work_dir=tmp_path)
    assert "TTSEREADER_DATA_DIR" not in os.environ
    assert sorted(factory._REGISTRY) == engines_before
    assert "mock" not in factory._REGISTRY
