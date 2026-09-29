import { describe, expect, it } from "vitest";
import {
  COLUMN_GAP,
  clampPage,
  nextPage,
  pageCount,
  pageOffset,
  pageToPosition,
  positionToPage,
  positionToScrollTop,
  scrollTopToPosition,
} from "./pagination";

describe("pageCount", () => {
  it("returns 1 for empty/zero dimensions", () => {
    expect(pageCount(0, 800)).toBe(1);
    expect(pageCount(500, 0)).toBe(1);
  });

  it("counts columns that fit the laid-out content width", () => {
    const vw = 800;
    // exactly one page
    expect(pageCount(vw, vw)).toBe(1);
    // two pages: content spans vw + gap + a bit more
    expect(pageCount(vw + COLUMN_GAP + 1, vw)).toBe(2);
    // three pages
    expect(pageCount(2 * (vw + COLUMN_GAP) + 1, vw)).toBe(3);
    // content that exactly fills two columns is still 2 pages
    expect(pageCount(2 * vw + COLUMN_GAP, vw)).toBe(2);
  });
});

describe("page <-> position round trip", () => {
  it("round-trips within range", () => {
    const pages = 10;
    for (let page = 0; page < pages; page++) {
      expect(positionToPage(pageToPosition(page, pages), pages)).toBe(page);
    }
  });

  it("single page maps to position 0", () => {
    expect(pageToPosition(0, 1)).toBe(0);
    expect(positionToPage(0.73, 1)).toBe(0);
  });

  it("clamps out-of-range pages", () => {
    expect(clampPage(-3, 5)).toBe(0);
    expect(clampPage(11, 5)).toBe(4);
    expect(clampPage(2, 1)).toBe(0);
  });
});

describe("pageOffset", () => {
  it("advances by column width plus gap", () => {
    expect(pageOffset(0, 800)).toBe(0);
    expect(pageOffset(1, 800)).toBe(800 + COLUMN_GAP);
    expect(pageOffset(3, 800)).toBe(3 * (800 + COLUMN_GAP));
  });
});

describe("nextPage", () => {
  it("returns null at the end of the chapter", () => {
    expect(nextPage(0, 5)).toBe(1);
    expect(nextPage(4, 5)).toBeNull();
    expect(nextPage(9, 5)).toBeNull();
  });
});

describe("scroll position mapping", () => {
  it("round-trips scrollTop through position", () => {
    const scrollHeight = 5000;
    const clientHeight = 1000;
    for (const top of [0, 500, 2000, 4000]) {
      const pos = scrollTopToPosition(top, scrollHeight, clientHeight);
      expect(positionToScrollTop(pos, scrollHeight, clientHeight)).toBe(top);
    }
  });

  it("returns 0 when nothing to scroll", () => {
    expect(scrollTopToPosition(0, 1000, 1000)).toBe(0);
    expect(positionToScrollTop(0.5, 500, 1000)).toBe(0);
  });

  it("clamps beyond the ends", () => {
    expect(scrollTopToPosition(99999, 5000, 1000)).toBe(1);
    expect(positionToScrollTop(1.5, 5000, 1000)).toBe(4000);
  });
});
