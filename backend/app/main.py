"""FastAPI entry point: CORS, routers, health check (ARCHITECTURE_v1 §2.1)."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import library, prepare, reader, tts
from app.core.config import get_settings
from app.core.database import init_db
from app.engines import factory

FRONTEND_DIST = Path(os.environ.get("TTSEREADER_FRONTEND_DIST", "frontend/dist"))

logger = logging.getLogger("tts_ereader")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    logger.info("started: data_dir=%s frontend_dist=%s", settings.data_dir, FRONTEND_DIST)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="tts-ereader", version="1.0.0-dev", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # local-first app; tighten for homelab exposure
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(library.router)
    app.include_router(reader.router)
    app.include_router(prepare.router)
    app.include_router(tts.router)

    @app.get("/api/health")
    def health():
        """Liveness + readiness for the Docker healthcheck and homelab monitoring.

        Reports the data dir (must be writable — it holds the DB and caches)
        and which TTS engines are usable with the configured keys. Always 200
        while the process is up: "degraded" (unwritable data dir, missing API
        keys) is reported in the body for monitoring, not a crash.
        """
        settings = get_settings()
        try:
            settings.ensure_dirs()
            writable = os.access(settings.data_dir, os.W_OK)
        except OSError:
            writable = False
        engines = [
            {"name": e.name, "available": e.is_available()}
            for e in factory.list_engines()
        ]
        body = {
            "status": "ok" if writable else "degraded",
            "version": app.version,
            "data_dir": str(settings.data_dir),
            "data_dir_writable": writable,
            "default_engine": settings.default_engine,
            "engines": engines,
        }
        return body

    # Serve the built frontend when it exists (local-first single-server
    # deployment, ARCHITECTURE_v1 §6). Registered last so API routes (including
    # /api/health above) take precedence; html=True gives the SPA fallback.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
