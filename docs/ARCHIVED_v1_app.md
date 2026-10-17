# Archived: v1 reader app

> **Decommissioned 2026-10-13 (issue #39).** The v1 web app is retired and
> receives no further development. The owner reads the read-along EPUBs in
> Readest instead. The code (`backend/`, `frontend/`, `Dockerfile`,
> `docker-compose.yml`) is kept for a possible revival and its tests still
> run in CI. This page is the README text the app had while it was live,
> moved here unchanged apart from headings.
>
> If you deploy it anyway: the app has no authentication, the image runs as
> root, and `docker-compose.yml` publishes port 8000 on all interfaces. Bind
> it to `127.0.0.1:8000:8000` and put it behind a reverse proxy with auth.

Delivery record: `PLAN_v1_reader.md`, `docs/SPEC_v1.md`,
`docs/ARCHITECTURE_v1.md`, `ROADMAP.md` (fully ticked). Test plan and
recorded results: `docs/QA_v1.md`. Runbook: `docs/DEPLOYMENT.md`. Never run
open items: the live-key benchmarks (AC-603/604) and the self-hosted manual
checklist in `docs/QA_v1.md` §1.2.

## Milestones (M1–M4: library + reader, TTS + read-along, voice tuning + LLM preparation, Docker + benchmark + docs)

The v1 app is in `backend/` (FastAPI + SQLite via SQLModel) and `frontend/`
(Svelte 4 + Vite + TypeScript), per `docs/ARCHITECTURE_v1.md`. M1 delivers:

- EPUB import with metadata, cover extraction, and spine-ordered chapter
  indexing; library list/get/delete; per-book progress persistence.
- Library UI: import via file picker or drag & drop, cover cards with
  progress bars, remove.
- Reader UI: chapter navigation, fonts (family, size 8–32pt, weight,
  line-height 1.0–2.5), themes (light/dark/sepia/custom colors), continuous
  scroll and paginated modes with toggle, auto-advance/auto-scroll with
  configurable speed, progress saved per book and restored on open,
  lang-aware hyphenation for European typography.

M2 adds TTS and the voice-by-progression read-along:

- Pluggable `TTSEngine` interface (`backend/app/engines/`): Gemini TTS
  adapter (primary, REST, PCM wrapped as WAV) and edge-tts adapter (free
  fallback, word-boundary timestamps, MP3 normalized to WAV via pydub/ffmpeg
  when available). Engines are looked up through a factory with automatic
  fallback (requested engine first, then Gemini, then edge-tts).
- TTS API: `GET /api/tts/engines`, `GET /api/tts/engines/{name}/voices`,
  `POST /api/tts/synthesize`, `POST /api/tts/synthesize-batch`. All synthesis
  is cached on disk under `data/audio_cache/` keyed by engine+voice+params+
  text hash, so re-reading is instant.
- Reader read-along: the chapter is split into sentences (Italian/Danish
  abbreviations, quotes, dialogue dashes handled); tapping any sentence
  synthesizes a window from there and reads aloud ("tap-to-read"); the spoken
  sentence is highlighted and the view follows the voice (scroll or page
  turn); manual scroll/page-turn repositions the voice; when the voice
  finishes the chapter it auto-advances to the next one (toggleable). Playback
  rate 0.5x–2x is applied client-side via Web Audio `playbackRate`.
- Per-book voice settings (engine, voice, rate, auto-advance) in the reader's
  Voice panel, persisted to localStorage per book.

M3 adds voice tuning and the LLM preparation pipeline:

- Voice panel: engine + voice selection, rate 0.5x–2x (client-side), pitch
  -20..+20 (baked into synthesis), a "Test this voice" button, and a per-book
  voice cast. The cast is seeded from engine+language defaults (Italian
  edge-tts: Giuseppe/Vivienne/Emma/Andrew; Danish edge-tts: Jeppe/Christel;
  Gemini: Charon/Kore/Leda/Puck) and every role can be overridden per book;
  settings persist per book in localStorage.
- With the cast enabled, the chapter is prepared through the same Mistral
  pipeline as the v0 CLIs (`shared/text_preparation.py`: clean +
  repunctuate + speaker tagging, with Italian (Saramago), Danish
  (Adler-Olsen), and generic prompts), cached on disk per book+chapter so
  it is never re-billed, and the prepared lines become the display and
  playback unit: each character reads with their own voice, speaker labels
  are shown inline, and tap-to-read/highlight/follow-voice work per line.
- Preparation API: `POST /api/books/{id}/chapters/{n}/prepare` (LLM + cast
  resolution; 503 without `MISTRAL_API_KEY`), `GET .../prepared` (cache
  only), `GET /api/tts/cast-defaults`; `synthesize-batch` accepts per-text
  voices.
- The v0 CLIs now import preparation + cast logic from `shared/`; their
  surface and Italian cast output are pinned by `tests/test_v0_compat.py`.

Gemini TTS needs `GEMINI_API_KEY` in `.env`; without it the engine shows as
unavailable and synthesis falls back to edge-tts automatically. LLM
preparation needs `MISTRAL_API_KEY`; without it the cast toggle reports the
error and the reader falls back to plain single-voice narration. Live Gemini
synthesis was verified by the owner on 2026-09-19 for Italian and Danish
(short texts, voice Kore) and on 2026-09-29 for English (Guns, Germs, and
Steel chapter 1 opening, ~1,100 chars, voices Kore and Charon); the
sandbox only exercises engines through mocks plus free edge-tts smoke tests.

Packaging note (issue #39): httpx is a runtime dependency of the Gemini
engine and is pinned in `requirements.txt`; it was previously dev-only,
so the packaged image failed at synthesis time with `ModuleNotFoundError`
while `/api/health` still reported gemini available. `is_available()` now
checks the import too.

Known limitation (seen live 2026-09-29): `GeminiTTSEngine`'s httpx client
uses a 30 s read timeout, which is too tight for requests beyond roughly
1,000 characters — the same ~1,100-char sample succeeded with Kore but
timed out twice with Charon until retried with a 120 s client (the engine
accepts an injectable `client`). Batch generation should chunk to short
lines (the prepared-lines pipeline already does) or raise the timeout.
Transient malformed responses (seen live 2026-10-01, issue #15): Gemini
sometimes answers 200 with a candidate that has no `content`; re-sending
the identical request succeeds. `GeminiTTSEngine.synthesize()` retries up
to 2 extra times (2 s / 4 s backoff, configurable via `retry_delays`) and
logs the discarded response shape (finishReason, candidate keys,
promptFeedback) at WARNING on the `tts_ereader.gemini` logger before each
retry, so incidents are diagnosable.
Gemini TTS on an AI Studio key has a hard per-day request quota
(observed limit: 100 requests/day per model, 2026-10-06; earlier
observed ~10/day — the number has changed before) plus a small
per-minute bucket — a full book at line granularity needs the
cache-resume across days; use `gemini_readaloud.py`'s cache-resume
for quota-limited slices (see above).

```bash
pip3 install -r requirements.txt -r requirements-dev.txt

# Run the backend test suite (unit + integration, <1s)
python3 -m pytest backend/tests -q

# Generate synthetic test EPUBs (never commit real books)
python3 tests/fixtures/make_fixture_epub.py --out-dir /tmp/epubs

# Development: backend on :8000, frontend dev server on :5173 (proxies /api)
cd backend && python3 -m uvicorn app.main:app --reload
cd frontend && npm install && npm run dev

# Frontend unit tests (Vitest) and type check
cd frontend && npm test && npm run check

# Production-style single server: build the frontend, then run the backend;
# it serves frontend/dist at http://localhost:8000 (data lives in ./data
# or $TTSEREADER_DATA_DIR)
cd frontend && npm run build
cd .. && python3 -m uvicorn app.main:app --app-dir backend
```

M4 makes it deployable and benchmarkable:

- Docker deployment for a self-hosted server: multi-stage `Dockerfile` (frontend
  bundle → `python:3.11-slim` + ffmpeg runtime) and `docker-compose.yml`
  with a single `./data` bind mount for all persisted state, `.env`
  passthrough, healthcheck, and `restart: unless-stopped`. Runbook:
  `docs/DEPLOYMENT.md`.
- Enriched `GET /api/health`: version, data-dir writability, default
  engine, and per-engine availability — always 200 while the process is
  up, degraded states in the body.
- Benchmark harness (`benchmark_tts.py`, owner-run with real keys): the
  same Italian/Danish passages through every engine and voice, one audio
  file per combination for A/B listening, and wall-time vs audio duration
  against the acceptance budgets (edge-tts < 2x, Gemini < 1.5x). Covered
  in the sandbox by unit tests against the mock engine.
- Resource profiling harness (`benchmark_profile.py`): peak RSS under 10
  concurrent TTS requests (AC-606) and mean CPU during read-along-paced
  background synthesis (AC-607), against the in-process app with the
  mock engine; results in `docs/QA_v1.md` §3.6.
- Offline indicator in the app shell (red banner when the server is
  unreachable).
- Docs: `docs/DEPLOYMENT.md` (self-hosting runbook), `docs/USER_GUIDE.md`,
  `docs/DEVELOPER_GUIDE.md`.

The Docker image itself was not built in the cloud sandbox (no Docker
daemon, 30s command limit) — the first `docker compose up -d --build` on
the target server is the owner's smoke test.
