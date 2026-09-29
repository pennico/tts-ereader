/** Theme definitions and CSS-variable application (AC-105..AC-108). */
import type { ReaderSettings, ThemeName } from "../types";

export interface ThemeColors {
  bg: string;
  fg: string;
  muted: string;
  panel: string;
  accent: string;
  border: string;
}

export const THEMES: Record<Exclude<ThemeName, "custom">, ThemeColors> = {
  light: {
    bg: "#ffffff",
    fg: "#1a1a1a",
    muted: "#6b6b6b",
    panel: "#f2f2f2",
    accent: "#34506b",
    border: "#dcdcdc",
  },
  dark: {
    bg: "#101010",
    fg: "#e8e8e8",
    muted: "#9a9a9a",
    panel: "#1c1c1c",
    accent: "#8ab4d8",
    border: "#333333",
  },
  sepia: {
    bg: "#f4ecd8",
    fg: "#4b3f2f",
    muted: "#8a7a5f",
    panel: "#eadfc4",
    accent: "#8a5a2b",
    border: "#d8c9a8",
  },
};

/** Resolve the active theme colors, including the custom theme (AC-108). */
export function themeColors(settings: ReaderSettings): ThemeColors {
  if (settings.theme !== "custom") return THEMES[settings.theme];
  return {
    bg: settings.customBg,
    fg: settings.customFg,
    muted: settings.customFg,
    panel: settings.customBg,
    accent: settings.customFg,
    border: settings.customFg,
  };
}

/** Apply theme colors as CSS variables on the given element. */
export function applyTheme(el: HTMLElement, settings: ReaderSettings): void {
  const c = themeColors(settings);
  el.style.setProperty("--bg", c.bg);
  el.style.setProperty("--fg", c.fg);
  el.style.setProperty("--muted", c.muted);
  el.style.setProperty("--panel", c.panel);
  el.style.setProperty("--accent", c.accent);
  el.style.setProperty("--border", c.border);
}

/** CSS font stacks for the three families (AC-101). */
export const FONT_STACKS: Record<string, string> = {
  serif: 'Georgia, "Times New Roman", serif',
  "sans-serif": '"Helvetica Neue", Helvetica, Arial, sans-serif',
  monospace: '"SF Mono", Menlo, Consolas, monospace',
};
