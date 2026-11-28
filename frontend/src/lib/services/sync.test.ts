import { describe, expect, it } from "vitest";
import {
  cumulativeStarts,
  indexAtPosition,
  nextWindow,
  offsetInItem,
  queueIndexForSentence,
} from "./sync";

describe("cumulativeStarts", () => {
  it("builds prefix sums starting at 0", () => {
    expect(cumulativeStarts([100, 200, 50])).toEqual([0, 100, 300, 350]);
  });

  it("handles an empty queue", () => {
    expect(cumulativeStarts([])).toEqual([0]);
  });
});

describe("indexAtPosition", () => {
  const starts = cumulativeStarts([100, 200, 50]);

  it("finds the item playing at a position", () => {
    expect(indexAtPosition(starts, 0)).toBe(0);
    expect(indexAtPosition(starts, 99)).toBe(0);
    expect(indexAtPosition(starts, 100)).toBe(1);
    expect(indexAtPosition(starts, 299)).toBe(1);
    expect(indexAtPosition(starts, 300)).toBe(2);
  });

  it("returns -1 past the end", () => {
    expect(indexAtPosition(starts, 350)).toBe(-1);
    expect(indexAtPosition(starts, 9999)).toBe(-1);
  });
});

describe("offsetInItem", () => {
  it("computes the offset within the active item", () => {
    const starts = cumulativeStarts([100, 200]);
    expect(offsetInItem(starts, 1, 150)).toBe(50);
    expect(offsetInItem(starts, 0, 10)).toBe(10);
  });
});

describe("queueIndexForSentence", () => {
  it("maps global sentence indices into the window", () => {
    expect(queueIndexForSentence(10, [1, 1, 1], 10)).toBe(0);
    expect(queueIndexForSentence(10, [1, 1, 1], 12)).toBe(2);
    expect(queueIndexForSentence(10, [1, 1, 1], 9)).toBe(-1);
    expect(queueIndexForSentence(10, [1, 1, 1], 13)).toBe(-1);
  });
});

describe("nextWindow", () => {
  const lengths = [10, 20, 30, 40, 50];

  it("returns a bounded run of sentence indices", () => {
    expect(nextWindow(1, 5, 2, 1000, lengths)).toEqual([1, 2]);
    expect(nextWindow(0, 5, 10, 1000, lengths)).toEqual([0, 1, 2, 3, 4]);
  });

  it("stops at the char budget", () => {
    // 10 + 20 + 30 = 60 chars fit; adding 40 would exceed 50.
    expect(nextWindow(0, 5, 10, 50, lengths)).toEqual([0, 1]);
  });

  it("returns empty at the end of the chapter", () => {
    expect(nextWindow(5, 5, 10, 1000, lengths)).toEqual([]);
  });
});
