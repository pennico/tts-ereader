# Deployment v1 — self-hosted Docker

**Status:** Role C (Implementation) deliverable, milestone M4
**Consumes:** docs/ARCHITECTURE_v1.md §6, PLAN_v1_reader.md

The app ships as a single container: FastAPI serves the API and the built
Svelte SPA on port 8000, with all persisted state (SQLite DB, EPUBs, covers,
audio cache) under one data directory mounted as a volume.

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build: `node:20-slim` builds the frontend, `python:3.11-slim` + ffmpeg runs the backend |
| `docker-compose.yml` | Self-hosted service: port 8000, `./data` bind mount, `.env` passthrough, healthcheck, `restart: unless-stopped` |
| `.env.example` | Template for API keys and settings — copy to `.env`, never commit it |
| `.dockerignore` | Keeps the image small and secrets out |

## First deployment (self-hosted server)

```bash
# on the self-hosted server, in the repo checkout
cp .env.example .env
$EDITOR .env          # fill in GEMINI_API_KEY and MISTRAL_API_KEY

docker compose up -d --build
docker compose ps     # wait for "healthy"
```

Open `http://<server>:8000`. The container healthcheck polls
`GET /api/health` every 30s.

## Health monitoring

`GET /api/health` always answers 200 while the process is up and reports
degraded states in the body:

```json
{
  "status": "ok",
  "version": "1.0.0-dev",
  "data_dir": "/data",
  "data_dir_writable": true,
  "default_engine": "gemini",
  "engines": [{"name": "gemini", "available": true}, {"name": "edge", "available": true}]
}
```

- `status: "degraded"` — the data dir is not writable (check the volume mount).
- `engines[].available` — whether each engine has its API key / dependency.
  With no `GEMINI_API_KEY`, synthesis automatically falls back to edge-tts.

Logs go to stdout (`docker compose logs -f tts-ereader`); startup lines log
the data dir and frontend dist path.

## Updates

```bash
git pull
docker compose up -d --build
```

## Backups

Everything that matters is in `./data` (DB, imported EPUBs, covers, audio
cache). Back up that directory; the audio cache is regenerable, the DB and
`data/epubs` are not:

```bash
tar czf backup.tgz data/tts_ereader.db data/epubs data/covers
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini TTS (primary engine). Empty → edge-tts fallback |
| `MISTRAL_API_KEY` | — | LLM text preparation (voice casts). Empty → single-voice narration |
| `TTSEREADER_DATA_DIR` | `/data` in the container | Root of all persisted state |
| `TTSEREADER_DEFAULT_ENGINE` | `gemini` | Engine used when a book has no preference |
| `TTSEREADER_FRONTEND_DIST` | `/app/frontend/dist` | Where the built SPA is served from |

## Verified / not verified

- Backend health endpoint, engine fallback, and the compose/Dockerfile
  wiring are covered by the test suite (`python3 -m pytest backend/tests -q`).
- The image itself was **not built in the cloud sandbox** (no Docker daemon,
  30s command limit). First `docker compose up -d --build` on the target server is
  the owner's smoke test; see the PR handoff for the checklist.
