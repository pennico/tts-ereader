#!/usr/bin/env python3
"""Re-clean the cached Gemini takes of a work dir with the current
shared/audio_clean.py, without new requests (2026-11-28).

The segment cache holds takes already cleaned by the clean_pcm of the
day they were bought. When the cleaning improves (here: the two-part
end burst of gemini-3.8-flash-lite-tts, and level matching between
takes), this rebuilds each take from its cached chunks (the chunks of a
batch are contiguous slices of one cleaned take), cleans it again,
matches its level and splits it again per line. Re-run the chapter
afterwards (same command as the nightly run, --chapter N): every take
is cached, so it re-stitches the audio and SMIL with zero requests.

Prepared mode, single voice only (the Lucidità setup); a take whose
files are not all in the cache (e.g. a recitation-halved batch) is
skipped and reported. A second run cuts nothing more (it may move a
few line boundaries by a few ms).

    python3 reclean_segments.py --work-dir out/readings/lucidita/prepared-gemini38/work \\
        --model gemini-3.8-flash-lite-tts --single Rami --chapters 0,1 [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gemini_readaloud import (
    _batch_key,
    _per_line_seg,
    _split_batch_by_voices,
    split_batch_best_effort,
    split_batch_pcm,
)
from shared.audio_clean import _windows, clean_pcm, match_level, tail_burst_start
from shared.text_preparation import parse_lines, split_long_narration


class _Eng:
    def __init__(self, model):
        self.model = model


def _read(path):
    with wave.open(str(path)) as w:
        return w.readframes(w.getnframes()), w.getsampwidth(), w.getframerate()


def _write(path, pcm, width, rate):
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    tmp.replace(path)


def _has_burst(pcm, width, rate):
    rms, _ = _windows(pcm, width, rate)
    return tail_burst_start(rms) < len(rms)


def reclean_chapter(ch_dir, cache_dir, eng, voice, dry_run=False):
    prepared = (ch_dir / "prepared_text.txt").read_text()
    plan = json.loads((ch_dir / "batches.json").read_text())
    lines = split_long_narration(parse_lines(prepared))
    turns = [(voice, t) for _s, _g, t in lines]
    if sum(plan["counts"]) != len(turns):
        raise SystemExit(f"{ch_dir.name}: batches.json does not match the "
                         "prepared lines; not touching it")
    stats = {"takes": 0, "bursts": 0, "resplit": 0, "estimated": 0,
             "skipped": 0}
    i = 0
    for c in plan["counts"]:
        batch, i = turns[i:i + c], i + c
        for sub in _split_batch_by_voices(batch):
            if len(sub) == 1:
                files = [_per_line_seg(cache_dir, eng, *sub[0])]
            else:
                key = _batch_key(eng, sub)
                files = [cache_dir / f"batch-{key}-{j:03d}.wav"
                         for j in range(len(sub))]
            if not all(f.exists() for f in files):
                stats["skipped"] += 1
                continue
            parts = [_read(f) for f in files]
            width, rate = parts[0][1], parts[0][2]
            take = b"".join(p[0] for p in parts)
            stats["takes"] += 1
            stats["bursts"] += _has_burst(take, width, rate)
            new = match_level(clean_pcm(take, width, rate), width, rate)
            if len(sub) == 1:
                chunks = [new]
            else:
                weights = [len(t) for _v, t in sub]
                chunks = split_batch_pcm(new, width, rate, weights)
                if chunks is None:
                    stats["estimated"] += 1
                    chunks = split_batch_best_effort(new, width, rate, weights)
                old_lens = [len(p[0]) for p in parts]
                if [len(x) for x in chunks] != old_lens:
                    stats["resplit"] += 1
            if not dry_run:
                for f, chunk in zip(files, chunks):
                    _write(f, chunk, width, rate)
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--single", required=True, help="the one voice used")
    ap.add_argument("--chapters", required=True,
                    help="comma-separated chapter indices (ch000 = 0)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cache_dir = args.work_dir / "gemini_segments" / args.model.replace(".", "_")
    eng = _Eng(args.model)
    for idx in (int(x) for x in args.chapters.split(",")):
        ch_dir = args.work_dir / f"ch{idx:03d}"
        st = reclean_chapter(ch_dir, cache_dir, eng, args.single, args.dry_run)
        print(f"{ch_dir.name}: {st['takes']} takes, {st['bursts']} end bursts "
              f"cut, {st['resplit']} re-split, {st['estimated']} with "
              f"estimated boundaries, {st['skipped']} not cached (skipped)"
              + (" [dry run]" if args.dry_run else ""))


if __name__ == "__main__":
    main()
