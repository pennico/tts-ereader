/**
 * Pure playback-timeline math for read-along sync (M2, AC-202, AC-206).
 *
 * The reader plays a queue of synthesized sentences; these helpers map a
 * chapter-wide playback position (ms) to the active queue item, and are kept
 * pure so they are unit-testable without Web Audio.
 */

/** Cumulative start time (ms) of each queue item: starts[0] === 0. */
export function cumulativeStarts(durationsMs: number[]): number[] {
  const starts = [0];
  for (let i = 0; i < durationsMs.length; i++) {
    starts.push(starts[i] + durationsMs[i]);
  }
  return starts;
}

/** Index of the item playing at posMs; -1 when posMs is past the end. */
export function indexAtPosition(starts: number[], posMs: number): number {
  for (let i = 0; i < starts.length - 1; i++) {
    if (posMs < starts[i + 1]) return i;
  }
  return -1;
}

/** Position (ms) relative to the start of the item at index. */
export function offsetInItem(starts: number[], index: number, posMs: number): number {
  return Math.max(0, posMs - starts[index]);
}

/**
 * Queue index for a global sentence index, or -1 if the sentence is outside
 * the window [queueStart, queueStart + durations.length).
 */
export function queueIndexForSentence(
  queueStart: number,
  durations: number[],
  sentenceIndex: number
): number {
  const rel = sentenceIndex - queueStart;
  if (rel < 0 || rel >= durations.length) return -1;
  return rel;
}

/** The next window of sentence indices to synthesize (bounded by chapter size). */
export function nextWindow(
  from: number,
  chapterSentences: number,
  maxSentences: number,
  maxChars: number,
  sentenceLengths: number[]
): number[] {
  const out: number[] = [];
  let chars = 0;
  for (let i = from; i < chapterSentences; i++) {
    if (out.length >= maxSentences) break;
    const len = sentenceLengths[i] ?? 0;
    if (out.length > 0 && chars + len > maxChars) break;
    out.push(i);
    chars += len;
  }
  return out;
}
