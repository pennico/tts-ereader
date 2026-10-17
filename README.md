# tts-ereader: read-along EPUB 3 generator with AI narration

[![CI](https://github.com/pennico/tts-ereader/actions/workflows/ci.yml/badge.svg)](https://github.com/pennico/tts-ereader/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Status: dormant](https://img.shields.io/badge/status-dormant-lightgrey.svg)

Command-line tools that turn an EPUB into a **read-along EPUB 3**: the book
text plus narration audio, with Media Overlays (SMIL) so a compatible reader
highlights each line as it is spoken. Text is first prepared by an LLM
(cleaned, repunctuated for speech, dialogue tagged with speakers), then
synthesized with Gemini TTS or the free Microsoft edge-tts voices.

## Status

**Dormant.** The v1 self-hosted web reader app was decommissioned on
2026-10-13 (issue #39) and gets no further development; the owner reads the
generated EPUBs in Readest instead. The one part still in active use is the
**book-daily** job (below), which reads the next chapter(s) of a book every
night within the Gemini free-tier quota and grows a single read-along EPUB.
The app code, Docker image and docs are kept for a possible revival; see
[docs/ARCHIVED_v1_app.md](docs/ARCHIVED_v1_app.md).

## What still works

| Tool | What it does |
|---|---|
| `book-daily.sh` | Daily growing-book job: next unread chapter(s) via `gemini_readaloud.py`, appended to one EPUB (active) |
| `gemini_readaloud.py` | Read-along EPUB with Gemini TTS; quota-aware, resumable across days |
| `epub_readaloud.py` | Read-along EPUB with edge-tts (free voices), built from the prepared text |
| `epub_fixedlayout.py` | Fixed-layout variant, the only read-along route Apple Books plays |
| `epub_mo.py` | Media Overlays injected into the book's original XHTML (edge-tts) |
| `edge_reader.py` | MP3 + manifest for a text or a chapter (edge-tts) |
| `poc_reader.py` | Phase 0 Voxtral proof of concept, see [docs/POC_voxtral.md](docs/POC_voxtral.md) |

## Setup

Python 3.9 or newer (CI runs 3.9 and 3.12) and `ffmpeg`
(`brew install ffmpeg` / `apt install ffmpeg`).

```bash
git clone https://github.com/pennico/tts-ereader.git
cd tts-ereader
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock   # pinned (Python 3.10+)
# Python 3.9: .venv/bin/pip install -r requirements.txt
cp .env.example .env                          # then fill in your keys
```

Keys live only in `.env` (gitignored, never commit it):

| Key | Needed for |
|---|---|
| `GEMINI_API_KEY` | `gemini_readaloud.py` and `book-daily.sh` (Gemini TTS) |
| `MISTRAL_API_KEY` | LLM text preparation (all generators) and `poc_reader.py` |

edge-tts synthesis needs no key. Never commit real books: put your own EPUBs
under `out/` (gitignored), for example `out/archive/`.

## book-daily: the daily growing-book job

`book-daily.sh` reads a book a little every day with the free Gemini TTS
quota (observed 100 requests/day per model) and keeps **one** growing
read-along EPUB for the whole book. Each run:

1. finds the next unread chapter (the highest chapter with finished
   artifacts in the work dir, plus one);
2. reads the remaining daily budget from the quota ledger
   (`out/quota_ledger.json`);
3. calls `gemini_readaloud.py --growing` chapter by chapter until the
   budget is spent or the book is done. Already synthesized segments are
   cached and never re-requested; a quota abort mid-chapter (exit 75) is a
   normal end of day and resumes tomorrow;
4. rebuilds the output EPUB from every completed chapter and, on the
   owner's server, drops a publish flag so the file is copied to the
   reading device.

```bash
# Print the resolved configuration without reading anything
DRY_RUN=1 LAST_CH=12 bash book-daily.sh out/archive/mybook.epub

# Read the next chapter(s) of your own book (spine indices 3..12)
FIRST_CH=3 LAST_CH=12 bash book-daily.sh out/archive/mybook.epub

# Verbatim text instead of LLM repunctuation, another voice
APPROACH=loyal TTS_VOICE=Kore LAST_CH=12 bash book-daily.sh out/archive/mybook.epub
```

Find the spine indices with
`python3 gemini_readaloud.py --epub out/archive/mybook.epub --list-chapters`.
Run with no argument, the script reads the owner's current book with its
existing paths (this is how the scheduled job calls it).

| Variable | Default | Meaning |
|---|---|---|
| `EPUB` (or first argument) | the owner's current book | Source EPUB |
| `BOOK` | EPUB file name without `.epub` | Name used for the output dir and file |
| `APPROACH` | `prepared` | `prepared` = LLM repunctuation, 400-char batches; `loyal` = author's text verbatim, one request per segment |
| `FIRST_CH` / `LAST_CH` | `0` / required | Spine range to read (`LAST_CH` is required for your own book) |
| `TTS_MODEL` | `gemini-3.8-flash-lite-tts` | Gemini TTS model (3.8 or newer only) |
| `TTS_VOICE` | `Rami` | Single narrator voice |
| `PREP_LLM` | `claude-sonnet-5-5` | Text-preparation LLM for `prepared` (Claude Code CLI on the subscription token; a Mistral model name such as `mistral-large-latest` switches back) |
| `DAILY_BUDGET` | `90` | Requests per day this job may spend |
| `MIN_USEFUL` | `5` | Do not start a chapter with fewer requests left |
| `BATCH_CHARS` | `400` | Characters per request in `prepared` mode |
| `WORK_DIR` | `out/readings/$BOOK/$APPROACH-gemini38/work` | Segment cache and per-chapter artifacts |
| `OUT_EPUB` | `.../readalong-$BOOK-full.epub` next to the work dir | The growing EPUB |
| `LEDGER` / `BOOK_DAILY_LOG` | `out/quota_ledger.json` / `out/book-daily.log` | Quota ledger and run log |

Exit codes: `0` for a good day (chapters read, budget spent, or book
complete), `2` for a configuration error, anything else is a real failure.

**Scheduling.** `.github/workflows/book-daily.yml` fires daily at 00:10 UTC,
just after the quota reset, and files a `run`-labeled issue whose first line
is the command. The owner's self-hosted dispatcher (`dispatcher/`) executes
that command in its clone of this repo, posts the output tail and closes the
issue. The workflow does nothing unless the repository variable
`TTS_BOOK_DAILY` is `enabled`. Without the dispatcher you can run the script
from your own cron instead:

```cron
10 0 * * * cd /path/to/tts-ereader && LAST_CH=12 bash book-daily.sh out/archive/mybook.epub
```

Background on the request budget, the 400-char method and the loyal mode:
[docs/REQUEST_EFFICIENCY.md](docs/REQUEST_EFFICIENCY.md).

## Generators

The per-tool reference. All generators share the LLM preparation in `shared/`
and the CLI conventions `--list-chapters` and `--chapter N`; the EPUB
generators add `--slice CHARS` (test on a slice first) and `--all`.

### edge_reader: edge-tts hybrid (Italian)

`edge_reader.py` is a second engine that keeps the LLM analysis stage but swaps
Voxtral for free Microsoft edge-tts neural voices (no API key needed for
synthesis). Built for Italian, where Voxtral's cross-lingual quality is poor.

```
Text -> [Mistral LLM: clean OCR/spelling errors + repunctuate for speech
         + tag dialogue speakers with gender]
     -> prepared lines -> [voice cast] -> edge-tts per line
     -> poc_output.mp3 + poc_manifest.json (works in poc_player.html)
```

#### Voice cast

| Role | Voice |
|---|---|
| Narrator / male characters | it-IT-GiuseppeMultilingualNeural |
| First female character | fr-FR-VivienneMultilingualNeural |
| Other female characters | en-US-EmmaMultilingualNeural |
| Very short male side roles (`--andrew-short`, off by default) | en-US-AndrewMultilingualNeural |

#### Usage

```bash
pip3 install edge-tts

# From a text file
python3 edge_reader.py --file sample.txt --output-dir out/sample_edge

# From an EPUB chapter
python3 edge_reader.py --epub "book.epub" --list-chapters
python3 edge_reader.py --epub "book.epub" --chapter 4 --output-dir out/ch4
```

Options: `--rate` (default `-8%`, softens delivery), `--model` (LLM for
preparation, default `mistral-large-latest`), `--max-chars` (chunk size),
`--andrew-short`, `--workers` (concurrent edge-tts requests, default 4).
The prepared text is saved as `prepared_text.txt` so the
cleaning/re-punctuation can be inspected before listening.

#### Cost

Synthesis is free (edge-tts). Only the LLM preparation is billed: roughly $4 per
million characters with `mistral-large-latest` (a whole book ≈ $1.50), under
$0.50 with `mistral-small-latest`.

### epub_mo: EPUB 3 Media Overlays (read-along)

`epub_mo.py` produces a read-along EPUB: the original book text with synced
sentence-level highlighting and continuous audio, playable in Apple Books
(iPhone) with playback from the lock screen. It reuses the edge_reader
pipeline (LLM preparation + voice cast) and adds:

- Word-level timings from edge-tts `WordBoundary` events
- Alignment of the prepared (cleaned) words back to the original EPUB text
  via difflib, so the displayed text stays the book's own XHTML
- Invisible `<span id="mo-N">` anchors injected around sentence fragments
- One SMIL per chapter, `media:duration` metadata, and an EPUB 3 upgrade of
  the package (the source is EPUB 2.0: version bump, nav document, legacy
  NCX kept)
- Footnote bodies removed by the LLM get no `<par>` and are skipped in
  playback; clips tile continuously so audio never stutters

```bash
# List chapters
python3 epub_mo.py --epub "book.epub" --list-chapters

# Test slice of one chapter (~4000 chars, ~4 min audio, ~1 min generation)
python3 epub_mo.py --epub "book.epub" --chapter 4 --slice 4000 \
    --output out/mo_test.epub

# Full book
python3 epub_mo.py --epub "book.epub" --all --output out/book_readalong.epub
```

Options: `--rate`, `--model`, `--max-chars`, `--andrew-short` (same as
edge_reader), plus `--slice` (chars per chapter, for testing) and `--work-dir`
(intermediate segment files, default `out/mo_work`). Synthesis runs with
`--workers` concurrent edge-tts requests (default 4). The script validates its
own output (OPF/SMIL parse, anchors exist, clips monotonic) and reports the
word match rate; a test slice of chapter 4 matched 94% of source words and
clipped 50/52 fragments (the misses were the chapter number and one clause
the LLM re-tagged as a speaker label).

Known limitation: edge-tts multilingual voices auto-detect language per
sentence and cannot be forced to Italian; occasional non-Italian readings of
foreign words are possible.

**Important — Apple Books does not play these files.** Apple Books (iPhone
and Mac) ignores Media Overlays in reflowable EPUBs; it only plays them in
fixed-layout books. Use `epub_fixedlayout.py` (below) for the Apple Books
route, or `epub_readaloud.py` output with Thorium Reader (Mac) or another
Media Overlays capable reader.

### epub_readaloud: simple read-along EPUB (recommended)

`epub_readaloud.py` is the simpler, mistake-proof variant: instead of
injecting overlays into the original book XHTML, it builds a fresh minimal
EPUB whose content IS the prepared reading text. Each line is a paragraph
paired in the SMIL to its exact audio segment offset — displayed text and
spoken text are identical by construction, with no alignment step.

```bash
# Test slice of one chapter (~4000 chars, ~3 min audio, ~1 min generation)
python3 epub_readaloud.py --epub "book.epub" --chapter 4 --slice 4000 \
    --output out/readalong_test.epub

# Full book
python3 epub_readaloud.py --epub "book.epub" --all --output out/readalong.epub
```

Same options as edge_reader (`--rate`, `--model`, `--max-chars`,
`--andrew-short`, `--workers`), plus `--slice` and `--work-dir`. It also strips the book
title that leaks from the source `<title>` tag so chapters don't start with
the title being read aloud.

### gemini_readaloud: Gemini TTS read-along (quota-resumable)

`gemini_readaloud.py` is the same output contract as `epub_readaloud.py`,
but synthesis goes through the Gemini TTS engine one prepared line at a
time (the "box" method), with per-line audio cleaning. It is built for
the Gemini per-day request quota (observed limit: **100 requests/day
per model**, 2026-10-06, issue #23; earlier observed ~10/day — the
tier's limit has changed before, so treat the number as volatile), so
runs are resumable across days (issue #17):

- The prepared text is cached per chapter (`prepared_text.txt` +
  `prepared_meta.txt` fingerprint) and reused verbatim on re-runs —
  LLM preparation is non-deterministic, and regenerating it would
  rewrite every line, invalidate the whole segment cache, and re-spend
  the chapter's entire daily quota on every run. The fingerprint binds
  to the resolved epub path plus a hash of the sliced source text, so
  a differently-spelled path still resumes and a replaced epub at the
  same path regenerates instead of reusing the old book's text.
  `--reprepare` forces regeneration.
- Synthesized segments are cached under the work dir; re-runs skip
  them and only spend quota on new lines.
- A daily-quota 429 aborts at once with a resumable error instead of
  retry-backoff: the per-day limit does not reset within a run, so
  waiting cannot help. Detection matches the quota metric in the error
  body in both spellings the API has used — CamelCase
  `GenerateRequestsPerDayPerProjectPerModel` and the current
  snake_case `generate_requests_per_model_per_day` (issue #23; the
  literal `PerDay` match missed the new format and the abort surfaced
  as exit 1). Per-minute 429s keep the 60–240 s backoff retry. The
  abort prints a one-line `QUOTA EXHAUSTED (resumable)` message with
  the API's own "retry in ..." hint and exits with code **75**
  (`EX_TEMPFAIL`), so wrapper jobs can tell "re-run after the reset to
  resume" apart from a real failure (issue #21).
- **Request-efficient mode** (issue #25): `--lines-per-request N`
  batches up to N prepared lines into ONE Gemini request — the
  blocking quota is the per-day REQUEST count (100/day on
  3.8-flash-tts), not tokens, and one request per line spends the
  whole bucket on a single chapter. Per-line voice casting is kept
  (2-voice batches go out as labeled multi-speaker conversations —
  the API requires exactly 2 speaker configs, so batches spanning 3
  voices are split; 1-voice batches go out as plain multi-paragraph
  requests). The batch's single take is split back into per-line
  segments at silence gaps, so the SMIL offsets stay per-line; a
  batch that cannot be aligned confidently (or hits the recitation
  filter) falls back to per-line synthesis — a few extra requests
  beat misaligned highlighting. Batches already fully cached per-line
  from earlier runs are stitched from the per-line cache without a
  new request. Default 1 = the original per-line box method.
- **Quota ledger** (issue #25): every run appends its measured
  request/token counts (from the API responses' `usageMetadata`) to
  `out/quota_ledger.json` — on success, quota abort, and failure
  alike — and prints the day's total for the model. Wrappers read the
  ledger (`shared/quota_ledger.py`) to report spend in notifications.
  Measured comparison of per-line vs batched synthesis (requests,
  tokens, wall time, alignment error):
  `docs/REQUEST_EFFICIENCY.md` — raw numbers in
  `out/voice_tests/reqeff-measurements.json` (local run artifacts,
  not committed).

```bash
python3 gemini_readaloud.py --epub "book.epub" --chapter 3 --slice 1200 \
    --single Kore --pace 20 --output out/slice.epub

# Request-efficient: whole chapters within the daily request quota
python3 gemini_readaloud.py --epub "book.epub" --chapter 3 \
    --narrator Rami --voice-m Rami --voice-f Kore \
    --lines-per-request 10 --pace 20 --output out/ch1.epub
```

A slice larger than the daily quota allows (observed 100 requests/day)
takes several days (each daily run synthesizes what the quota allows,
then resumes the next day); paid tier removes the limit.

#### Choosing how to read (model + approach)

Two knobs decide how a run is carried out: the **model** (`--model`,
default `gemini-3.8-flash-tts` — the quality reference; Rami/Kore are
the reference voices. 3.8-or-newer TTS models only: 2.5-preview-tts and
older are retired. Observed quota on an AI Studio key: 100 requests/day
per model — the number has changed before, so treat it as volatile) and
the **approach**: how many prepared lines go into one request
(`--lines-per-request`, or one `--preset` flag that expands to it and is
printed in the run log; an explicit `--lines-per-request` wins over the
preset).

| Approach | Requests (513-line run) | Quality | When to use |
|---|---|---|---|
| Per-line (`--preset quality` = `--lines-per-request 1`, the default) | 513 | Best prosody: each line a fresh, self-contained delivery; exact SMIL offsets | Short runs, slices, or when the request quota does not matter |
| Batched (`--preset balanced` = `--lines-per-request 10`) | ~53 | Coherent pacing across lines; a batch that cannot be split confidently falls back to per-line (measured 20-line 3.8-flash-lite sample: 1 of 2 batch10 takes fell back) | Whole chapters within the daily request quota |
| Aggressive batching (`--preset fast` = `--lines-per-request 20`) | ~26 | Longest batches — one bad take affects up to 20 lines; measured 20-line 3.8-flash-lite sample: no fallbacks, boundary drift up to ~7.7 s | Big books on a tight request budget |

Batching keeps per-line voice casting, per-line SMIL offsets (the batch
take is split back into per-line segments at silence gaps), caching, and
the per-line fallbacks; a batch that cannot be aligned confidently falls
back to per-line synthesis. Measured tradeoffs and samples:
`docs/REQUEST_EFFICIENCY.md`.

```bash
# Best quality, one request per line (needs quota headroom or multi-day resume)
python3 gemini_readaloud.py --epub "book.epub" --chapter 3 \
    --narrator Rami --voice-m Rami --voice-f Kore \
    --preset quality --output out/ch3.epub

# Recommended: whole chapters within the daily request quota
python3 gemini_readaloud.py --epub "book.epub" --chapter 3 \
    --narrator Rami --voice-m Rami --voice-f Kore \
    --preset balanced --output out/ch3.epub

# Fewest requests: big books on a tight budget
python3 gemini_readaloud.py --epub "book.epub" --all \
    --narrator Rami --voice-m Rami --voice-f Kore \
    --preset fast --output out/book.epub

# Explicit model choice (default shown)
python3 gemini_readaloud.py --epub "book.epub" --chapter 3 \
    --model gemini-3.8-flash-tts --preset balanced --output out/ch3.epub
```

#### Where read-along actually works

| Reader | Media Overlays (reflowable) | Media Overlays (fixed layout) |
|---|---|---|
| Apple Books (iPhone + Mac) | No — opens the book, ignores the overlay | Yes — use `epub_fixedlayout.py` |
| Thorium Reader (Mac/Win/Linux, free) | Yes — the reference test player | Yes |
| Kobo Books / Adobe Digital Editions (iOS) | Yes (per current reports) | Yes |
| Readest | No | No |

Test on the Mac with Thorium Reader (https://www.edrlab.org/software/thorium-reader/):
open the EPUB, press play — sentences highlight in yellow as Giuseppe reads.

### epub_fixedlayout: Apple Books route (fixed layout)

`epub_fixedlayout.py` is the variant that Apple Books will actually play.
Apple Books ignores Media Overlays in reflowable EPUBs but plays them in
fixed-layout (pre-paginated) books, so this script paginates the prepared
reading text into fixed-size pages and emits the metadata Apple requires:

- `rendition:layout` = `pre-paginated` and `rendition:viewport` in the OPF
- A `<meta name="viewport">` in every page document
- One XHTML + one SMIL per page; page SMILs clip into the chapter's single
  audio file (clips are exact concatenation offsets, like epub_readaloud)
- Pagination by character budget (`--chars-per-page`, default 900): lines
  are never split across pages, since each line is one SMIL par/clip

```bash
# Tiny demo book (no API key needed, ~15s) — for Apple Books device QA
python3 epub_fixedlayout.py --demo --output out/fx_demo.epub

# Test slice of one chapter
python3 epub_fixedlayout.py --epub "book.epub" --chapter 4 --slice 4000 \
    --output out/fx_test.epub

# Full book
python3 epub_fixedlayout.py --epub "book.epub" --all --output out/fx.epub
```

Same options as `epub_readaloud.py`, plus `--chars-per-page` (default 900)
and `--viewport WIDTHxHEIGHT` (default 768x1024, portrait). The script
validates its own output (OPF/SMIL parse, anchors, clip monotonicity, plus
fixed-layout metadata checks); unit tests in `tests/test_fixedlayout.py`.

#### Parallel synthesis

All engines synthesize with `--workers` concurrent edge-tts requests
(default 4; `--workers 1` restores the old sequential behavior). Segment
order — and therefore the concatenation offsets and SMIL clips — is
preserved regardless of worker count. On the 7-line demo book the synthesis
stage dropped from ~13s to ~2s with 4 workers; a full book is expected to
drop from ~1.5-2h to roughly 30-40 min. Unit tests with a mocked
synthesizer: `tests/test_parallel_synth.py`.

#### Device QA (Apple Books)

1. `python3 epub_fixedlayout.py --demo --output out/fx_demo.epub`
2. AirDrop/transfer the file to iPhone (or open on Mac), then open in Apple
   Books — a read-aloud play control should appear.
3. If text overflows a page, lower `--chars-per-page` (e.g. 700) or raise
   `--viewport`; if it looks too sparse, raise the budget.
4. For a real chapter: `--chapter 4 --slice 4000` first, then `--all`.

Known trade-off: fixed layout means no user-adjustable font size, and page
breaks are estimated from character counts, not rendered text. Expect one
tuning round of `--chars-per-page` per book after looking at it on device.

## Tests

All tests are offline: engines are mocked and fixtures are generated
(`tests/fixtures/make_fixture_epub.py`), so no API key or Gemini quota is
used.

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/python -m pytest tests backend/tests dispatcher -q
cd frontend && npm ci && npm test && npm run check   # archived app UI
```

As of 2026-10-17: 237 tests for the CLI tools and the archived backend, 87
for the dispatcher, 55 frontend tests. CI runs all of them on every PR
(Python 3.9 and 3.12, Node 20). `backend/tests/unit/test_benchmark_profile.py`
reads `/proc` and only passes on Linux.

## Project structure

```
tts-ereader/
├── book-daily.sh          # Daily growing-book job (active)
├── loyal-sample.sh        # One-shot verbatim-mode sample
├── gemini_readaloud.py    # Gemini TTS read-along EPUB (quota-resumable)
├── epub_readaloud.py      # edge-tts read-along EPUB from prepared text
├── epub_fixedlayout.py    # Fixed-layout read-along EPUB (Apple Books)
├── epub_mo.py             # Media Overlays on the original XHTML
├── edge_reader.py         # edge-tts hybrid engine (LLM prep + free voices)
├── poc_reader.py          # Phase 0 Voxtral PoC (+ poc_player.html)
├── benchmark_*.py         # Engine and resource benchmarks (archived app)
├── shared/                # Text preparation, voice cast, quota ledger
├── tests/                 # CLI tests (+ fixtures/make_fixture_epub.py)
├── backend/, frontend/    # Archived v1 web app (FastAPI + Svelte)
├── Dockerfile, docker-compose.yml   # Archived app deployment
├── dispatcher/, .vibe/    # Agent workflow engine and its command guard
├── docs/                  # Specs, request-efficiency notes, archived docs
├── samples/               # Original sample texts (no books)
└── out/                   # Generated output and your EPUBs (gitignored)
```

## How this repo is built (agent workflow)

Most of this code was written by AI coding agents, and the files that drive
them are public on purpose:

- `AGENTS.md` holds the instructions every agent session reads first: roles,
  hard constraints (no real books, mocked engines, keys only in `.env`), and
  how to hand off work.
- `dispatcher/` is a self-hosted scheduler (a synced copy from the owner's
  ops repo) that turns `ROADMAP.md` checkboxes, labeled issues and open PRs
  into headless agent sessions: implement, QA review, merge when CI is
  green. `run`-labeled issues (like book-daily's) are executed as plain
  commands without an LLM. It acts only on the owner's and the Actions
  bot's issues, PRs and comments, never on PRs from forks.
- `.vibe/` is the agent CLI's hook config and a guard that blocks
  some destructive shell commands.
- `PLAN_*.md`, `ROADMAP.md` and `docs/SPEC_v1.md` / `docs/ARCHITECTURE_v1.md`
  / `docs/QA_v1.md` are the agents' planning and review record.

The owner sets the work and answers the agents' questions in issues.
Human contributions go through normal pull requests, reviewed by the owner; see [CONTRIBUTING.md](CONTRIBUTING.md). You do not need the
dispatcher to use or develop the tools.

## License

MIT, see [LICENSE](LICENSE).

## Contributing and security

- Contributions: [CONTRIBUTING.md](CONTRIBUTING.md) and the
  [Code of Conduct](CODE_OF_CONDUCT.md).
- Security issues: report privately as described in
  [SECURITY.md](SECURITY.md), not in a public issue.
