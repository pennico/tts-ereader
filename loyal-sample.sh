#!/bin/bash
# One-shot loyal-mode sample (owner decision, 2026-10-09): the first
# paragraphs of book chapter 1, verbatim Saramago — footnotes out, one
# request per <=300-char piece (sentence then clause boundaries).
# Published to Nextcloud out/listening for the owner to judge the
# approach BEFORE the full loyal schedule is armed.
#
# Trigger: the scheduled GitHub Action (loyal-sample.yml) files a
# `run` issue; the ops dispatcher executes this script in the repo
# clone inside the agent-runner container (no LLM session).
#
# One-shot: the schedule fires only while the repository variable
# TTS_LOYAL_SAMPLE = "enabled"; a SUCCESSFUL run deletes the variable
# so it never fires twice. A failed run keeps it armed: the schedule
# retries the next day and the segment cache resumes for free.
set -u
cd "$(dirname "$0")"

MODEL=gemini-3.8-flash-lite-tts
WORK=/tmp/loyal-sample-work      # throwaway: a slice must NOT seed the
OUT=/tmp/loyal-sample.epub       # growing book's work dir (it would
LISTEN=out/listening             # mark ch1 complete while partial)

if ! grep -q -- "--prepare-mode" gemini_readaloud.py 2>/dev/null; then
  echo "engine lacks the loyal mode: merge the loyal-mode PR first" >&2
  exit 1
fi

rm -rf "$WORK" "$OUT"
python3 gemini_readaloud.py --epub out/archive/saramago.epub --chapter 3 \
    --slice 3700 --prepare-mode loyal --single Rami --model "$MODEL" \
    --daily-requests 0 --max-requests 16 \
    --work-dir "$WORK" --output "$OUT"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "sample FAILED (exit $rc); work dir kept, schedule stays armed" >&2
  exit "$rc"
fi

# Share the audio: extract the chapter mp3 from the sample EPUB.
mkdir -p "$LISTEN"
python3 - "$OUT" "$LISTEN/loyal-sample-ch1.mp3" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    audio = sorted(n for n in z.namelist()
                   if n.startswith("audio/") and n.endswith(".mp3"))[0]
    with open(sys.argv[2], "wb") as f:
        f.write(z.read(audio))
print(f"extracted {audio} -> {sys.argv[2]}")
PY

# The mp3 is the keeper; the throwaway artifacts go.
rm -rf "$WORK" "$OUT"

# Publish flag: the host watcher (cron */5) copies out/listening to
# Nextcloud and notifies.
FLAGS=../.publish-flags/tts-ereader
if [ -d "$(dirname "$FLAGS")" ]; then
  echo "loyal-sample" > "$FLAGS"
  echo "publish flag dropped: $FLAGS"
fi

# One-shot: disarm the schedule so tomorrow does not re-run a done
# sample (and does not spend quota the owner wants for own tests).
if command -v gh >/dev/null 2>&1; then
  gh variable delete TTS_LOYAL_SAMPLE -R pennico/tts-ereader \
      && echo "schedule disarmed (TTS_LOYAL_SAMPLE deleted)" \
      || echo "WARN: could not disarm TTS_LOYAL_SAMPLE"
fi
echo "sample published: $LISTEN/loyal-sample-ch1.mp3"
