# Developer guide v1

**Status:** Role C (Implementation) deliverable, milestone M4
**Consumes:** docs/ARCHITECTURE_v1.md

## Layout

```
backend/app/        FastAPI: api/ (library, reader, prepare, tts), engines/
                    (base, gemini, edge_tts, factory), services/, core/
frontend/src/       Svelte 4 + Vite + TS: pages/, components/, services/,
                    stores/, utils/
shared/             text_preparation + voice_cast, shared by v0 CLIs and the app
tests/              v0 unit tests + synthetic EPUB fixture generator
backend/tests/      v1 unit + integration tests (pytest)
benchmark_tts.py    TTS benchmark harness (owner-run, real keys)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # add keys if you have them; tests run without

cd frontend && npm ci
```

## Running

```bash
# backend on :8000 (serves the built SPA from frontend/dist when present)
cd backend && python3 -m uvicorn app.main:app --reload

# frontend dev server on :5173 (proxies /api to :8000)
cd frontend && npm run dev

# production-style single server
cd frontend && npm run build
cd .. && python3 -m uvicorn app.main:app --app-dir backend
```

## Tests

```bash
python3 -m pytest backend/tests -q          # v1 unit + integration (<5s)
python3 -m unittest discover tests          # v0 CLI tests
cd frontend && npm test && npm run check     # Vitest + svelte-check
```

The v1 suite needs no API keys: engines are exercised through
`MockTTSEngine` (`backend/tests/mock_engine.py`), EPUBs through the
synthetic fixtures (`tests/fixtures/make_fixture_epub.py`). Live synthesis
never runs in the cloud sandbox (no keys, 30s command limit).

## TTS engines

All synthesis goes through the `TTSEngine` interface
(`backend/app/engines/base.py`); the app never calls an engine directly.
To add an engine:

1. Subclass `TTSEngine` in `backend/app/engines/` (implement `name`,
   `display_name`, `list_voices`, `synthesize`; override `is_available` if
   it needs a key or optional dependency).
2. Register it in `_default_registry()` (`backend/app/engines/factory.py`).
3. Add unit tests with a mocked HTTP client (see `test_engines.py` for the
   Gemini/edge patterns).

Fallback is automatic: the requested engine, then Gemini, then edge-tts
(`factory.fallback_chain`).

## Benchmark harness

`benchmark_tts.py` compares engines on the same Italian/Danish passages:
it records one audio file per engine×voice×language for A/B listening and
reports wall-time per second of audio against the acceptance budgets
(edge-tts < 2x, Gemini < 1.5x — AC-603/AC-604). Run it locally with real
keys:

```bash
python3 benchmark_tts.py                       # all engines, it+da
python3 benchmark_tts.py --engines gemini --voices 'gemini=Charon,Kore'
python3 benchmark_tts.py --repeats 3            # timing stability
```

Output lands in `out/benchmark/` (gitignored): the audio files,
`benchmark_report.json`, and a markdown table on stdout. Exit code 1 if
any combination exceeds its budget. In the sandbox the harness is covered
by `backend/tests/unit/test_benchmark.py` against the mock engine.

## Docker

See `docs/DEPLOYMENT.md`. The image is a multi-stage build (frontend bundle
→ `python:3.11-slim` + ffmpeg); `docker compose up -d --build` is the
homelab runbook. Note the runtime image includes `shared/` — the prepare
endpoints import `shared.text_preparation` at runtime.

## Conventions

- Python: stdlib-first, argparse CLIs (`--list-chapters`, `--slice`),
  `from __future__ import annotations`, no new heavy dependencies without
  justification.
- The v0 CLIs (`poc_reader.py`, `edge_reader.py`, `epub_*.py`) must keep
  working; their surface is pinned by `tests/test_v0_compat.py`.
- Never commit `.env`, API keys, audio files, or real books
  (`samples/*.epub` is gitignored; use the fixture generator).
