# Contributing

Thanks for your interest in contributing. The project is dormant (see the
README): bug fixes and improvements to the read-along generators and
`book-daily.sh` are welcome; the archived v1 web app only takes small fixes.

## Setup

Python 3.9 or newer and `ffmpeg`.

```bash
git clone https://github.com/pennico/tts-ereader.git
cd tts-ereader
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock -r requirements-dev.txt   # Python 3.10+
# Python 3.9: .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
# Optional console commands (tts-gemini-readaloud, ...): .venv/bin/pip install -e . --no-deps
```

API keys (`GEMINI_API_KEY`, `MISTRAL_API_KEY`) live in a local `.env` file
(see `.env.example`) and are never committed. You do not need keys to run
the test suite: all tests use mocked engines.

## Running the checks

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -q          # tests/, backend/tests/, dispatcher/
cd frontend && npm ci && npm test && npm run check   # archived app UI (Node 20)
```

CI runs the same commands on Python 3.9 and 3.12. Please add tests for
anything you change. TTS-related tests must stay mocked: never spend live
Gemini requests in CI.

## Dependencies

`requirements.txt` and `pyproject.toml` list the same lower bounds;
`requirements.lock` holds the exact pins CI and the Docker image use. After
changing a dependency, update all three
(`uv pip compile requirements.txt -o requirements.lock`). No new runtime
dependency without a reason in the PR description.

## Ground rules

- Do not commit real books or copyrighted text. Test fixtures are
  generated programmatically (`tests/fixtures/make_fixture_epub.py`);
  `*.epub` is gitignored for a reason.
- Do not commit audio files, API keys, or `.env`.
- Keep the CLI scripts working: `--list-chapters`, `--slice`, and the
  existing output contracts are relied upon, and `bash book-daily.sh` with
  no arguments must keep its current defaults (the scheduled job runs it
  that way).
- Match the existing style (argparse CLIs, plain dependency-light choices).

## Pull requests

Open a PR against `main` with a clear description of what changed and
why, and the test results. Small, focused PRs get reviewed faster.

Much of this repo is written by AI agents (see "How this repo is built" in
the README). `AGENTS.md` is written for them; as a human contributor you
can ignore its role and hand-off rules, but its hard constraints (no books,
no keys, mocked engines) apply to everyone.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
