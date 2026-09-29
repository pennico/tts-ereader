# Multi-stage build (ARCHITECTURE_v1 §6.1): frontend bundle, then slim runtime.
# The single container serves the API and the built SPA on :8000.

# ── Stage 1: build the frontend ──────────────────────────────────────────────
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim
# ffmpeg: pydub audio normalization (edge-tts MP3 -> WAV) and concatenation.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# shared/: the preparation pipeline imports shared.text_preparation at
# runtime (llm_service bootstraps /app onto sys.path) — without it the
# prepare/voice-cast endpoints fail in the container.
COPY shared/ ./shared/
COPY --from=frontend-builder /build/dist ./frontend/dist

# All persisted state (SQLite DB, EPUBs, covers, audio cache) under /data,
# mounted as a volume by docker-compose.
ENV TTSEREADER_DATA_DIR=/data \
    TTSEREADER_FRONTEND_DIST=/app/frontend/dist \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=4)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend"]
