# AI-Powered TTS eReader

An AI-powered text-to-speech system that analyzes text for characters, emotion, and context, then synthesizes expressive speech with distinct character voices. The v0 CLI pipeline is validated and preserved; the v1 reader app (library, reader view, TTS with voice-by-progression, Docker deployment) is implemented.

## Status

- **Phase 0 (PoC)**: Complete and validated. English fiction and nonfiction reading quality is good.
- **Italian**: Works but quality is poor — Voxtral uses cross-lingual transfer, not native Italian. This is a model limitation.
- **Italian (edge-tts hybrid)**: Good quality. `edge_reader.py` pairs Mistral LLM text preparation (cleaning, re-punctuation for speech, speaker tagging) with free Microsoft edge-tts neural voices. See "edge_reader" below.
- **Danish**: Not supported by Voxtral. Included as a test case only.
- **EPUB support**: Working. Text is extracted, chunked, analyzed, and synthesized per chapter.
- **v1 (implemented)**: the reader app is delivered — see `PLAN_v1_reader.md`, `docs/SPEC_v1.md`, and `docs/ARCHITECTURE_v1.md`. M1 (library + reader view), M2 (TTS engines + voice-by-progression), M3 (voice tuning + LLM preparation with per-book voice casts), and M4 (Docker deployment + benchmark harness + docs) are implemented and merged; see `ROADMAP.md` (fully ticked). Test plan and recorded results: `docs/QA_v1.md`. Remaining open items are live-key benchmarks (AC-603/604) and the homelab manual checklist in `docs/QA_v1.md` §1.2.

## Architecture

```
Text → [Mistral LLM analysis] → reading_script.json
         (segments: text, speakable_text, speaker, gender, emotion, pace, voice-profile)
              ↓
         voice-profile + emotion → voice_id mapping (voices.json)
              ↓
reading_script.json → [Voxtral TTS per segment] → audio segments + offsets manifest
              ↓
poc_output.mp3 + poc_manifest.json → [poc_player.html] → synced text + audio
```

The separation between analysis and synthesis is what makes "make this character more convinced/soft" possible: you edit the voice-profile or emotion field in `reading_script.json` and re-synthesize only the affected segments.

For long texts (EPUB chapters), the pipeline chunks text at paragraph boundaries (default 4000 chars per chunk), analyzes each chunk separately, and renumbers segments globally before synthesis.

## edge_reader: edge-tts hybrid (Italian)

`edge_reader.py` is a second engine that keeps the LLM analysis stage but swaps
Voxtral for free Microsoft edge-tts neural voices (no API key needed for
synthesis). Built for Italian, where Voxtral's cross-lingual quality is poor.

```
Text -> [Mistral LLM: clean OCR/spelling errors + repunctuate for speech
         + tag dialogue speakers with gender]
     -> prepared lines -> [voice cast] -> edge-tts per line
     -> poc_output.mp3 + poc_manifest.json (works in poc_player.html)
```

### Voice cast

| Role | Voice |
|---|---|
| Narrator / male characters | it-IT-GiuseppeMultilingualNeural |
| First female character | fr-FR-VivienneMultilingualNeural |
| Other female characters | en-US-EmmaMultilingualNeural |
| Very short male side roles (`--andrew-short`, off by default) | en-US-AndrewMultilingualNeural |

### Usage

```bash
pip3 install edge-tts

# From a text file
python3 edge_reader.py --file sample.txt --output-dir out/saramago_edge

# From an EPUB chapter
python3 edge_reader.py --epub "book.epub" --list-chapters
python3 edge_reader.py --epub "book.epub" --chapter 4 --output-dir out/ch4
```

Options: `--rate` (default `-8%`, softens delivery), `--model` (LLM for
preparation, default `mistral-large-latest`), `--max-chars` (chunk size),
`--andrew-short`, `--workers` (concurrent edge-tts requests, default 4).
The prepared text is saved as `prepared_text.txt` so the
cleaning/re-punctuation can be inspected before listening.

### Cost

Synthesis is free (edge-tts). Only the LLM preparation is billed: roughly $4 per
million characters with `mistral-large-latest` (a whole book ≈ $1.50), under
$0.50 with `mistral-small-latest`.

## epub_mo: EPUB 3 Media Overlays (read-along)

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
    --output out/saramago_mo_test.epub

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

## epub_readaloud: simple read-along EPUB (recommended)

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

## gemini_readaloud: Gemini TTS read-along (quota-resumable)

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
- **Request-efficient mode** (issue #25; owner configuration
  2026-10-07): lines are batched into ONE Gemini request per batch —
  the blocking quota is the per-day REQUEST count (100/day on the 3.8
  TTS models), not tokens, and one request per line spends the whole
  bucket on a single chapter. **Default sizing**: the whole required
  text is spread over `--daily-requests 90` requests — each request
  carries total_chars/90 characters (capped by
  `--max-request-chars 2000`) — so a full read fits one day's quota
  with the remainder as margin for ad-hoc daily tests.
  `--lines-per-request N` overrides the sizing with fixed batches;
  `--daily-requests 0` restores the original per-line box method.
  Per-line voice casting is kept (2-voice batches go out as labeled
  multi-speaker conversations — the API requires exactly 2 speaker
  configs, so batches spanning 3 voices are split; 1-voice batches
  go out as plain multi-paragraph requests). The batch's single take
  is split back into per-line segments at silence gaps, so the SMIL
  offsets stay per-line; a batch that cannot be aligned confidently
  (or hits the recitation filter) falls back to per-line synthesis —
  a few extra requests beat misaligned highlighting. Batches already
  fully cached per-line from earlier runs are stitched from the
  per-line cache without a new request.
- **Quota ledger** (issue #25): every run appends its measured
  request/token counts (from the API responses' `usageMetadata`) to
  `out/quota_ledger.json` — on success, quota abort, and failure
  alike — and prints the day's total for the model. Wrappers read the
  ledger (`shared/quota_ledger.py`) to report spend in notifications.
  Measured comparison of per-line vs batched synthesis (requests,
  tokens, wall time, alignment error):
  `docs/REQUEST_EFFICIENCY.md` — raw numbers in
  `out/archive/reqeff-measurements.json` (local run artifacts, not
  committed; the distinct audio versions live in `out/archive/`).

```bash
# Owner defaults: single voice Rami, gemini-3.8-flash-lite-tts,
# requests auto-sized to the 90/day reading budget
python3 gemini_readaloud.py --epub "book.epub" --chapter 3 \
    --pace 20 --output out/ch1.epub

# Role cast instead of the single voice
python3 gemini_readaloud.py --epub "book.epub" --chapter 3 \
    --cast --pace 20 --output out/ch1.epub
```

A slice larger than the daily quota allows (observed 100 requests/day)
takes several days (each daily run synthesizes what the quota allows,
then resumes the next day); paid tier removes the limit.

### Where read-along actually works

| Reader | Media Overlays (reflowable) | Media Overlays (fixed layout) |
|---|---|---|
| Apple Books (iPhone + Mac) | No — opens the book, ignores the overlay | Yes — use `epub_fixedlayout.py` |
| Thorium Reader (Mac/Win/Linux, free) | Yes — the reference test player | Yes |
| Kobo Books / Adobe Digital Editions (iOS) | Yes (per current reports) | Yes |
| Readest | No | No |

Test on the Mac with Thorium Reader (https://www.edrlab.org/software/thorium-reader/):
open the EPUB, press play — sentences highlight in yellow as Giuseppe reads.

## epub_fixedlayout: Apple Books route (fixed layout)

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

### Parallel synthesis

All engines synthesize with `--workers` concurrent edge-tts requests
(default 4; `--workers 1` restores the old sequential behavior). Segment
order — and therefore the concatenation offsets and SMIL clips — is
preserved regardless of worker count. On the 7-line demo book the synthesis
stage dropped from ~13s to ~2s with 4 workers; a full book is expected to
drop from ~1.5-2h to roughly 30-40 min. Unit tests with a mocked
synthesizer: `tests/test_parallel_synth.py`.

### Device QA (Apple Books)

1. `python3 epub_fixedlayout.py --demo --output out/fx_demo.epub`
2. AirDrop/transfer the file to iPhone (or open on Mac), then open in Apple
   Books — a read-aloud play control should appear.
3. If text overflows a page, lower `--chars-per-page` (e.g. 700) or raise
   `--viewport`; if it looks too sparse, raise the budget.
4. For a real chapter: `--chapter 4 --slice 4000` first, then `--all`.

Known trade-off: fixed layout means no user-adjustable font size, and page
breaks are estimated from character counts, not rendered text. Expect one
tuning round of `--chars-per-page` per book after looking at it on device.

## Setup

### 1. Get a Mistral API key

1. Go to https://console.mistral.ai and sign in / create an account.
2. Under **API Keys**, create a new key (copy it — shown once).
3. Add credit / a plan if prompted (TTS + chat completions are billed per use).
4. Store it in `.env` (gitignored):
   ```
   MISTRAL_API_KEY=your-key-here
   ```
   Or export in shell: `export MISTRAL_API_KEY="your-key-here"`

### 2. Install dependencies

```bash
pip3 install -r requirements.txt
brew install ffmpeg   # needed for audio concatenation with crossfades
```

### 3. Configure voices

Edit `voices.json` to map voice profiles to Voxtral voices. Two styles are available:

- **`basic`**: Single voice for all text. Set `default_voice_id` to a preset voice ID.
- **`enhanced`**: Multi-voice with emotional variety. Maps `profile:emotion` pairs to different preset voices. Falls back to `fallback_by_profile`, then `default_voice_id`.

To find available voice IDs:
```bash
python3 poc_reader.py --list-voices
```

There are 30 preset voices: Paul (male, en_us, 8 emotions), Oliver (male, en_gb, 7 emotions), Jane (female, en_gb, 7 emotions), Marie (female, fr_fr, 6 emotions).

## Usage

### Generate audio from a sample

```bash
python3 poc_reader.py --sample english_fiction --style basic
python3 poc_reader.py --sample english_fiction --style enhanced
python3 poc_reader.py --sample italian_fiction --style enhanced
```

### Generate audio from custom text

```bash
python3 poc_reader.py --text "Your custom text here" --style basic
```

### Generate audio from an EPUB

```bash
# List chapters
python3 poc_reader.py --epub "samples/Book.epub" --list-chapters

# Generate a chapter
python3 poc_reader.py --epub "samples/Book.epub" --chapter 5 --style basic --output-dir out/book_ch5

# Generate with enhanced voices
python3 poc_reader.py --epub "samples/Book.epub" --chapter 5 --style enhanced --output-dir out/book_ch5_enhanced
```

### Play with synced highlighting

The player needs HTTP (browser security blocks local file access):

```bash
python3 -m http.server 8000
```

Open `http://localhost:8000/poc_player.html` in your browser.

The player has:
- **Sample dropdown**: switch between English Fiction and Italian Fiction
- **Basic / Enhanced toggle**: compare single-voice vs multi-voice with emotions
- **Voice name tag** per segment (shown in Enhanced mode)
- **Click any segment** to jump to that point in the audio
- **Speed control**: cycle through 0.75x, 1.0x, 1.25x, 1.5x, 2.0x

### All CLI options

```
python3 poc_reader.py --help

Options:
  --sample SAMPLE        Sample name (e.g. english_fiction)
  --text TEXT            Custom text to process
  --epub PATH            Path to an EPUB file to read
  --chapter N            Chapter index in the EPUB
  --list-chapters        List chapters in the EPUB (requires --epub)
  --style STYLE          Voice style: 'basic' or 'enhanced' (default: enhanced)
  --max-chars N          Max chars per LLM analysis chunk (default: 4000)
  --output-dir DIR       Output directory (default: out/)
  --list-voices          List saved voices in your Mistral account
```

## Output files

All outputs go to the specified `--output-dir` (default: `out/`):

| File | Description |
|---|---|
| `poc_output.mp3` | The final concatenated audio |
| `poc_manifest.json` | Segment metadata + audio offsets (used by the player) |
| `reading_script.json` | The LLM's full analysis (inspect what the AI decided) |
| `seg_NNN.mp3` | Individual segment audio files |

## How it works

1. **Load**: Text from a sample file, custom string, or EPUB chapter.
2. **Chunk**: Long texts are split at paragraph boundaries (max 4000 chars per chunk).
3. **Analyze**: Each chunk is sent to `mistral-large-latest` with a prompt that instructs it to break the text into segments, detect language, identify speakers, assign emotion/pace/pitch/voice_profile, and produce a `speakable_text` field (numbers spelled out, abbreviations expanded, quotation marks removed, natural pause commas added).
4. **Map voices**: Each segment's `voice_profile` + `emotion` is looked up in `voices.json` to find a `voice_id`.
5. **Synthesize**: Each segment's `speakable_text` is sent to the Voxtral TTS API (`voxtral-mini-tts-2603`) with the mapped voice. Content moderation 403s are caught and skipped. Rate limits retry with exponential backoff.
6. **Concatenate**: Segments are joined with 40ms crossfades and 150ms silence gaps using pydub/ffmpeg. Falls back to binary concatenation if ffmpeg is unavailable.
7. **Manifest**: A JSON manifest maps each segment to its audio start/end offset for synced playback.

## Cost & time estimates

Based on testing with Guns, Germs, and Steel (~1M chars, 24 content chapters):

| Metric | Value |
|---|---|
| TTS cost | $16 per million characters |
| LLM cost (analysis) | ~$11 per million chars of text |
| Total for a full book | ~$28 |
| Time (sequential) | ~26 hours |
| Time (3 parallel workers) | ~9 hours |
| Audio length | ~21 hours |
| Commercial audiobook (Audible) | $15-30 |

The cost is comparable to buying a commercial audiobook, with the added benefit of synced text, voice control, and the ability to regenerate any section.

## Supported languages

Voxtral TTS supports: **English, French, German, Spanish, Dutch, Portuguese, Italian, Hindi, Arabic**.

Danish is NOT supported. Italian works via cross-lingual transfer but quality is noticeably worse than English.

## Voice styles

### Basic
Single voice (Paul - Neutral by default) for all text. Best for nonfiction and long-form reading where character distinction is not needed.

### Enhanced
Multi-voice with emotional variety. The LLM assigns a `voice_profile` and `emotion` per segment, and the voice mapping selects a different preset voice for each combination:

| Character type | Emotion | Voice used |
|---|---|---|
| Narrator (warm) | calm/convinced | Paul - Confident |
| Narrator (warm) | tense | Paul - Frustrated |
| Narrator (warm) | sad | Paul - Sad |
| Female (soft) | tense | Jane - Frustrated |
| Female (soft) | sad | Jane - Sad |
| Male (rough) | tense/neutral | Paul - Frustrated |
| Male (soft) | soft/sad | Oliver - Sad |
| Technical | neutral | Paul - Neutral |

Enhanced is more expressive but can feel over-emphasized for nonfiction. Basic is recommended for reading nonfiction books.

## Project structure

```
tts-ereader/
├── poc_reader.py          # Main pipeline script (CLI, Voxtral engine)
├── edge_reader.py         # edge-tts hybrid engine (LLM prep + free edge voices)
├── benchmark_tts.py       # TTS engine benchmark harness (owner-run, real keys)
├── Dockerfile             # Multi-stage image: frontend build + FastAPI runtime (M4)
├── docker-compose.yml     # Homelab deployment: port 8000, ./data volume, healthcheck (M4)
├── epub_mo.py             # EPUB 3 Media Overlays generator (overlays on original XHTML)
├── epub_readaloud.py      # Simple read-along EPUB from prepared text (recommended)
├── epub_fixedlayout.py    # Fixed-layout read-along EPUB (Apple Books route)
├── poc_player.html        # Web player with synced highlighting + style toggle
├── tests/                 # v0 unit tests (python3 -m unittest discover tests)
│   └── fixtures/make_fixture_epub.py  # Synthetic EPUB generator (no copyrighted books)
├── shared/                # text preparation + voice cast shared by v0 CLIs and the v1 app (M3)
├── backend/               # v1 reader app (M1–M3 — see docs/ARCHITECTURE_v1.md)
│   ├── app/               # FastAPI: library/reader/TTS API, EPUB parser, TTS engines
│   └── tests/             # pytest unit + integration tests
├── frontend/              # v1 reader UI (Svelte 4 + Vite + TypeScript)
│   ├── src/lib/pages/     # Library and Reader pages
│   ├── src/lib/components/# BookCard, ChapterNav, SettingsPanel, VoicePanel, SentenceContent
│   └── src/lib/           # api client, settings/tts stores, audio engine, sync, sentence utils
├── voices.json            # Voice profile → voice_id mapping (basic + enhanced)
├── requirements.txt       # Python dependencies (mistralai, pydub, mutagen)
├── .env                   # API key (gitignored, you create this)
├── samples/               # Sample text files + EPUBs
│   ├── english_fiction.txt
│   ├── italian_fiction.txt
│   ├── danish_fiction.txt
│   ├── danish_technical.txt
│   └── *.epub
├── voices/                # Reference audio clips (for voice cloning, you provide)
└── out/                   # Generated output (gitignored)
    ├── english_basic/
    ├── english_enhanced/
    ├── italian_basic/
    ├── italian_enhanced/
    └── ggs_ch3/           # Guns, Germs, and Steel preface
```

## v1 reader app (M1–M4: library + reader, TTS + read-along, voice tuning + LLM preparation, Docker + benchmark + docs)

The v1 app is in `backend/` (FastAPI + SQLite via SQLModel) and `frontend/`
(Svelte 4 + Vite + TypeScript), per `docs/ARCHITECTURE_v1.md`. M1 delivers:

- EPUB import with metadata, cover extraction, and spine-ordered chapter
  indexing; library list/get/delete; per-book progress persistence.
- Library UI: import via file picker or drag & drop, cover cards with
  progress bars, remove.
- Reader UI: chapter navigation, fonts (family, size 8–32pt, weight,
  line-height 1.0–2.5), themes (light/dark/sepia/custom colors), continuous
  scroll and paginated modes with toggle, auto-advance/auto-scroll with
  configurable speed, progress saved per book and restored on open,
  lang-aware hyphenation for European typography.

M2 adds TTS and the voice-by-progression read-along:

- Pluggable `TTSEngine` interface (`backend/app/engines/`): Gemini TTS
  adapter (primary, REST, PCM wrapped as WAV) and edge-tts adapter (free
  fallback, word-boundary timestamps, MP3 normalized to WAV via pydub/ffmpeg
  when available). Engines are looked up through a factory with automatic
  fallback (requested engine first, then Gemini, then edge-tts).
- TTS API: `GET /api/tts/engines`, `GET /api/tts/engines/{name}/voices`,
  `POST /api/tts/synthesize`, `POST /api/tts/synthesize-batch`. All synthesis
  is cached on disk under `data/audio_cache/` keyed by engine+voice+params+
  text hash, so re-reading is instant.
- Reader read-along: the chapter is split into sentences (Italian/Danish
  abbreviations, quotes, dialogue dashes handled); tapping any sentence
  synthesizes a window from there and reads aloud ("tap-to-read"); the spoken
  sentence is highlighted and the view follows the voice (scroll or page
  turn); manual scroll/page-turn repositions the voice; when the voice
  finishes the chapter it auto-advances to the next one (toggleable). Playback
  rate 0.5x–2x is applied client-side via Web Audio `playbackRate`.
- Per-book voice settings (engine, voice, rate, auto-advance) in the reader's
  Voice panel, persisted to localStorage per book.

M3 adds voice tuning and the LLM preparation pipeline:

- Voice panel: engine + voice selection, rate 0.5x–2x (client-side), pitch
  -20..+20 (baked into synthesis), a "Test this voice" button, and a per-book
  voice cast. The cast is seeded from engine+language defaults (Italian
  edge-tts: Giuseppe/Vivienne/Emma/Andrew; Danish edge-tts: Jeppe/Christel;
  Gemini: Charon/Kore/Leda/Puck) and every role can be overridden per book;
  settings persist per book in localStorage.
- With the cast enabled, the chapter is prepared through the same Mistral
  pipeline as the v0 CLIs (`shared/text_preparation.py`: clean +
  repunctuate + speaker tagging, with Italian (Saramago), Danish
  (Adler-Olsen), and generic prompts), cached on disk per book+chapter so
  it is never re-billed, and the prepared lines become the display and
  playback unit: each character reads with their own voice, speaker labels
  are shown inline, and tap-to-read/highlight/follow-voice work per line.
- Preparation API: `POST /api/books/{id}/chapters/{n}/prepare` (LLM + cast
  resolution; 503 without `MISTRAL_API_KEY`), `GET .../prepared` (cache
  only), `GET /api/tts/cast-defaults`; `synthesize-batch` accepts per-text
  voices.
- The v0 CLIs now import preparation + cast logic from `shared/`; their
  surface and Italian cast output are pinned by `tests/test_v0_compat.py`.

Gemini TTS needs `GEMINI_API_KEY` in `.env`; without it the engine shows as
unavailable and synthesis falls back to edge-tts automatically. LLM
preparation needs `MISTRAL_API_KEY`; without it the cast toggle reports the
error and the reader falls back to plain single-voice narration. Live Gemini
synthesis was verified by the owner on 2026-09-19 for Italian and Danish
(short texts, voice Kore) and on 2026-09-29 for English (Guns, Germs, and
Steel chapter 1 opening, ~1,100 chars, voices Kore and Charon); the
sandbox only exercises engines through mocks plus free edge-tts smoke tests.

Known limitation (seen live 2026-09-29): `GeminiTTSEngine`'s httpx client
uses a 30 s read timeout, which is too tight for requests beyond roughly
1,000 characters — the same ~1,100-char sample succeeded with Kore but
timed out twice with Charon until retried with a 120 s client (the engine
accepts an injectable `client`). Batch generation should chunk to short
lines (the prepared-lines pipeline already does) or raise the timeout.
Transient malformed responses (seen live 2026-10-01, issue #15): Gemini
sometimes answers 200 with a candidate that has no `content`; re-sending
the identical request succeeds. `GeminiTTSEngine.synthesize()` retries up
to 2 extra times (2 s / 4 s backoff, configurable via `retry_delays`) and
logs the discarded response shape (finishReason, candidate keys,
promptFeedback) at WARNING on the `tts_ereader.gemini` logger before each
retry, so incidents are diagnosable.
Gemini TTS on an AI Studio key has a hard per-day request quota
(observed limit: 100 requests/day per model, 2026-10-06; earlier
observed ~10/day — the number has changed before) plus a small
per-minute bucket — a full book at line granularity needs the
cache-resume across days; use `gemini_readaloud.py`'s cache-resume
for quota-limited slices (see above).

```bash
pip3 install -r requirements.txt -r requirements-dev.txt

# Run the backend test suite (unit + integration, <1s)
python3 -m pytest backend/tests -q

# Generate synthetic test EPUBs (never commit real books)
python3 tests/fixtures/make_fixture_epub.py --out-dir /tmp/epubs

# Development: backend on :8000, frontend dev server on :5173 (proxies /api)
cd backend && python3 -m uvicorn app.main:app --reload
cd frontend && npm install && npm run dev

# Frontend unit tests (Vitest) and type check
cd frontend && npm test && npm run check

# Production-style single server: build the frontend, then run the backend;
# it serves frontend/dist at http://localhost:8000 (data lives in ./data
# or $TTSEREADER_DATA_DIR)
cd frontend && npm run build
cd .. && python3 -m uvicorn app.main:app --app-dir backend
```

M4 makes it deployable and benchmarkable:

- Docker deployment for the homelab: multi-stage `Dockerfile` (frontend
  bundle → `python:3.11-slim` + ffmpeg runtime) and `docker-compose.yml`
  with a single `./data` bind mount for all persisted state, `.env`
  passthrough, healthcheck, and `restart: unless-stopped`. Runbook:
  `docs/DEPLOYMENT.md`.
- Enriched `GET /api/health`: version, data-dir writability, default
  engine, and per-engine availability — always 200 while the process is
  up, degraded states in the body.
- Benchmark harness (`benchmark_tts.py`, owner-run with real keys): the
  same Italian/Danish passages through every engine and voice, one audio
  file per combination for A/B listening, and wall-time vs audio duration
  against the acceptance budgets (edge-tts < 2x, Gemini < 1.5x). Covered
  in the sandbox by unit tests against the mock engine.
- Offline indicator in the app shell (red banner when the server is
  unreachable).
- Docs: `docs/DEPLOYMENT.md` (homelab runbook), `docs/USER_GUIDE.md`,
  `docs/DEVELOPER_GUIDE.md`.

The Docker image itself was not built in the cloud sandbox (no Docker
daemon, 30s command limit) — the first `docker compose up -d --build` on
the homelab is the owner's smoke test.

## Technical notes

- The Mistral Python SDK (1.10.0) does not yet include the TTS/voice endpoints, so `poc_reader.py` calls the REST API directly for speech generation (`POST /v1/audio/speech`) and voice listing (`GET /v1/audio/voices`). The SDK is used for chat completions (LLM analysis).
- TTS pricing: $16 per million characters.
- The model generates up to 2 minutes of audio per request; longer text is split automatically by the API.
- Content moderation: some text may be rejected with HTTP 403. The script catches these and skips the segment.
- EPUB extraction uses Python's built-in zipfile + html.parser — no extra dependencies needed.
- Text chunking splits at paragraph boundaries to avoid cutting mid-sentence.

## Next steps (Phase 2)

The PoC is validated. The next phase would be:

1. ~~**Batch generation script**: Process all chapters of a book in the background, with parallel TTS workers to cut time from ~26h to ~9h.~~ Done for the edge-tts engines: `--workers` (default 4) on all EPUB scripts; full-book generation is `--all`.
2. **Web app (PWA)**: Chapter list with generation status, continuous text view with sentence-level highlighting, playback controls, progress tracking across chapters.
3. **Backend**: Local FastAPI server that serves chapter list, triggers generation, and serves audio + manifests to the frontend.
4. **On-demand generation**: User clicks a chapter, it generates in the background, becomes available when done.
