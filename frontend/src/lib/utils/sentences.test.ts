import { describe, expect, it } from "vitest";
import {
  splitChapter,
  splitSentences,
  sentencePosition,
} from "./sentences";

describe("splitSentences", () => {
  it("splits plain narration on terminators", () => {
    const out = splitSentences(
      "La casa era silenziosa. Il giardino era umido. Nessuno parlava."
    );
    expect(out.map((s) => s.text)).toEqual([
      "La casa era silenziosa.",
      "Il giardino era umido.",
      "Nessuno parlava.",
    ]);
  });

  it("keeps closing quotes attached to the sentence", () => {
    const out = splitSentences('Disse: «Così sia.» Poi tacque a lungo.');
    expect(out.map((s) => s.text)).toEqual(["Disse: «Così sia.»", "Poi tacque a lungo."]);
  });

  it("handles double-quote and right-quote closers", () => {
    expect(splitSentences('“Pronto.” disse lui.')[0].text).toBe("“Pronto.”");
    expect(splitSentences('"Pronto." disse lui.')[0].text).toBe('"Pronto."');
  });

  it("does not split on abbreviations", () => {
    const it = "Sig. Rossi abitava in via Roma nr. 12. Non usciva mai.";
    const out = splitSentences(it);
    expect(out.map((s) => s.text)).toEqual([
      "Sig. Rossi abitava in via Roma nr. 12.",
      "Non usciva mai.",
    ]);
  });

  it("does not split Danish abbreviations and ordinals", () => {
    const da = "Han boede f.eks. i København den 1. januar. Det var koldt.";
    const out = splitSentences(da);
    expect(out.map((s) => s.text)).toEqual([
      "Han boede f.eks. i København den 1. januar.",
      "Det var koldt.",
    ]);
  });

  it("does not split initials", () => {
    const out = splitSentences("J. R. R. Tolkien skrev meget. Blev læst.");
    expect(out.map((s) => s.text)).toEqual([
      "J. R. R. Tolkien skrev meget.",
      "Blev læst.",
    ]);
  });

  it("treats ellipsis as a terminator", () => {
    const out = splitSentences("Aspettò… poi bussò di nuovo.");
    expect(out.map((s) => s.text)).toEqual(["Aspettò…", "poi bussò di nuovo."]);
  });

  it("splits before dialogue dashes (Saramago-style)", () => {
    const out = splitSentences("Non rispose. — Vado via, disse.");
    expect(out.map((s) => s.text)).toEqual([
      "Non rispose.",
      "— Vado via, disse.",
    ]);
  });

  it("returns the whole paragraph when there is no terminator", () => {
    const out = splitSentences("una frase senza fine");
    expect(out.map((s) => s.text)).toEqual(["una frase senza fine"]);
  });

  it("reports char offsets within the paragraph", () => {
    const para = "Prima frase. Seconda frase.";
    const out = splitSentences(para);
    expect(out[0].start).toBe(0);
    expect(out[1].start).toBe(13);
    expect(para.slice(out[1].start).startsWith("Seconda")).toBe(true);
  });
});

describe("splitChapter", () => {
  it("indexes sentences globally across paragraphs", () => {
    const out = splitChapter(["Uno. Due.", "Tre."]);
    expect(out.map((s) => s.text)).toEqual(["Uno.", "Due.", "Tre."]);
    expect(out.map((s) => s.index)).toEqual([0, 1, 2]);
    expect(out.map((s) => s.para)).toEqual([0, 0, 1]);
  });
});

describe("sentencePosition", () => {
  it("maps a sentence to a fractional position within the chapter", () => {
    const paras = ["Uno. Due.", "Tre."];
    const all = splitChapter(paras);
    expect(sentencePosition(paras, all[0])).toBeCloseTo(0, 5);
    expect(sentencePosition(paras, all[2])).toBeGreaterThan(0.5);
    expect(sentencePosition(paras, all[2])).toBeLessThanOrEqual(1);
  });

  it("returns 0 for empty chapters", () => {
    expect(sentencePosition([], splitChapter([])[0])).toBe(0);
  });
});
