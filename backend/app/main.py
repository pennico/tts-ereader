"""FastAPI entry point: CORS, routers, health check (ARCHITECTURE_v1 §2.1)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import library, prepare, reader, tts
from app.core.database import init_db

FRONTEND_DIST = Path(os.environ.get("TTSEREADER_FRONTEND_DIST", "frontend/dist"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
        return {"status": "ok"}

    # Serve the built frontend when it exists (local-first single-server
    # deployment, ARCHITECTURE_v1 §6). Registered last so API routes (including
    # /api/health above) take precedence; html=True gives the SPA fallback.
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
