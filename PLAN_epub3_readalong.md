# Plan: EPUB3 Read-Along Generator (Media Overlays)

Status: planned, not started. Approved approach, pending implementation.
Date of planning: 2026-09-19

## Goal

Turn the existing `edge_reader.py` pipeline into an EPUB3 Media Overlays
("read-along") generator, so Saramago's books (and any Italian EPUB) can be
listened to in Apple Books on iPhone with synced text highlighting, including
playback with the phone locked during commutes.

## Reader support (verified 2026-09)

| Reader | EPUB3 Media Overlays |
|---|---|
| Apple Books (iOS/macOS) | Fixed-layout only — primary target (`epub_fixedlayout.py`); ignores overlays in reflowable EPUBs |
| Thorium Reader (desktop) | Yes — use as validation cross-check |
| Google Play Books | Yes |
| Readest | No (feature-request level; standard file will work if added later) |
| KOReader | No (open feature request) |

Apple Books keeps playing with the screen locked and syncs reading position
via iCloud — this is the reason EPUB3 was chosen over a web/PWA player
(iOS Safari suspends web audio when locked).

## Pipeline design

```
EPUB → [LLM prepare per chapter] → [edge-tts + word timestamps]
     → [fuzzy-align prepared sentences ↔ original XHTML]
     → inject <span id> into original XHTML
     → SMIL overlay per chapter (text#id ↔ audio clipBegin/clipEnd)
     → updated OPF + repackaged .epub → Apple Books
```

Key design decisions:

1. **Displayed text stays the original EPUB.** We only inject invisible
   `<span id>` markers around sentences. The audio is the LLM-prepared
   reading; divergences (cleaned words, re-punctuation) are invisible since
   highlighting is per-sentence span.
2. **Exact clip times for free.** edge-tts emits word-boundary timestamps
   during synthesis — use them for precise `clipBegin`/`clipEnd` per sentence,
   no extra synthesis passes needed.
3. **Alignment is the hard part.** Fuzzy-match prepared sentences back to the
   XHTML sentences (difflib on normalized text), with paragraph-level
   fallback when a sentence does not match. Saramago's unmarked dialogue is
   the main engineering risk.
4. **Footnotes** (Saramago's `[3]` markers): skipped in audio, marked with
   `epub:type` skip so readers do not stall on them.
5. **Voice cast unchanged** (user-approved):
   - Narrator / male characters → `it-IT-GiuseppeMultilingualNeural`
   - First female character → `fr-FR-VivienneMultilingualNeural`
   - Other female characters → `en-US-EmmaMultilingualNeural`
   - Very short male side roles → `en-US-AndrewMultilingualNeural`
     (`--andrew-short`, off by default)
   - Known limitation: multilingual voices can drift into other languages on
     proper nouns; edge-tts has no language-forcing parameter. Mitigations:
     LLM text normalization, per-segment regeneration with phonetic
     respelling, or a `--single-voice` Giuseppe fallback (not yet implemented).

## Implementation phases

| Phase | Work | Effort |
|---|---|---|
| 1 | Sentence alignment + `<span id>` injection into original XHTML | The tricky part; one focused session |
| 2 | SMIL generation + OPF updates + EPUB repackaging (mimetype first, stored) | Mechanical; same session |
| 3 | QA in Apple Books on iPhone + fixes | One short iteration after user QA |

Development does not require the full 2h audio run: validate on a 2–3 minute
chapter slice and check the EPUB structure programmatically. Thorium Reader
serves as a desktop cross-check for MO structure validity.

Estimated total: one session (~1–2h) for phases 1–2, plus one fix round after
real-device QA.

## Costs (per book)

| Item | Cost |
|---|---|
| LLM preparation (mistral-large-latest) | ~$1.50 (under $0.50 with mistral-small-latest) |
| edge-tts synthesis | free |
| Generation time | ~1.5–2h sequential; 30–40 min with parallel synthesis workers (not yet implemented) |

## Delivery architecture (decided)

Apple Books consumes a complete `.epub` — it cannot fetch chapters on demand.
Therefore "at need" applies at the **book level**, not chapter level:

- **Recommended**: Docker service on the homelab server. Drop an EPUB in →
  generates the read-along version in the background → download the `.epub`
  → open in Apple Books. A small FastAPI wrapper + Dockerfile around the same
  pipeline code, built after the generator is validated.
- **Rejected**: per-chapter on-demand generation with a web/PWA player —
  iOS Safari suspends web audio when the phone is locked, which defeats the
  commute use case.
- **Not viable**: running the pipeline in Mistral Studio — it needs Python +
  ffmpeg + calls to Microsoft's edge-tts; Studio can only cover the
  LLM-preparation step.

## Current state (what exists already)

- `edge_reader.py` — working hybrid engine: LLM prepare (clean + repunctuate +
  gender-tagged speaker lines) → voice cast → edge-tts → concatenated audio +
  `poc_manifest.json` (player-compatible). Options: `--rate` (default -8%),
  `--model`, `--max-chars`, `--andrew-short`.
- `poc_player.html` — synced web player, already loads edge output
  ("Saramago — edge hybrid" entry, `out/saramago_edge`).
- Approved sample: `out/saramago_edge/` (Giuseppe + Vivienne, 10 segments).
- Book: "Storia dell'assedio di Lisbona" EPUB, 21 chapters, 259K chars,
  source text verified clean (no OCR errors found).
- `epub_mo.py` — Media Overlays injected into the original XHTML; works,
  94% word match on the test slice, self-validates output.
- `epub_readaloud.py` — simpler variant (fresh EPUB from prepared text);
  recommended reflowable output path.
- **Apple Books blocker addressed (2026-09-19)**: `epub_fixedlayout.py`
  builds a fixed-layout (pre-paginated) read-along EPUB — the variant Apple
  Books will play. Paginates prepared text into fixed-size pages
  (`--chars-per-page`, `--viewport`), one SMIL per page clipping into the
  chapter audio, `rendition:layout`/`rendition:viewport` metadata, and a
  `--demo` mode that builds a tiny test book with no API key for device QA.
  Structure validated programmatically (tests + self-validation); real-device
  QA in Apple Books is pending.

## Next steps (when resuming)

1. ~~Implement phases 1–2~~ done (`epub_mo.py`, `epub_readaloud.py`).
2. ~~Validate on a short chapter slice~~ done (Thorium cross-check passed).
3. User QA of `epub_fixedlayout.py` output in Apple Books on iPhone:
   run `--demo`, then a `--slice 4000` chapter, then `--all`; tune
   `--chars-per-page`/`--viewport` if text overflows or underfills pages.
4. Add parallel synthesis workers (30–40 min per book).
5. Dockerize as the book-level on-demand service for the homelab.
