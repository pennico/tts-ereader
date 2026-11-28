#!/usr/bin/env python3
"""Resource profiling harness (QA, SPEC_v1 §3.7, AC-606/AC-607).

Measures the P1 resource criteria against the real FastAPI app in-process
(httpx ASGITransport, no server), populated like benchmark_app.py:

- AC-606  memory  peak RSS < 500 MB while serving --concurrency
          simultaneous TTS requests (default 10, per the criterion).
- AC-607  cpu     mean CPU < 50% of one core over a --window seconds
          (default 5) of read-along operation: each audio chunk is
          synthesized, then the app idles for that chunk's playback
          duration before the next synthesis. A tight synthesis loop
          would peg the CPU by construction; the read-along pace is
          the workload the criterion describes ("background synthesis"
          while the user keeps reading).

Synthesis runs on the MockTTSEngine (registered as "mock"), so no network
and no API keys are needed. The numbers therefore profile the backend's
own overhead (request handling, caching, audio assembly); real engines
add their own footprint on top and can be measured the same way on the
homelab once the image is rebuilt.

CPU is reported two ways: one-core equivalent (100% = one full core; the
AC-607 budget applies to this number) and machine share (one-core
equivalent divided by the core count).

Usage:
    python3 benchmark_profile.py                     # 10 concurrent, 5s window
    python3 benchmark_profile.py --concurrency 10 --window 5

Output: a markdown table on stdout (recorded in docs/QA_v1.md).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from benchmark_app import app_client  # noqa: E402

# Acceptance budgets (SPEC_v1 §3.7).
BUDGET_MB = {"AC-606": 500.0}
BUDGET_CPU_PCT = {"AC-607": 50.0}

# Distinct text per request so every synthesis is a real (uncached) run.
TAP_TEXT = "Ciao mondo, che bella giornata per leggere un libro insieme."

try:
    CLK_TCK = os.sysconf("SC_CLK_TCK")
except (ValueError, OSError, AttributeError):  # pragma: no cover - non-Linux
    CLK_TCK = 100.0

PROC_STATUS = Path("/proc/self/status")
PROC_STAT = Path("/proc/self/stat")


def _parse_vm_rss_kb(status_text: str) -> int:
    """VmRSS in kB from /proc/<pid>/status content."""
    for line in status_text.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise ValueError("no VmRSS line in /proc status content")


def _parse_cpu_ticks(stat_text: str) -> int:
    """utime+stime clock ticks from /proc/<pid>/stat content."""
    # Field 2 (comm) can contain spaces and parens; everything after the
    # final ") " starts at field 3 (state), so utime is index 11 there.
    fields = stat_text.rsplit(") ", 1)[1].split()
    return int(fields[11]) + int(fields[12])


def rss_mb() -> float:
    """Current process RSS in MB (whole process: app runs in-process)."""
    return _parse_vm_rss_kb(PROC_STATUS.read_text()) / 1024.0


def cpu_seconds() -> float:
    """Cumulative user+system CPU seconds of the current process."""
    return _parse_cpu_ticks(PROC_STAT.read_text()) / float(CLK_TCK)


def _synthesize_body(i: int) -> dict:
    return {"text": f"{TAP_TEXT} Richiesta numero {i}.", "engine": "mock", "voice": "mock-voice"}


async def _measure_memory(client: httpx.AsyncClient, concurrency: int) -> dict:
    """Peak RSS while `concurrency` synthesize requests run simultaneously."""
    baseline_mb = rss_mb()
    peak_mb = baseline_mb

    async def sample_until(done: asyncio.Event) -> None:
        nonlocal peak_mb
        while not done.is_set():
            peak_mb = max(peak_mb, rss_mb())
            await asyncio.sleep(0.02)

    async def request(i: int) -> None:
        r = await client.post("/api/tts/synthesize", json=_synthesize_body(i))
        r.raise_for_status()

    done = asyncio.Event()
    sampler = asyncio.create_task(sample_until(done))
    await asyncio.gather(*(request(i) for i in range(concurrency)))
    done.set()
    await sampler
    return {"baseline_mb": baseline_mb, "peak_mb": peak_mb}


async def _measure_cpu(client: httpx.AsyncClient, window_s: float) -> dict:
    """Mean CPU over a window of read-along-paced background synthesis.

    Each iteration synthesizes one chunk, then idles for the chunk's
    playback duration (the natural gap while the audio plays), so the
    window models background synthesis during reading rather than a
    CPU-bound tight loop.
    """
    cpu_start = cpu_seconds()
    t_start = time.perf_counter()
    i = 0
    while True:
        remaining = window_s - (time.perf_counter() - t_start)
        if remaining <= 0:
            break
        r = await client.post("/api/tts/synthesize", json=_synthesize_body(i))
        r.raise_for_status()
        i += 1
        playback_s = min(r.json()["duration_ms"] / 1000.0,
                        window_s - (time.perf_counter() - t_start))
        if playback_s > 0:
            await asyncio.sleep(playback_s)
    cpu_delta = cpu_seconds() - cpu_start
    wall_delta = time.perf_counter() - t_start
    one_core_pct = (cpu_delta / wall_delta) * 100.0 if wall_delta > 0 else 0.0
    cores = os.cpu_count() or 1
    return {
        "requests": i,
        "wall_s": wall_delta,
        "cpu_one_core_pct": one_core_pct,
        "cpu_machine_pct": one_core_pct / cores,
        "cores": cores,
    }


def run_profile(concurrency: int, window_s: float, work_dir: Path) -> list[dict]:
    """Run both measurements; returns result rows (markdown-table data)."""
    with app_client(work_dir / "data") as test_client:
        transport = httpx.ASGITransport(app=test_client.app)
        async def run() -> tuple[dict, dict]:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                mem = await _measure_memory(client, concurrency)
                cpu = await _measure_cpu(client, window_s)
                return mem, cpu

        mem, cpu = asyncio.run(run())
    return [
        {
            "ac": "AC-606",
            "measurement": f"Peak RSS, {concurrency} concurrent synthesize requests",
            "baseline_mb": mem["baseline_mb"],
            "peak_mb": mem["peak_mb"],
        },
        {
            "ac": "AC-607",
            "measurement": f"Mean CPU, read-along-paced synthesis ({window_s:.1f} s, {cpu['requests']} chunks)",
            "cpu_one_core_pct": cpu["cpu_one_core_pct"],
            "cpu_machine_pct": cpu["cpu_machine_pct"],
            "cores": cpu["cores"],
        },
    ]


def print_table(rows: list[dict]) -> None:
    print("| AC | Measurement | Budget | Value | Result |")
    print("|---|---|---|---|---|")
    for row in rows:
        if row["ac"] == "AC-606":
            budget = BUDGET_MB["AC-606"]
            ok = row["peak_mb"] < budget
            print(
                "| AC-606 | {} | <{:.0f} MB | peak {:.0f} MB (baseline {:.0f} MB) | {} |".format(
                    row["measurement"], budget, row["peak_mb"], row["baseline_mb"],
                    "PASS" if ok else "FAIL",
                )
            )
        else:
            budget = BUDGET_CPU_PCT["AC-607"]
            ok = row["cpu_one_core_pct"] < budget
            print(
                "| AC-607 | {} | <{:.0f}% of one core | {:.1f}% of one core ({:.1f}% of {} cores) | {} |".format(
                    row["measurement"], budget, row["cpu_one_core_pct"],
                    row["cpu_machine_pct"], row["cores"],
                    "PASS" if ok else "FAIL",
                )
            )


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value!r} must be >= 1")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} must be > 0")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--concurrency", type=_positive_int, default=10,
                        help="simultaneous TTS requests for AC-606 (default 10)")
    parser.add_argument("--window", type=_positive_float, default=5.0,
                        help="continuous-synthesis seconds for AC-607 (default 5)")
    args = parser.parse_args()

    if not PROC_STATUS.exists():
        print("error: this harness reads /proc; it needs Linux (homelab or sandbox)", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="benchmark_profile_") as tmp:
        rows = run_profile(args.concurrency, args.window, Path(tmp))
    print_table(rows)
    ok = (
        rows[0]["peak_mb"] < BUDGET_MB["AC-606"]
        and rows[1]["cpu_one_core_pct"] < BUDGET_CPU_PCT["AC-607"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
