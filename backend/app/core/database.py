"""SQLite setup via SQLModel (file-based, local-first — ARCHITECTURE_v1 §1.1)."""
from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import Settings, get_settings

_engine = None


def get_engine(settings: Settings | None = None):
    global _engine
    if _engine is None:
        settings = settings or get_settings()
        settings.ensure_dirs()
        _engine = create_engine(
            f"sqlite:///{settings.db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _engine


def init_db(settings: Settings | None = None) -> None:
    """Create tables. Import models first so they are registered."""
    import app.models.book  # noqa: F401  (registers SQLModel tables)

    SQLModel.metadata.create_all(get_engine(settings))


def get_session():
    """FastAPI dependency: a session per request."""
    with Session(get_engine()) as session:
        yield session


def reset_engine_for_tests() -> None:
    """Allow tests to point the engine at a fresh database."""
    global _engine
    _engine = None
