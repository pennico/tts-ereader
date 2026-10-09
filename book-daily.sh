#!/bin/bash
# Daily growing-book reading (owner decision, 2026-10-09): one Gemini
# quota window per day, the next unread chapter with the 400-char
# method, appended to the single growing EPUB — old reads are never
# re-synthesized (segment cache), one output file for the whole book.
#
# Trigger: the scheduled GitHub Action (.github/workflows/
# book-daily.yml) files a `run`-labeled issue; the pennico-ops
# dispatcher executes this script directly in the repo root (no LLM
# session). The Action is DISABLED until the repository variable
# TTS_BOOK_DAILY is set to "enabled" — the owner arms it explicitly.
#
# Exit codes: 0 = a successful day (chapter(s) read, budget spent, or
# book complete); non-zero = a real failure (the dispatcher files a
# blocker). Gemini's resumable quota abort (exit 75 from the engine)
# is a SUCCESS here: the budget did its job for today.
set -u
cd "$(dirname "$0")"

# APPROACH (owner decision, 2026-10-09): prepared = LLM repunctuation
# (best for normal books); loyal = the author's text verbatim,
# footnotes out, one request per paragraph/segment (box method, best
# quality for authors whose rhythm IS the work, e.g. Saramago).
APPROACH=${APPROACH:-prepared}
EPUB=out/archive/saramago.epub
WORK=out/readings/$APPROACH-gemini38/work
OUT=out/readings/$APPROACH-gemini38/readalong-saramago-full.epub
MODEL=gemini-3.8-flash-lite-tts
BATCH_CHARS=400        # the 400-char method: near-zero recitation blocks
DAILY_BUDGET=90       # of the observed 100/day; margin kept for ad-hoc tests
MIN_USEFUL=5          # below this, not worth starting a chapter today
FIRST_CH=3           # spine: 0-2 front matter, 3 = book chapter 1
LAST_CH=20           # spine index of the last real chapter
LEDGER=out/quota_ledger.json
LOG=out/book-daily.log

if ! grep -q -- "--batch-chars" gemini_readaloud.py 2>/dev/null; then
  echo "engine lacks the 400-char method: merge tts-ereader PR #41 first" >&2
  exit 1
fi
if ! grep -q -- "--prepare-mode" gemini_readaloud.py 2>/dev/null; then
  echo "engine lacks the loyal mode: merge the loyal-mode PR first" >&2
  exit 1
fi

# Next unread chapter: the highest completed chapter's spine index + 1
# (completed = persisted artifacts in the work dir, written only when a
# chapter's synthesis finished).
next=$(python3 - "$WORK" "$FIRST_CH" <<'PY'
import json, sys
from pathlib import Path
work, first = Path(sys.argv[1]), int(sys.argv[2])
done = sorted(int(json.loads((d / "chapter.json").read_text())["idx"])
              for d in work.glob("ch*") if (d / "chapter.json").is_file())
print(done[-1] + 1 if done else first)
PY
)
if [ "$next" -gt "$LAST_CH" ]; then
  echo "BOOK COMPLETE: chapters ${FIRST_CH}-${LAST_CH} are all read."
  echo "Disable the schedule: gh variable delete TTS_BOOK_DAILY -R pennico/tts-ereader"
  exit 0
fi

# Requests left today from the quota ledger (0 requests are spent on
# fully cached re-runs, so the ledger tracks real spend only).
remaining=$(python3 - "$LEDGER" "$MODEL" "$DAILY_BUDGET" <<'PY'
import sys
sys.path.insert(0, ".")
from shared.quota_ledger import day_totals
ledger, model, budget = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    spent = day_totals(ledger, model=model)["requests"]
except Exception:
    spent = 0
print(max(0, budget - spent))
PY
)
if [ "$remaining" -lt "$MIN_USEFUL" ]; then
  echo "daily budget already spent (${remaining} left); nothing to do today"
  exit 0
fi

while [ "$next" -le "$LAST_CH" ] && [ "$remaining" -ge "$MIN_USEFUL" ]; do
  echo "=== $(date -u '+%Y-%m-%d %H:%M UTC') chapter $next, $remaining requests left today ===" | tee -a "$LOG"
  if [ "$APPROACH" = "loyal" ]; then
    # Loyal: one request per paragraph/segment (box method) — the
    # owner's per-paragraph quality choice; --batch-chars 0 disables
    # batching so each segment is its own request.
    BATCH_ARGS="--batch-chars 0 --daily-requests 0"
  else
    BATCH_ARGS="--batch-chars $BATCH_CHARS"
  fi
  python3 gemini_readaloud.py --epub "$EPUB" --chapter "$next" \
      --single Rami --model "$MODEL" --prepare-mode "$APPROACH" \
      $BATCH_ARGS --max-requests "$remaining" \
      --growing --work-dir "$WORK" --output "$OUT" >> "$LOG" 2>&1
  rc=$?
  if [ "$rc" -eq 75 ]; then
    # Budget reached mid-chapter: resumable, the growing EPUB already
    # carries everything read so far. A spent budget is a good day.
    echo "budget reached mid-chapter $next (resumable); continuing tomorrow" | tee -a "$LOG"
    break
  elif [ "$rc" -ne 0 ]; then
    echo "chapter $next FAILED (exit $rc); see $LOG" | tee -a "$LOG"
    exit "$rc"
  fi
  echo "chapter $next done" | tee -a "$LOG"
  next=$((next + 1))
  remaining=$(python3 - "$LEDGER" "$MODEL" "$DAILY_BUDGET" <<'PY'
import sys
sys.path.insert(0, ".")
from shared.quota_ledger import day_totals
ledger, model, budget = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    spent = day_totals(ledger, model=model)["requests"]
except Exception:
    spent = 0
print(max(0, budget - spent))
PY
)
done

# Share the updated growing EPUB: the host publish-watcher (cron */5)
# picks the flag up and copies the file to Nextcloud.
FLAGS=../.publish-flags/tts-ereader
if [ -d "$(dirname "$FLAGS")" ] && [ -f "$OUT" ]; then
  echo "book-daily" > "$FLAGS"
  echo "publish flag dropped: $FLAGS"
fi
echo "growing EPUB: $OUT ($(date -u '+%H:%M UTC'))"
