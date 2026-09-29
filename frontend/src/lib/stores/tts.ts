/**
 * Per-book TTS settings (AC-301..AC-303), persisted to localStorage per book.
 * Voice cast persistence beyond a single narrator is M3 (AC-307).
 */
import { writable } from "svelte/store";
import { DEFAULT_TTS_SETTINGS, type TtsSettings } from "../types";
import type { StorageLike } from "./settings";

const KEY_PREFIX = "tts-ereader.tts.v1.";

export function browserStorage(): StorageLike | null {
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch {
    /* sandboxed context */
  }
  return null;
}

export function mergeTtsSettings(
  defaults: TtsSettings,
  stored: Partial<TtsSettings> | null | undefined
): TtsSettings {
  if (!stored) return { ...defaults };
  const out = { ...defaults };
  if (typeof stored.engine === "string" && stored.engine) out.engine = stored.engine;
  if (typeof stored.voice === "string" && stored.voice) out.voice = stored.voice;
  if (typeof stored.rate === "number" && !Number.isNaN(stored.rate)) {
    out.rate = Math.min(2.0, Math.max(0.5, stored.rate)); // AC-303
  }
  if (typeof stored.autoAdvance === "boolean") out.autoAdvance = stored.autoAdvance;
  return out;
}

export function createTtsStore(
  bookId: number,
  storage: StorageLike | null,
  onChange?: (value: TtsSettings) => void
) {
  let current: TtsSettings;
  if (storage) {
    try {
      current = mergeTtsSettings(
        DEFAULT_TTS_SETTINGS,
        JSON.parse(storage.getItem(KEY_PREFIX + bookId) || "null")
      );
    } catch {
      current = { ...DEFAULT_TTS_SETTINGS };
    }
  } else {
    current = { ...DEFAULT_TTS_SETTINGS };
  }
  const store = writable<TtsSettings>(current);
  store.subscribe((value) => {
    current = value;
    if (storage) {
      try {
        storage.setItem(KEY_PREFIX + bookId, JSON.stringify(value));
      } catch {
        /* storage unavailable: keep in-memory */
      }
    }
    onChange?.(value);
  });
  return store;
}
