"""Shared test setup: isolated data dir, database, app client, fixture EPUBs."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))  # shared/ (M3 preparation + voice cast)
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))

from make_fixture_epub import make_all_fixtures  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.database import reset_engine_for_tests  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at a per-test data dir (no repo pollution)."""
    test_settings = Settings(data_dir=tmp_path / "data")
    test_settings.ensure_dirs()
    return test_settings


@pytest.fixture()
def client(settings: Settings):
    """TestClient wired to the isolated data dir."""
    import os

    os.environ["TTSEREADER_DATA_DIR"] = str(settings.data_dir)
    reset_engine_for_tests()

    from fastapi.testclient import TestClient

    from app.core.database import init_db
    from app.main import create_app

    init_db(settings)
    app = create_app()
    # The startup hook calls init_db() again; the env var above points the
    # default settings at the same per-test data dir, so it is a no-op.
    with TestClient(app) as c:
        yield c

    reset_engine_for_tests()
    del os.environ["TTSEREADER_DATA_DIR"]


@pytest.fixture(scope="session")
def fixture_epubs(tmp_path_factory) -> dict:
    """All synthetic EPUB fixtures, keyed by fixture name."""
    out_dir = tmp_path_factory.mktemp("epubs")
    paths = make_all_fixtures(out_dir)
    return {Path(p).stem: Path(p) for p in paths}
