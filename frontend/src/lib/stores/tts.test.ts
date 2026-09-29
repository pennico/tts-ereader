import { describe, expect, it } from "vitest";
import { mergeTtsSettings } from "./tts";
import { DEFAULT_TTS_SETTINGS } from "../types";

describe("mergeTtsSettings", () => {
  it("returns defaults for null stored values", () => {
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, null)).toEqual(DEFAULT_TTS_SETTINGS);
  });

  it("keeps valid stored values", () => {
    const merged = mergeTtsSettings(DEFAULT_TTS_SETTINGS, {
      engine: "edge",
      voice: "da-DK-ChristelNeural",
      rate: 1.5,
      pitch: -5,
      autoAdvance: false,
      castEnabled: true,
      cast: { narrator: "da-DK-JeppeNeural" },
    });
    expect(merged).toEqual({
      engine: "edge",
      voice: "da-DK-ChristelNeural",
      rate: 1.5,
      pitch: -5,
      autoAdvance: false,
      castEnabled: true,
      cast: { narrator: "da-DK-JeppeNeural" },
    });
  });

  it("clamps rate to 0.5..2.0 (AC-303)", () => {
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, { rate: 5 }).rate).toBe(2.0);
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, { rate: 0.1 }).rate).toBe(0.5);
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, { rate: 0 }).rate).toBe(0.5);
  });

  it("clamps pitch to -20..20 (AC-304)", () => {
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, { pitch: 99 }).pitch).toBe(20);
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, { pitch: -99 }).pitch).toBe(-20);
  });

  it("drops invalid values", () => {
    const merged = mergeTtsSettings(DEFAULT_TTS_SETTINGS, {
      engine: "",
      voice: "",
      rate: Number.NaN,
      pitch: Number.NaN,
    });
    expect(merged.engine).toBe(DEFAULT_TTS_SETTINGS.engine);
    expect(merged.voice).toBe(DEFAULT_TTS_SETTINGS.voice);
    expect(merged.rate).toBe(1.0);
    expect(merged.pitch).toBe(0);
  });

  it("filters the cast to known roles with string voices (AC-305)", () => {
    const merged = mergeTtsSettings(DEFAULT_TTS_SETTINGS, {
      castEnabled: "yes", // invalid type: ignored
      cast: {
        narrator: "da-DK-JeppeNeural",
        female_1: 42, // invalid voice: dropped
        villain: "evil-voice", // unknown role: dropped
      } as unknown as Record<string, string>,
    });
    expect(merged.castEnabled).toBe(false);
    expect(merged.cast).toEqual({ narrator: "da-DK-JeppeNeural" });
  });
});
