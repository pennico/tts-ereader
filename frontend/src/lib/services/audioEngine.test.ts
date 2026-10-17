import { describe, expect, it, vi } from "vitest";
import {
  AudioEngine,
  base64ToArrayBuffer,
  type AudioBufferLike,
  type AudioBufferSourceNodeLike,
  type AudioContextLike,
  type GainNodeLike,
} from "./audioEngine";

/** Deterministic fake Web Audio context for position/rate math tests. */
class FakeContext implements AudioContextLike {
  currentTime = 0;
  sampleRate = 24000;
  lastSource: FakeSource | null = null;

  async decodeAudioData(data: ArrayBuffer): Promise<AudioBufferLike> {
    return { duration: 1.0 }; // decoded blobs are 1s
  }

  createBufferSource(): AudioBufferSourceNodeLike {
    const src = new FakeSource(this);
    this.lastSource = src;
    return src;
  }

  createGain(): GainNodeLike {
    const node: GainNodeLike = { gain: { value: 1 }, connect: () => node };
    return node;
  }

  async resume(): Promise<void> {}
}

class FakeSource implements AudioBufferSourceNodeLike {
  buffer: AudioBufferLike | null = null;
  playbackRate = { value: 1 };
  onended: (() => void) | null = null;
  started: { when: number; offset: number } | null = null;
  stopped = false;

  constructor(private ctx: FakeContext) {}

  connect(): AudioBufferSourceNodeLike {
    return this;
  }

  start(when?: number, offset?: number): void {
    this.started = { when: when ?? 0, offset: offset ?? 0 };
  }

  stop(): void {
    this.stopped = true;
  }
}

function b64(): string {
  // "AAAA" -> 3 zero bytes; content is irrelevant (decode is faked).
  return "AAAA";
}

describe("base64ToArrayBuffer", () => {
  it("decodes base64 to bytes", () => {
    const buf = base64ToArrayBuffer("AAECAw==");
    expect(new Uint8Array(buf)).toEqual(new Uint8Array([0, 1, 2, 3]));
  });
});

describe("AudioEngine", () => {
  it("tracks position in the buffer timeline at 1x rate", async () => {
    const ctx = new FakeContext();
    const engine = new AudioEngine(ctx);
    const buffer = await engine.decode(b64());
    await engine.play(buffer, 0, 1.0);
    ctx.currentTime += 0.5; // 500ms of real time
    expect(engine.positionMs()).toBeCloseTo(500, 0);
  });

  it("scales position by the playback rate (AC-303)", async () => {
    const ctx = new FakeContext();
    const engine = new AudioEngine(ctx);
    const buffer = await engine.decode(b64());
    await engine.play(buffer, 0, 2.0);
    ctx.currentTime += 0.25; // 250ms real time at 2x = 500ms of audio
    expect(engine.positionMs()).toBeCloseTo(500, 0);
  });

  it("pause freezes the position and resume continues from it", async () => {
    const ctx = new FakeContext();
    const engine = new AudioEngine(ctx);
    const buffer = await engine.decode(b64());
    await engine.play(buffer, 0, 1.0);
    ctx.currentTime += 0.3;
    const pos = engine.pause();
    expect(pos).toBeCloseTo(300, 0);
    expect(engine.isPlaying).toBe(false);
    ctx.currentTime += 1.0; // time passes while paused
    expect(engine.positionMs()).toBeCloseTo(300, 0);
    await engine.resume();
    expect(engine.isPlaying).toBe(true);
    ctx.currentTime += 0.2;
    expect(engine.positionMs()).toBeCloseTo(500, 0);
  });

  it("fires onEnded when the buffer runs out naturally", async () => {
    const ctx = new FakeContext();
    const engine = new AudioEngine(ctx);
    const buffer = await engine.decode(b64()); // 1s
    const onEnded = vi.fn();
    engine.onEnded = onEnded;
    await engine.play(buffer, 0, 1.0);
    ctx.currentTime += 1.0;
    ctx.lastSource!.onended!();
    expect(onEnded).toHaveBeenCalledOnce();
    expect(engine.isPlaying).toBe(false);
  });

  it("does not fire onEnded after an explicit pause", async () => {
    const ctx = new FakeContext();
    const engine = new AudioEngine(ctx);
    const buffer = await engine.decode(b64());
    const onEnded = vi.fn();
    engine.onEnded = onEnded;
    await engine.play(buffer, 0, 1.0);
    engine.pause();
    expect(onEnded).not.toHaveBeenCalled();
  });

  it("setRate restarts at the current position with the new rate", async () => {
    const ctx = new FakeContext();
    const engine = new AudioEngine(ctx);
    const buffer = await engine.decode(b64());
    await engine.play(buffer, 0, 1.0);
    ctx.currentTime += 0.4; // 400ms in
    await engine.setRate(2.0);
    expect(engine.positionMs()).toBeCloseTo(400, 0);
    ctx.currentTime += 0.1; // 100ms real at 2x = 200ms audio
    expect(engine.positionMs()).toBeCloseTo(600, 0);
    expect(ctx.lastSource!.playbackRate.value).toBe(2.0);
  });
});
