# tts-ereader — agent instructions

AI-powered TTS eReader: LLM text preparation + voice-cast synthesis, being
developed into a full ebook reader app with voice-by-progression read-along.
**Status (2026-10-13, issue #39): dormant.** The v1 web app is
decommissioned; the only active part is the `book-daily.sh` growing-book
pipeline. Do not start new app work unless an issue from the owner asks
for it. The text below describes the v1 build phase.

Read `README.md`, `PLAN_epub3_readalong.md` (v0 history), and
`PLAN_v1_reader.md` (current goal) before starting. Do not re-litigate
decided questions (voice cast, book-level delivery, web-app-with-known-iOS-
limitation trade-off).

Cross-cutting operational standards (self-hosted environment, quotas,
scheduled jobs, publish pipeline) live in the owner's private ops
repository (AGENTIC_WORK_STANDARDS.md, not public); where they conflict
with this file, this file wins for work in this repo.

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

## Handoff protocol (unattended sessions)

All roles run headless, launched by the dispatcher; you cannot launch,
resume, or signal another session. The repo is the only coordination bus.

- End every PR with a **Handoff** section: what is done and verified, what
  the next role should pick up, and any decision the owner must make.
- If you are blocked (missing upstream doc, question only the owner can
  answer, work outside your role), **open a GitHub issue labeled `blocker`**
  (`gh issue create --label blocker --title ... --body ...`) and stop
  cleanly. Write it in plain language for a non-developer on a phone:
  what you were doing, what you need from them, the options if any, and
  end with how to answer (comment + `answered` label, or reply to the
  owner's notification channel). The owner gets a push notification, answers in
  a comment, and adds the `answered` label — the dispatcher then resumes
  with your issue and the owner's answer quoted in the prompt. Close the
  issue once your resumed session has resolved it.
- Design choices that change what results mean (what is counted,
  excluded, grouped, or named) are owner decisions: ask before
  building — file a blocker with the options instead of guessing
  and building.
- Never wait idly for another agent — either proceed with work that is
  within your role, or stop with the issue filed.

## Decision defaults (do not stop to ask)

You may run unattended (headless dispatcher); a stopped session wastes the
whole run. When a question is not answered by the docs:

- Prefer the simpler, dependency-light option and record the choice in the
  PR's Handoff section.
- SPEC/ARCHITECTURE ambiguities: follow `docs/SPEC_v1.md` acceptance
  criteria literally; where silent, follow commercial-reader conventions
  (Apple Books / Readest).
- Never invent live-test results; mark anything untested as untested.
- Only stop (open a GitHub issue) if proceeding would be irreversible or
  would break the v0 scripts.

## Hard constraints

- **Sandbox commands time out at 30 seconds.** Never launch long
  synthesis, builds with big dependency trees, or long test runs. Develop
  with tiny slices, mocked synthesizers, and synthetic EPUB fixtures you
  generate programmatically. There are no book EPUBs in the repo
  (copyright; `samples/*.epub` is gitignored) — build fixtures instead.
- **Never pip install into the system Python.** Sessions may run inside
  the agent-runner container, whose Python is shared with the `vibe`
  CLI itself — installing or upgrading packages there breaks the agent
  loop. If you need dependencies, use a venv:
  `python3 -m venv /tmp/venv && /tmp/venv/bin/pip install ...`.
- Never commit `.env`, API keys, audio files, or copyrighted books.
  `.gitignore` covers them — keep it that way. Keys (MISTRAL_API_KEY,
  GEMINI_API_KEY, GOOGLE_TTS_KEY) live only in the owner's local `.env`.
- If an API key you need is not available in your environment, write the
  code and its tests with mocks; skip live calls rather than faking them.
- The v0 scripts must keep working: if you refactor shared logic, the
  CLIs (`--list-chapters`, `--slice`, etc.) must still run.
- **Gemini TTS: `gemini-3.8-flash-tts` or newer only.** Never use
  `gemini-2.5-flash-preview-tts` or older models — the owner retired
  them (voice quality; Rami/Kore are the reference voices on 3.8).

## Style

- Match the existing CLI conventions (argparse, `--list-chapters`,
  `--slice`).
- New app code follows the stack chosen in `docs/ARCHITECTURE_v1.md`;
  until that doc exists, do not start implementation (role C waits for
  role B).
- Plain, dependency-light choices win ties. No new heavy dependencies
  without justification in the PR description.
