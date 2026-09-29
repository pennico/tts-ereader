"""Integration tests for the library + reader API (AC-001..AC-003, AC-005)."""
from __future__ import annotations

from pathlib import Path


def _import(client, epub_path: Path):
    with open(epub_path, "rb") as f:
        return client.post(
            "/api/books", files={"file": (epub_path.name, f, "application/epub+zip")}
        )


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data_dir_writable"] is True
    assert body["version"]
    # Engine availability is reported for monitoring (keys absent in tests).
    engines = {e["name"]: e["available"] for e in body["engines"]}
    assert "gemini" in engines and "edge" in engines


def test_import_and_list(client, fixture_epubs):
    resp = _import(client, fixture_epubs["plain_it"])
    assert resp.status_code == 200
    book = resp.json()
    assert book["title"] == "Plain Narration (IT)"
    assert book["author"] == "Fixture Author"
    assert book["chapter_count"] == 2

    resp = client.get("/api/books")
    assert resp.status_code == 200
    books = resp.json()
    assert len(books) == 1
    assert books[0]["id"] == book["id"]


def test_import_rejects_garbage(client):
    resp = client.post(
        "/api/books", files={"file": ("bad.epub", b"not a zip", "application/epub+zip")}
    )
    assert resp.status_code == 422
    assert "not a valid EPUB" in resp.json()["detail"]


def test_chapters_and_text(client, fixture_epubs):
    book_id = _import(client, fixture_epubs["plain_it"]).json()["id"]

    resp = client.get(f"/api/books/{book_id}/chapters")
    assert resp.status_code == 200
    chapters = resp.json()
    assert [c["index"] for c in chapters] == [0, 1]
    assert chapters[0]["title"] == "Chapter 1"
    assert chapters[0]["char_count"] > 0

    resp = client.get(f"/api/books/{book_id}/chapters/0")
    assert resp.status_code == 200
    chapter = resp.json()
    assert chapter["index"] == 0
    assert "La mattina scendeva lenta" in chapter["text"]

    resp = client.get(f"/api/books/{book_id}/chapters/99")
    assert resp.status_code == 404


def test_progress_roundtrip_persists(client, fixture_epubs):
    """AC-003: progress persisted per book."""
    book_id = _import(client, fixture_epubs["plain_da"]).json()["id"]

    resp = client.get(f"/api/books/{book_id}/progress")
    assert resp.status_code == 200
    assert resp.json() == {"chapter_index": 0, "position": 0.0}

    resp = client.put(
        f"/api/books/{book_id}/progress",
        json={"chapter_index": 1, "position": 0.42},
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/books/{book_id}/progress")
    assert resp.json() == {"chapter_index": 1, "position": 0.42}

    # Visible in the book listing too.
    books = client.get("/api/books").json()
    assert books[0]["progress_chapter"] == 1
    assert abs(books[0]["progress_position"] - 0.42) < 1e-9


def test_progress_validation(client, fixture_epubs):
    book_id = _import(client, fixture_epubs["plain_it"]).json()["id"]
    resp = client.put(
        f"/api/books/{book_id}/progress",
        json={"chapter_index": 0, "position": 1.5},
    )
    assert resp.status_code == 422


def test_delete_book(client, fixture_epubs):
    book_id = _import(client, fixture_epubs["plain_it"]).json()["id"]
    resp = client.delete(f"/api/books/{book_id}")
    assert resp.status_code == 200
    assert client.get("/api/books").json() == []
    assert client.get(f"/api/books/{book_id}").status_code == 404
    resp = client.delete(f"/api/books/{book_id}")
    assert resp.status_code == 404


def test_cover_endpoint(client, fixture_epubs):
    """AC-002: covers are served for books that have one, 404 otherwise."""
    with_cover = _import(client, fixture_epubs["plain_it"]).json()["id"]
    without_cover = _import(client, fixture_epubs["plain_da"]).json()["id"]

    resp = client.get(f"/api/books/{with_cover}/cover")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"

    assert client.get(f"/api/books/{without_cover}/cover").status_code == 404
    assert client.get("/api/books/999/cover").status_code == 404


def test_missing_book_404(client):
    assert client.get("/api/books/999").status_code == 404
    assert client.get("/api/books/999/chapters").status_code == 404
