# Contributing

Thanks for your interest in contributing.

## Setup

```bash
git clone https://github.com/pennico/tts-ereader.git
cd tts-ereader
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -r requirements.lock -r requirements-dev.txt
```

API keys (`MISTRAL_API_KEY`, `GEMINI_API_KEY`) live in a local `.env` file
(see `.env.example`) and are never committed. You do not need keys to run
the test suite — all tests use mocked engines.

## Running the tests

```bash
/tmp/venv/bin/python -m pytest tests backend/tests -q   # backend + CLI
cd frontend && npm test && npm run check                 # frontend (needs Node.js)
```

Please add tests for anything you change. TTS-related tests must stay
mocked — never spend live Gemini requests in CI.

## Ground rules

- Do not commit real books or copyrighted text. Test fixtures are
  generated programmatically (`tests/fixtures/make_fixture_epub.py`);
  `samples/*.epub` is gitignored for a reason.
- Do not commit audio files, API keys, or `.env`.
- Keep the v0 CLI scripts working: `--list-chapters`, `--slice`, and the
  existing output contracts are relied upon.
- Match the existing style (argparse CLIs, plain dependency-light
  choices). Lint with `ruff check .`.

## Pull requests

Open a PR against `main` with a clear description of what changed and
why, and the test results. Small, focused PRs get reviewed faster.
