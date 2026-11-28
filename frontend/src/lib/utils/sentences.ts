/**
 * Sentence splitting for read-along (M2, AC-201/AC-202).
 *
 * The reader's playback unit is the sentence: each sentence is synthesized
 * separately, so the spoken sentence can be highlighted with engine-reported
 * timing. European typography: handles closing quotes («», ”, ", '), ellipsis,
 * dialogue dashes, and common Italian/Danish/English abbreviations.
 */

export interface Sentence {
  /** Trimmed sentence text. */
  text: string;
  /** Char offset of the first character within the source paragraph. */
  start: number;
}

const TERMINATORS = ".!?…";
const CLOSERS = "»”\"')’]*";

// Tokens that look like sentence ends but are not (lowercase, no dot).
const ABBREVIATIONS = new Set([
  // English
  "mr", "mrs", "ms", "dr", "st", "vs", "etc", "jr", "sr", "prof", "inc",
  // Italian
  "sig", "sig.ra", "sig.ra", "ecc", "nr", "es", "p", "pag", "cap", "fig",
  "gen", "geol", "mil", "mus", "pen", "pol", "prof", "tel", "vol",
  // Danish
  "nr", "f.eks", "osv", "bl.a", "dvs", "kr", "ca", "att", "adr", "dir",
  "inkl", "max", "min", "kl", "siden", "jf", "øns", "alm",
]);

function isAbbreviation(text: string, dotIndex: number, nextWordStart: number): boolean {
  const before = text[dotIndex - 1];
  if (before === undefined) return true;
  // Danish ordinals: "den 1. januar", "3. kapitel" — digit + '.' + lowercase.
  // A digit + '.' followed by an uppercase word is a sentence end ("nr. 12. Non").
  if (/[0-9]/.test(before)) {
    const next = nextWordStart >= 0 ? text[nextWordStart] : "";
    return !!next && /[a-zà-ÿ]/.test(next);
  }
  // Scan back over letters and internal dots (f.eks -> "f.eks").
  let i = dotIndex - 1;
  while (i >= 0 && /[A-Za-zÀ-ÿ.]/.test(text[i])) i--;
  const token = text.slice(i + 1, dotIndex).toLowerCase();
  if (!token) return false;
  if (ABBREVIATIONS.has(token)) return true;
  // Single initials: "J. R. R. Tolkien".
  if (token.length === 1 && /[a-zà-ÿ]/i.test(token)) return true;
  return false;
}

/** Split a paragraph into sentences with their char offsets. */
export function splitSentences(paragraph: string): Sentence[] {
  const out: Sentence[] = [];
  let start = 0;
  const len = paragraph.length;

  for (let i = 0; i < len; i++) {
    if (!TERMINATORS.includes(paragraph[i])) continue;
    // Swallow closing quotes/brackets after the terminator.
    let j = i + 1;
    while (j < len && CLOSERS.includes(paragraph[j])) j++;
    if (j < len) {
      const next = paragraph[j];
      const isBoundary = /\s/.test(next) || next === "—" || next === "–";
      if (!isBoundary) continue;
      // First char of the next word (for the ordinal heuristic).
      let k = j;
      while (k < len && /\s/.test(paragraph[k])) k++;
      if (isAbbreviation(paragraph, i, k < len ? k : -1)) continue;
    }
    const text = paragraph.slice(start, j).trim();
    if (text) out.push({ text, start });
    // Next sentence starts after the whitespace (or at a dialogue dash).
    let k = j;
    while (k < len && /\s/.test(paragraph[k])) k++;
    start = k;
    i = j - 1;
  }

  const tail = paragraph.slice(start).trim();
  if (tail) out.push({ text: tail, start });
  return out;
}

/** Flat chapter-wide sentence list: [{paraIndex, sentence, globalIndex}]. */
export interface ChapterSentence {
  index: number; // global index within the chapter
  para: number; // paragraph index
  text: string;
  start: number; // char offset within the paragraph
}

export function splitChapter(paragraphs: string[]): ChapterSentence[] {
  const out: ChapterSentence[] = [];
  let index = 0;
  paragraphs.forEach((para, p) => {
    for (const s of splitSentences(para)) {
      out.push({ index: index++, para: p, text: s.text, start: s.start });
    }
  });
  return out;
}

/** Fractional reading position (0..1) of a sentence within the chapter. */
export function sentencePosition(
  paragraphs: string[],
  sentence: ChapterSentence
): number {
  const total = paragraphs.reduce((n, p) => n + p.length + 2, 0);
  if (total <= 0 || !sentence) return 0;
  let before = 0;
  for (let p = 0; p < sentence.para; p++) before += paragraphs[p].length + 2;
  before += sentence.start;
  return Math.min(1, before / total);
}
