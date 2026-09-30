"""LLM text preparation for the reader (AC-401, AC-403, AC-405..AC-407).

Wraps the shared preparation pipeline (Mistral chat completions) with:
- an injectable client (tests pass a fake; no key -> LLMUnavailableError),
- chunked preparation of whole chapters,
- a disk cache of prepared lines per book+chapter, so re-opening a book or
  changing the voice cast never re-bills the LLM.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:  # pragma: no cover - import bootstrap for non-repo-root working dirs
    from shared.text_preparation import (  # noqa: E402
        chunk_text,
        detect_language,
        llm_prepare,
        normalize_language,
        parse_lines,
        split_long_narration,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from shared.text_preparation import (  # noqa: E402
        chunk_text,
        detect_language,
        llm_prepare,
        normalize_language,
        parse_lines,
        split_long_narration,
    )

LLM_MODEL_DEFAULT = "mistral-large-latest"
MAX_CHUNK_CHARS = 4000


class LLMUnavailableError(Exception):
    """Raised when no Mistral API key is configured (drives HTTP 503)."""


# Injectable for tests: a zero-arg callable returning a Mistral-like client.
client_factory = None


def get_client():
    if client_factory is not None:
        return client_factory()
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise LLMUnavailableError(
            "MISTRAL_API_KEY not set; LLM text preparation is unavailable"
        )
    try:
        from mistralai import Mistral
    except ImportError:  # mistralai 2.x: client moved off the top level
        from mistralai.client import Mistral

    return Mistral(api_key=api_key)


def prepare_text(
    text: str,
    language: str = "it",
    client=None,
    model: str = LLM_MODEL_DEFAULT,
    max_chars: int = MAX_CHUNK_CHARS,
) -> str:
    """Clean + repunctuate + speaker-tag a whole chapter, chunk by chunk."""
    client = client or get_client()
    lang = normalize_language(language)
    parts = [
        llm_prepare(client, model, chunk, language=lang)
        for chunk in chunk_text(text, max_chars)
    ]
    return "\n\n".join(parts)


def segment_lines(prepared: str) -> List[Tuple[Optional[str], Optional[str], str]]:
    """Prepared text -> (speaker, gender, text) lines ready for the cast."""
    return split_long_narration(parse_lines(prepared))


# ── Prepared-chapter cache ─────────────────────────────────────────────────


def prepared_cache_path(settings, book_id: int, chapter_index: int) -> Path:
    return settings.data_dir / "prepared" / f"{book_id}_{chapter_index}.json"


def load_prepared(settings, book_id: int, chapter_index: int) -> Optional[dict]:
    """Cached preparation: {language, prepared_text, lines: [[s, g, text]]}."""
    path = prepared_cache_path(settings, book_id, chapter_index)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_prepared(
    settings, book_id: int, chapter_index: int, language: str, prepared_text: str
) -> dict:
    data = {
        "language": language,
        "prepared_text": prepared_text,
        "lines": [
            [speaker, gender, text] for speaker, gender, text in segment_lines(prepared_text)
        ],
    }
    path = prepared_cache_path(settings, book_id, chapter_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data
