"""App configuration (dependency-light: env vars + dataclass, no extra deps)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    """Runtime settings. All persisted state lives under data_dir."""

    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tts_ereader.db"

    @property
    def epubs_dir(self) -> Path:
        return self.data_dir / "epubs"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.epubs_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Settings from the TTSEREADER_DATA_DIR env var (default: ./data)."""
    return Settings(data_dir=Path(os.environ.get("TTSEREADER_DATA_DIR", "data")))
