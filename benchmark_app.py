#!/usr/bin/env python3
"""App-side performance harness (QA, ARCHITECTURE_v1 §5.6, AC-601/602/605).

Measures the P0 performance criteria that do not need live TTS keys, against
the real FastAPI app (in-process TestClient) populated with synthetic EPUB
fixtures:

- AC-601  library load  < 2s for 100 books   (GET /api/books)
- AC-602  chapter load  < 1s                  (GET /api/books/{id}/chapters/{i})
- AC-605  tap-to-audio  < 50ms                (POST /api/tts/synthesize,
          cache hit — the backend portion of the tap-to-play path; the
          browser decode/start half is measured on the homelab, see
          docs/QA_v1.md)

Synthesis runs on the MockTTSEngine (registered as "mock"), so no network
and no API keys are needed. AC-603/AC-604 (realtime synthesis budgets)
need live engines and are covered by benchmark_tts.py instead.

Usage:
    python3 benchmark_app.py                    # 100 books, 5 repeats
    python3 benchmark_app.py --books 20 --repeats 3

Output: a markdown table on stdout (recorded in docs/QA_v1.md).
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))

from app.core.config import Settings  # noqa: E402
from app.core.database import init_db, reset_engine_for_tests  # noqa: E402
from app.engines import factory  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from make_fixture_epub import make_plain_narration_epub  # noqa: E402
from tests.mock_engine import MockTTSEngine  # noqa: E402

# Acceptance budgets (SPEC_v1 §3.7), in milliseconds.
BUDGET_MS = {"AC-601": 2000.0, "AC-602": 1000.0, "AC-605": 50.0}

# Chapter text used for the AC-605 cache-hit measurement (synthetic).
TAP_TEXT = "Ciao mondo, che bella giornata per leggere un libro insieme."


@contextmanager
def app_client(data_dir: Path):
    """App + TestClient wired to an isolated data dir, mock engine registered."""
    os.environ["TTSEREADER_DATA_DIR"] = str(data_dir)
    settings = Settings(data_dir=data_dir)
    settings.ensure_dirs()
    reset_engine_for_tests()
    init_db(settings)
    saved_registry = dict(factory._REGISTRY)
    factory.register(MockTTSEngine())
    app = create_app()
    with TestClient(app) as client:
        yield client
    factory._REGISTRY.clear()
    factory._REGISTRY.update(saved_registry)
    reset_engine_for_tests()
    del os.environ["TTSEREADER_DATA_DIR"]


def _timed_ms(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000.0


def run_measurements(books: int, repeats: int, work_dir: Path) -> list[dict]:
    """Import `books` fixture EPUBs, then time each P0 path; returns result rows."""
    with app_client(work_dir / "data") as client:
        epub_path = make_plain_narration_epub("it", 400, work_dir)
        epub_bytes = epub_path.read_bytes()

        for i in range(books):
            r = client.post(
                "/api/books",
                files={"file": (f"fixture-{i:03d}.epub", epub_bytes, "application/epub+zip")},
            )
            r.raise_for_status()

        def list_library():
            r = client.get("/api/books")
            r.raise_for_status()
            assert len(r.json()) == books

        def load_chapter():
            r = client.get("/api/books/1/chapters/0")
            r.raise_for_status()

        body = {"text": TAP_TEXT, "engine": "mock", "voice": "mock-voice"}
        first = client.post("/api/tts/synthesize", json=body)  # populate the cache
        first.raise_for_status()
        assert first.json()["cached"] is False

        def tap_to_audio_cached():
            r = client.post("/api/tts/synthesize", json=body)
            r.raise_for_status()
            assert r.json()["cached"] is True

        paths = [
            ("AC-601", f"Library load (list {books} books)", list_library),
            ("AC-602", "Chapter load (text endpoint)", load_chapter),
            ("AC-605", "Tap-to-audio, cache hit (synthesize endpoint)", tap_to_audio_cached),
        ]
        rows = []
        for ac_id, label, fn in paths:
            samples = [_timed_ms(fn) for _ in range(repeats)]
            rows.append(
                {
                    "ac": ac_id,
                    "measurement": label,
                    "median_ms": statistics.median(samples),
                    "min_ms": min(samples),
                    "max_ms": max(samples),
                    "repeats": repeats,
                }
            )
    return rows


def print_table(rows: list[dict]) -> None:
    print("| AC | Measurement | Budget | Median | Min | Max | Result |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        budget = BUDGET_MS[row["ac"]]
        ok = row["median_ms"] <= budget
        print(
            "| {} | {} | <{:.0f} ms | {:.1f} ms | {:.1f} ms | {:.1f} ms | {} |".format(
                row["ac"],
                row["measurement"],
                budget,
                row["median_ms"],
                row["min_ms"],
                row["max_ms"],
                "PASS" if ok else "FAIL",
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--books", type=int, default=100, help="library size for AC-601 (default 100)")
    parser.add_argument("--repeats", type=int, default=5, help="timed repeats per path (default 5)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="benchmark_app_") as tmp:
        rows = run_measurements(args.books, args.repeats, Path(tmp))
    print_table(rows)
    return 0 if all(r["median_ms"] <= BUDGET_MS[r["ac"]] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
