# Request-efficient synthesis (issue #25)

The quota that blocks chapter read-along runs on Gemini TTS is the
per-day **request count** (100/day per model on `gemini-3.8-flash-tts`,
billing active — the limit is per model, not per key), not tokens. The
per-line "box method" makes one short request per prepared line, so a
single chapter (ch1 of the Saramago test book = 117 prepared lines)
spends more than a day's whole bucket. This note records what was
considered, what was measured, and the recommended configuration.
Measured numbers (requests, tokens, wall time, per-boundary alignment
error) are in `out/voice_tests/reqeff-measurements.json` (local run
artifacts, gitignored; listenable sample WAVs alongside). The
`gemini-2.5-flash-preview-tts` entries in that file predate the
model's retirement and are not used below; all numbers cited here are
from `gemini-3.8-flash-lite-tts`.

**Owner decision (issue #30 answer, 2026-10-06):** the scheduled ch1-3
run uses `gemini-3.8-flash-lite-tts` — a different model with a
different request quota than `gemini-3.8-flash-tts` — and tomorrow's
run is a new, lower-demand request on the gemini 3.8 family. No
re-measurement on `gemini-3.8-flash-tts` is needed; the flash-lite
numbers below are the basis of the recommendation.

## Approaches considered

| Approach | Requests for ch1-3 (513 lines) | Verdict |
|---|---|---|
| Per-line (box method, status quo) | 513 | Works today only via multi-day cache resume; one chapter per day at best |
| Batch N lines per request (`--lines-per-request N`) | ceil(513/N) + fallbacks | **Chosen** — keeps per-line casting, caching, and SMIL granularity |
| Same-voice-only batching (no multi-speaker) | depends on dialogue density; splits at every voice change | Rejected as the primary mode: request count stays unbounded for dialogue-heavy chapters; kept implicitly (a batch never mixes >2 voices) |
| Non-TTS `gemini-3.8-flash` (10k req/day) for synthesis | — | **Not possible**: TTS audio output requires the TTS models; the non-TTS models return no AUDIO modality. No real use for synthesis. (A non-TTS model could pre-screen lines likely to hit the copyright recitation filter, but that would cost Mistral-free requests to save rare fallbacks — not worth it.) |
| Coarser SMIL (one highlight per batch) | ceil(513/N) | Rejected: changes what the read-along means — highlighting would jump N paragraphs at once |
| Silence-detection alignment of batch audio | ceil(513/N) + fallbacks | Chosen (this is the batching design): the batch take is split back into per-line segments at silence gaps, so offsets stay per-line |

## How batching works (`gemini_readaloud.py --lines-per-request N`)

- Lines are grouped into consecutive batches of N; each batch is split
  into voice-compatible sub-batches (the Gemini multi-speaker API
  requires **exactly 2** `speakerVoiceConfigs` — measured live
  2026-10-06: a 1-speaker config is a 400 error).
- A 2-voice sub-batch is sent as one labeled multi-speaker conversation
  (`Rami: <line>` / `Kore: <line>`, with a minimal "read the
  conversation, do not read the labels" instruction); a 1-voice
  sub-batch is sent as a plain multi-paragraph request (the box
  method, no style prefix).
- The single take is cleaned (`shared/audio_clean.py`) and split back
  into one segment per line at silence gaps: boundary candidates are
  silence runs >= 200 ms; each boundary is placed at the gap closest
  to the position proportional to cumulative text length (optimal
  monotone assignment), and the split is accepted only if every
  boundary is within max(1.5 s, 35% of the average line duration) and
  every segment is at least 0.25 s. Otherwise the batch falls back to
  per-line synthesis — a few extra requests beat silently misaligned
  highlighting.
- Per-batch cache keys make runs resumable; a batch whose lines are
  all already in the per-line cache (earlier box-method runs) is
  stitched from that cache with **zero** new requests.
- The recitation-filter sentence-splitting and the exit-75 daily-quota
  abort are unchanged (both reachable via the per-line fallback).

## The prosody tradeoff

Batching trades isolation for continuity. Per-line requests give each
line a fresh, self-contained delivery (the validated box method) at one
request per line. A batch is read as one continuous take: pacing across
lines becomes coherent — arguably better for Saramago's long narration —
but the model sees a longer prompt, the voice assignment for dialogue
depends on the model honoring the labels, and a single bad generation
affects up to N lines (mitigated by the per-batch fallbacks). Alignment
of the SMIL offsets is approximate (silence-gap based) rather than
exact: measured per-boundary error is in
`out/voice_tests/reqeff-measurements.json` (the `alignment` key);
per-line requests have exact offsets by construction.

## Recommendation

`--lines-per-request 10` for the scheduled ch1-3 run:

- Measured prepared lines: ch1 = 117, ch2 = 133, ch3 = 263 (513 total).
- Worst case 53 requests — half the 100/day budget; with ch1 already
  ~fully cached per-line from earlier runs, ~43.
- Wall time on `gemini-3.8-flash-lite-tts` (measured 2026-10-06,
  20-line ch1 slice): batch10 = 2 requests, 44.0 s wall; batch20 =
  1 request, 26.6 s wall — both well inside the engine's 120 s read
  timeout. (An earlier draft of this note argued batch20 was "closer
  to the read timeout" from retired 2.5-preview-tts timings; that
  model is retired and the claim is withdrawn — on the 3.8 numbers
  it does not hold.)
- Alignment on the same slice: batch10 = 1 of 2 takes unalignable
  (falls back to per-line), boundary drift up to 9.7 s on the other;
  batch20 = 0 fallbacks, drift up to 7.7 s; batch5 = 1 of 4
  fallbacks, drift up to 5.8 s. One 20-line slice is too small to
  rank batch sizes on alignment; the fallback keeps highlighting
  correct, but an accepted batch can still drift a few seconds
  against per-line ground truth.

N=10 stays the recommendation: 53 requests already fit the day's
budget with headroom for fallbacks, and a smaller batch bounds how
many lines one bad take affects. On the measured 3.8-flash-lite
slice batch20 was no slower and did not fall back, so N=20 is a
reasonable choice for big books on a tight budget — the earlier
timeout-based argument against it is withdrawn.

If a future run needs to fit a bigger book into the same budget, raise N
(the flag is the only knob); if alignment fallbacks ever dominate,
lower it.
