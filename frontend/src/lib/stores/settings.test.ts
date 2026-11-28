import { get } from "svelte/store";
import { describe, expect, it } from "vitest";
import { DEFAULT_SETTINGS } from "../types";
import { createSettingsStore, mergeSettings, type StorageLike } from "./settings";

function memoryStorage(initial: Record<string, string> = {}): StorageLike {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => (data.has(key) ? (data.get(key) as string) : null),
    setItem: (key, value) => void data.set(key, value),
    removeItem: (key) => void data.delete(key),
  };
}

describe("mergeSettings", () => {
  it("returns defaults for null/undefined stored values", () => {
    expect(mergeSettings(DEFAULT_SETTINGS, null)).toEqual(DEFAULT_SETTINGS);
    expect(mergeSettings(DEFAULT_SETTINGS, undefined)).toEqual(DEFAULT_SETTINGS);
  });

  it("keeps valid stored values and fills the rest with defaults", () => {
    const merged = mergeSettings(DEFAULT_SETTINGS, {
      theme: "dark",
      fontSize: 22,
      scrollMode: "paged",
    });
    expect(merged.theme).toBe("dark");
    expect(merged.fontSize).toBe(22);
    expect(merged.scrollMode).toBe("paged");
    expect(merged.lineHeight).toBe(DEFAULT_SETTINGS.lineHeight);
  });

  it("clamps ranges (AC-102: 8..32pt, AC-104: 1.0..2.5)", () => {
    const merged = mergeSettings(DEFAULT_SETTINGS, {
      fontSize: 99,
      lineHeight: 9,
      autoPageSeconds: 0,
      autoScrollPxPerSec: 10000,
    });
    expect(merged.fontSize).toBe(32);
    expect(merged.lineHeight).toBe(2.5);
    expect(merged.autoPageSeconds).toBe(2);
    expect(merged.autoScrollPxPerSec).toBe(400);
  });

  it("drops values of the wrong type", () => {
    const bad = {
      theme: 42,
      fontSize: "big",
      autoEnabled: "yes",
    } as unknown as Partial<Record<string, unknown>>;
    const merged = mergeSettings(
      DEFAULT_SETTINGS,
      bad as unknown as Partial<typeof DEFAULT_SETTINGS>
    );
    expect(merged).toEqual(DEFAULT_SETTINGS);
  });
});

describe("settings store persistence", () => {
  it("persists updates to the injected storage and reloads them", () => {
    const storage = memoryStorage();
    const store = createSettingsStore(storage);

    store.update((s) => ({ ...s, theme: "sepia", fontSize: 24 }));
    const saved = JSON.parse(storage.getItem("tts-ereader.settings.v1") as string);
    expect(saved.theme).toBe("sepia");
    expect(saved.fontSize).toBe(24);

    // A new store over the same storage picks the values back up.
    const reloaded = get(createSettingsStore(storage));
    expect(reloaded.theme).toBe("sepia");
    expect(reloaded.fontSize).toBe(24);
    expect(reloaded.lineHeight).toBe(DEFAULT_SETTINGS.lineHeight);
  });

  it("falls back to defaults on corrupt stored JSON", () => {
    const storage = memoryStorage({ "tts-ereader.settings.v1": "{not json" });
    expect(get(createSettingsStore(storage))).toEqual(DEFAULT_SETTINGS);
  });

  it("works with no storage available", () => {
    const store = createSettingsStore(null);
    store.update((s) => ({ ...s, theme: "dark" as const }));
    expect(get(store).theme).toBe("dark");
  });
});
