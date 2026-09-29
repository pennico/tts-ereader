/** Shared API types mirroring the backend schemas (backend/app/api/*.py). */

export interface Book {
  id: number;
  title: string;
  author: string;
  language: string;
  cover_path: string | null;
  chapter_count: number;
  progress_chapter: number;
  progress_position: number;
}

export interface ChapterMeta {
  index: number;
  title: string;
  char_count: number;
}

export interface ChapterText {
  index: number;
  title: string;
  text: string;
}

export interface Progress {
  chapter_index: number;
  position: number;
}

export type ThemeName = "light" | "dark" | "sepia" | "custom";
export type FontFamily = "serif" | "sans-serif" | "monospace";
export type ScrollMode = "scroll" | "paged";

/** TTS types mirroring backend/app/api/tts.py (M2). */
export interface TtsEngineInfo {
  name: string;
  display_name: string;
  available: boolean;
  is_default: boolean;
}

export interface TtsVoiceInfo {
  name: string;
  display_name: string;
  gender: string;
  locale: string;
}

export interface WordBoundary {
  word: string;
  start_ms: number;
  end_ms: number;
}

export interface SynthesisSegment {
  text: string;
  engine: string;
  cached: boolean;
  audio_b64: string;
  format: string;
  sample_rate: number;
  duration_ms: number;
  word_boundaries: WordBoundary[] | null;
}

/** Per-book voice settings (AC-301..AC-303), persisted locally per book. */
export interface TtsSettings {
  engine: string;
  voice: string;
  rate: number; // 0.5..2.0 (AC-303)
  autoAdvance: boolean; // voice-driven auto progression (AC-205)
}

export const DEFAULT_TTS_SETTINGS: TtsSettings = {
  engine: "gemini",
  voice: "Kore",
  rate: 1.0,
  autoAdvance: true,
};

/** Reader display + behavior preferences (AC-101..AC-113), persisted locally. */
export interface ReaderSettings {
  theme: ThemeName;
  customBg: string;
  customFg: string;
  fontFamily: FontFamily;
  fontSize: number; // pt, 8..32 (AC-102)
  fontWeight: "normal" | "bold"; // AC-103
  lineHeight: number; // 1.0..2.5 (AC-104)
  scrollMode: ScrollMode; // AC-109..AC-111
  autoEnabled: boolean; // AC-112/AC-113
  autoPageSeconds: number; // paginated: seconds per page
  autoScrollPxPerSec: number; // continuous: px per second
}

export const DEFAULT_SETTINGS: ReaderSettings = {
  theme: "light",
  customBg: "#101010",
  customFg: "#e8e8e8",
  fontFamily: "serif",
  fontSize: 18,
  fontWeight: "normal",
  lineHeight: 1.6,
  scrollMode: "scroll",
  autoEnabled: false,
  autoPageSeconds: 8,
  autoScrollPxPerSec: 40,
};
