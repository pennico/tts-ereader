"""Quota ledger: persistent per-run record of API requests and tokens.

AGENTIC_WORK_STANDARDS: every run that spends quota updates the ledger.
gemini_readaloud appends one entry per run (issue #25); wrappers read the
day totals to report spend in notifications.

Ledger format (JSON, append-only list of run entries):

    {"runs": [
        {"date": "2026-10-06", "model": "gemini-3.8-flash-tts",
         "run_id": "2026-10-06T02:30:01", "requests": 12, "tokens": 8451}
    ]}
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.exists():
        return {"runs": []}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"runs": []}
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        return {"runs": []}
    return data


def add_entry(
    ledger_path,
    *,
    model: str,
    run_id: str,
    requests: int,
    tokens: int,
    date: str | None = None,
) -> dict:
    """Append one run entry; returns the entry written."""
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": date or time.strftime("%Y-%m-%d"),
        "model": model,
        "run_id": run_id,
        "requests": int(requests),
        "tokens": int(tokens),
    }
    data = _load(path)
    data["runs"].append(entry)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)
    return entry


def day_totals(ledger_path, model: str | None = None, date: str | None = None) -> dict:
    """Sum requests/tokens over one day (optionally one model)."""
    data = _load(Path(ledger_path))
    date = date or time.strftime("%Y-%m-%d")
    totals = {"requests": 0, "tokens": 0}
    for run in data["runs"]:
        if run.get("date") != date:
            continue
        if model is not None and run.get("model") != model:
            continue
        totals["requests"] += run.get("requests", 0)
        totals["tokens"] += run.get("tokens", 0)
    return totals
