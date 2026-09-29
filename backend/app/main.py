"""FastAPI entry point: CORS, routers, health check (ARCHITECTURE_v1 §2.1)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import library, reader
from app.core.database import init_db


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

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
