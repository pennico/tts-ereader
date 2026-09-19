# tts-ereader — agent instructions

AI-powered TTS eReader: LLM text preparation + voice-cast synthesis, being
developed into a full ebook reader app with voice-by-progression read-along.
Read `README.md`, `PLAN_epub3_readalong.md` (v0 history), and
`PLAN_v1_reader.md` (current goal) before starting. Do not re-litigate
decided questions (voice cast, book-level delivery, web-app-with-known-iOS-
limitation trade-off).

## Versioning

- `v0` (git tag): the CLI pipeline — `poc_reader.py`, `edge_reader.py`,
  `epub_mo.py`, `epub_readaloud.py`. Working; do not break it.
- `v1` (current): the reader app per `PLAN_v1_reader.md`.

## Your role

You are one of four agent roles (A: Research & Spec, B: Architecture,
C: Implementation, D: Testing & QA — see the workflow table in
`PLAN_v1_reader.md`). Your session prompt names your role. Rules:

- Read your role's upstream input doc from the repo first. If it is
  missing, either produce it (if it is your role's job) or stop with a
  clear note in the session — never fake upstream work.
- Produce your role's deliverable as a PR against `main`. One PR per
  coherent unit; keep commits incremental with clear messages.
- Update `README.md` and the relevant `PLAN`/`docs` files with what you
  did — the owner reads those first when he returns.

## Handoff protocol (sessions cannot trigger each other)

Cloud sessions are independent: you cannot launch, resume, or signal
another session. The repo is the only coordination bus.

- End every PR with a **Handoff** section: what is done and verified, what
  the next role should pick up, and any decision the owner must make.
- If you are blocked (missing upstream doc, question only the owner can
  answer, work outside your role), **open a GitHub issue** describing the
  blocker and stop cleanly. The owner sees the issue from his phone and
  launches the next session pointed at it.
- Never wait idly for another agent — either proceed with work that is
  within your role, or stop with the issue filed.

## Hard constraints

- **Sandbox commands time out at 30 seconds.** Never launch long
  synthesis, builds with big dependency trees, or long test runs. Develop
  with tiny slices, mocked synthesizers, and synthetic EPUB fixtures you
  generate programmatically. There are no book EPUBs in the repo
  (copyright; `samples/*.epub` is gitignored) — build fixtures instead.
- Never commit `.env`, API keys, audio files, or copyrighted books.
  `.gitignore` covers them — keep it that way. Keys (MISTRAL_API_KEY,
  GEMINI_API_KEY, GOOGLE_TTS_KEY) live only in the owner's local `.env`.
- If an API key you need is not available in your environment, write the
  code and its tests with mocks; skip live calls rather than faking them.
- The v0 scripts must keep working: if you refactor shared logic, the
  CLIs (`--list-chapters`, `--slice`, etc.) must still run.

## Style

- Match the existing CLI conventions (argparse, `--list-chapters`,
  `--slice`).
- New app code follows the stack chosen in `docs/ARCHITECTURE_v1.md`;
  until that doc exists, do not start implementation (role C waits for
  role B).
- Plain, dependency-light choices win ties. No new heavy dependencies
  without justification in the PR description.
