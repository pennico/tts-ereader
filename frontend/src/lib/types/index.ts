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

/** Per-book voice settings (AC-301..AC-304, AC-305, AC-307), persisted locally per book. */
export interface TtsSettings {
  engine: string;
  voice: string;
  rate: number; // 0.5..2.0 (AC-303)
  pitch: number; // -20..20 (AC-304)
  autoAdvance: boolean; // voice-driven auto progression (AC-205)
  castEnabled: boolean; // per-book voice cast via LLM speaker tagging (AC-305)
  cast: Record<string, string>; // role -> voice id overrides (AC-305)
}

export const DEFAULT_TTS_SETTINGS: TtsSettings = {
  engine: "gemini",
  voice: "Kore",
  rate: 1.0,
  pitch: 0,
  autoAdvance: true,
  castEnabled: false,
  cast: {},
};

/** Cast roles (mirrors shared/voice_cast.py). */
export const CAST_ROLES = [
  "narrator",
  "female_1",
  "female_other",
  "male_short",
] as const;

export type CastRole = (typeof CAST_ROLES)[number];

export const CAST_ROLE_LABELS: Record<CastRole, string> = {
  narrator: "Narrator / male characters",
  female_1: "First female character",
  female_other: "Other female characters",
  male_short: "Short male side roles",
};

/** Prepared chapter segments (backend/app/api/prepare.py, M3). */
export interface PreparedSegment {
  index: number;
  text: string;
  speaker: string | null;
  gender: string | null;
  role: string;
  voice: string;
}

export interface PreparedChapter {
  chapter_index: number;
  language: string;
  cached: boolean;
  segments: PreparedSegment[];
}

export interface CastRoleInfo {
  role: string;
  display_name: string;
  voice: string;
  voice_display_name: string;
}

export interface CastDefaults {
  engine: string;
  language: string;
  roles: CastRoleInfo[];
}

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
