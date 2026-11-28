/**
 * Reader settings store, persisted to localStorage (AC-101..AC-113).
 * The storage backend is injectable so unit tests can pass a mock.
 */
import { writable } from "svelte/store";
import {
  DEFAULT_SETTINGS,
  type ReaderSettings,
} from "../types";

const STORAGE_KEY = "tts-ereader.settings.v1";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function browserStorage(): StorageLike | null {
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch {
    /* sandboxed context */
  }
  return null;
}

/** Merge stored settings over defaults, dropping unknown/invalid values. */
export function mergeSettings(
  defaults: ReaderSettings,
  stored: Partial<ReaderSettings> | null | undefined
): ReaderSettings {
  if (!stored) return { ...defaults };
  const out = { ...defaults };
  for (const key of Object.keys(defaults) as (keyof ReaderSettings)[]) {
    const value = stored[key];
    if (value === undefined || value === null || typeof value !== typeof defaults[key]) {
      continue;
    }
    // Range guards (AC-102: 8..32pt, AC-104: 1.0..2.5).
    if (key === "fontSize") {
      out.fontSize = clamp(Number(value), 8, 32);
      continue;
    }
    if (key === "lineHeight") {
      out.lineHeight = clamp(Number(value), 1.0, 2.5);
      continue;
    }
    if (key === "autoPageSeconds") {
      out.autoPageSeconds = clamp(Number(value), 2, 120);
      continue;
    }
    if (key === "autoScrollPxPerSec") {
      out.autoScrollPxPerSec = clamp(Number(value), 5, 400);
      continue;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (out as any)[key] = value;
  }
  return out;
}

function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function loadSettings(storage: StorageLike | null): ReaderSettings {
  if (!storage) return { ...DEFAULT_SETTINGS };
  try {
    return mergeSettings(DEFAULT_SETTINGS, JSON.parse(storage.getItem(STORAGE_KEY) || "null"));
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function createSettingsStore(storage: StorageLike | null = browserStorage()) {
  const store = writable<ReaderSettings>(loadSettings(storage));
  store.subscribe((value) => {
    if (!storage) return;
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(value));
    } catch {
      /* storage full or unavailable: keep in-memory settings */
    }
  });
  return store;
}

export const settings = createSettingsStore();
