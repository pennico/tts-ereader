#!/bin/bash
# One-shot: request-efficient read-along EPUBs for chapters 1-3 of the
# Saramago test book, Rami/Kore cast, --lines-per-request 10 (issue #25).
# Idempotent/resumable: finished chapter EPUBs are skipped and cached
# lines cost nothing, so re-runs never re-spend quota on work already
# done. Self-removes from crontab on full success (see the delivering
# PR's Handoff for the exact crontab lines).
#
# Model: gemini-3.8-flash-lite-tts — owner decision (issue #30 answer):
# a different model with a different request quota than
# gemini-3.8-flash-tts was chosen for the scheduled run. Override in
# one line via the environment if the owner-side session is told
# otherwise (TTS_CH13_MODEL=gemini-3.8-flash-tts).
set -u
LOG=/home/nicola/tts-ch13-efficient.log
MODEL="${TTS_CH13_MODEL:-gemini-3.8-flash-lite-tts}"
LINES_PER_REQUEST="${TTS_CH13_LINES_PER_REQUEST:-10}"

notify() {
  docker exec -i agent-runner python3 - "$1" "$2" <<'PYEOF'
import os, sys, urllib.request
title, body = sys.argv[1], sys.argv[2]
req = urllib.request.Request(
    os.environ["NTFY_SERVER"] + "/" + os.environ["NTFY_TOPIC"],
    data=body.encode(), headers={"X-Title": title, "X-Priority": "3"})
try:
    urllib.request.urlopen(req, timeout=10).read()
except Exception as e:
    print("ntfy notify failed (not fatal):", e)
PYEOF
}

# Failure feedback loop: failures file a diagnosis task issue on the repo
# (an agent session picks it up); success closes any open auto-issues.
feedback() {
  docker exec -i agent-runner python3 \
    /app/projects/pennico-ops/dispatcher/feedback.py "$@"
}

EPUB=/app/projects/tts-ereader/out/voice_tests/saramago.epub
OUTDIR=/app/projects/tts-ereader/out
LEDGER=/app/projects/tts-ereader/out/quota_ledger.json

echo "=== $(date) ch1-3 efficient run (model=$MODEL, lines-per-request=$LINES_PER_REQUEST) ===" >> "$LOG"

# Chapter indices 3,4,5 are the first three real chapters (0-2 = front matter)
for ch in 3 4 5; do
  n=$((ch-2))
  OUT="$OUTDIR/readalong-ch${n}.epub"
  if [ -s "$OUT" ]; then
    echo "ch${n}: $OUT already present - skipping" >> "$LOG"
    continue
  fi
  docker exec agent-runner python3 /app/projects/tts-ereader/gemini_readaloud.py \
       --epub "$EPUB" --chapter "$ch" \
       --narrator Rami --voice-m Rami --voice-f Kore \
       --model "$MODEL" --pace 20 \
       --lines-per-request "$LINES_PER_REQUEST" \
       --work-dir /app/projects/tts-ereader/out/gemini_readaloud_work \
       --output "$OUT" >> "$LOG" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "ch${n} OK" >> "$LOG"
  elif [ "$rc" -eq 75 ]; then
    # Exit 75 = Gemini daily quota exhausted mid-chapter: resumable, not
    # a failure (tts-ereader issue #21). Cached lines are skipped on the
    # next run, so keep the crontab line and retry on the next fire.
    echo "ch${n}: daily quota reached - resumable, retrying on the next cron fire" >> "$LOG"
    notify "tts-ereader ch1-3 progress" "Gemini daily quota reached in chapter ${n} (model ${MODEL}); progress is cached. The job retries on the next cron fire (every 30 min until 08:30, then tomorrow 02:30 CET)."
    exit 0
  else
    echo "ch${n} FAILED (exit ${rc})" >> "$LOG"
    notify "tts-ereader ch1-3 failed" "Chapter ${n} (index ${ch}) failed - agents notified, see /home/nicola/tts-ch13-efficient.log."
    tail -50 "$LOG" | feedback report --source tts-ch13-efficient --repo tts-ereader \
      --title "ch1-3 efficient read-along failed at chapter ${n}" --tail - >> "$LOG" 2>&1
    exit 1
  fi
done

# Success: publish, close auto-issues, report the day's measured spend.
/opt/services/agent-runner/homelab/publish_tts-ereader_outputs.sh >> "$LOG" 2>&1
feedback resolve --source tts-ch13-efficient >> "$LOG" 2>&1
SPEND=$(docker exec agent-runner python3 -c "
import sys
sys.path.insert(0, '/app/projects/tts-ereader/shared')
import quota_ledger
t = quota_ledger.day_totals('${LEDGER}', model='${MODEL}')
print('{} requests, {} tokens today'.format(t['requests'], t['tokens']))
" 2>> "$LOG")
notify "tts-ereader ch1-3 done" "Read-along EPUBs ch1-3 (Rami/Kore, ${MODEL}, ${LINES_PER_REQUEST} lines/request) ready: calibre-web (Tailscale :8452) and Nextcloud tts-ereader/. Spend: ${SPEND:-n/a (ledger)}."
(crontab -l | grep -v tts-ch13-efficient-run) | crontab -
echo "=== done, cron line self-removed ===" >> "$LOG"
