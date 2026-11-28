# tts-ereader — instructions for coding sessions

AI-powered TTS eReader: LLM text preparation + voice-cast synthesis.
**Status (2026-10-13, issue #39): dormant.** The v1 web app is
decommissioned; the only active part is the `book-daily.sh` growing-book
pipeline. Do not start new app work unless the owner asks for it.
The unattended agent workflow (dispatcher, roles, `blocker`/`answered`
issues) was retired on 2026-11-22; work here happens in sessions the owner
starts.

Read `README.md`, `PLAN_epub3_readalong.md` (v0 history) and
`PLAN_v1_reader.md` (the dormant v1 goal) before starting. Do not
re-litigate decided questions (voice cast, book-level delivery,
web-app-with-known-iOS-limitation trade-off).

## Versioning

- `v0` (git tag): the CLI pipeline — `poc_reader.py`, `edge_reader.py`,
  `epub_mo.py`, `epub_readaloud.py`. Working; do not break it.
- `v1`: the archived reader app per `PLAN_v1_reader.md`.

## Working rules

- One PR per coherent unit against `main`, CI green, README and the
  relevant `PLAN`/`docs` files updated with what changed.
- Design choices that change what results mean (what is counted,
  excluded, grouped or named) are the owner's: ask before building.
- Never invent live-test results; mark anything untested as untested.

## Hard constraints

- Develop with tiny slices, mocked synthesizers and synthetic EPUB
  fixtures you generate programmatically. There are no book EPUBs in the
  repo (copyright; `samples/*.epub` is gitignored).
- Use a virtualenv for dependencies, never the system Python.
- Never commit `.env`, API keys, audio files or copyrighted books.
  `.gitignore` covers them — keep it that way. Keys (MISTRAL_API_KEY,
  GEMINI_API_KEY, GOOGLE_TTS_KEY) live only in the owner's local `.env`.
- If an API key you need is not available, write the code and its tests
  with mocks; skip live calls rather than faking them.
- The v0 scripts must keep working: if you refactor shared logic, the
  CLIs (`--list-chapters`, `--slice`, etc.) must still run.
- **Gemini TTS: `gemini-3.8-flash-tts` or newer only.** Never use
  `gemini-2.5-flash-preview-tts` or older models — the owner retired
  them (voice quality; Rami/Kore are the reference voices on 3.8).

## Style

- Match the existing CLI conventions (argparse, `--list-chapters`,
  `--slice`).
- Plain, dependency-light choices win ties. No new heavy dependencies
  without justification in the PR description.

## Private-pattern scan (before every push)

Run `scripts/scan-private.sh` (tree) and `scripts/scan-private.sh --history origin/main..HEAD` (new commits and their
authors) before pushing. The extra list lives in the git-ignored `private/patterns.txt`; CI reads the same list from
the repository secret `PRIVATE_PATTERNS`. Commit only as the GitHub noreply identity
(`pennico <313404961+pennico@users.noreply.github.com>`); the scan rejects any other author or committer.
