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
      autoAdvance: false,
    });
    expect(merged).toEqual({
      engine: "edge",
      voice: "da-DK-ChristelNeural",
      rate: 1.5,
      autoAdvance: false,
    });
  });

  it("clamps rate to 0.5..2.0 (AC-303)", () => {
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, { rate: 5 }).rate).toBe(2.0);
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, { rate: 0.1 }).rate).toBe(0.5);
    expect(mergeTtsSettings(DEFAULT_TTS_SETTINGS, { rate: 0 }).rate).toBe(0.5);
  });

  it("drops invalid values", () => {
    const merged = mergeTtsSettings(DEFAULT_TTS_SETTINGS, {
      engine: "",
      voice: "",
      rate: Number.NaN,
    });
    expect(merged.engine).toBe(DEFAULT_TTS_SETTINGS.engine);
    expect(merged.voice).toBe(DEFAULT_TTS_SETTINGS.voice);
    expect(merged.rate).toBe(1.0);
  });
});
