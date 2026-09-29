import { describe, expect, it } from "vitest";
import { DEFAULT_SETTINGS } from "../types";
import { FONT_STACKS, THEMES, themeColors } from "./themes";

describe("themeColors", () => {
  it("resolves the three built-in themes (AC-105..AC-107)", () => {
    expect(themeColors({ ...DEFAULT_SETTINGS, theme: "light" })).toEqual(THEMES.light);
    expect(themeColors({ ...DEFAULT_SETTINGS, theme: "dark" })).toEqual(THEMES.dark);
    expect(themeColors({ ...DEFAULT_SETTINGS, theme: "sepia" })).toEqual(THEMES.sepia);
  });

  it("uses user colors for the custom theme (AC-108)", () => {
    const colors = themeColors({
      ...DEFAULT_SETTINGS,
      theme: "custom",
      customBg: "#123456",
      customFg: "#fedcba",
    });
    expect(colors.bg).toBe("#123456");
    expect(colors.fg).toBe("#fedcba");
  });

  it("provides a stack for every font family (AC-101)", () => {
    for (const family of ["serif", "sans-serif", "monospace"]) {
      expect(FONT_STACKS[family].length).toBeGreaterThan(0);
    }
  });
});
