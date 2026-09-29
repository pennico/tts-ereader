/**
 * Web Audio API wrapper (ARCHITECTURE_v1 §11.2, AC-605).
 *
 * Plays one decoded AudioBuffer at a time with precise position tracking via
 * AudioContext.currentTime. Playback rate scales the timeline: position is
 * reported in the buffer's own timeline (ms), i.e. real elapsed time is
 * multiplied by the rate (AC-303).
 */

export interface AudioContextLike {
  currentTime: number;
  sampleRate: number;
  decodeAudioData(data: ArrayBuffer): Promise<AudioBufferLike>;
  createBufferSource(): AudioBufferSourceNodeLike;
  createGain(): GainNodeLike;
  resume(): Promise<void>;
}

export interface AudioBufferLike {
  duration: number; // seconds
}

export interface AudioBufferSourceNodeLike {
  buffer: AudioBufferLike | null;
  playbackRate: { value: number };
  onended: (() => void) | null;
  connect(node: unknown): AudioBufferSourceNodeLike;
  start(when?: number, offset?: number, duration?: number): void;
  stop(when?: number): void;
}

export interface GainNodeLike {
  gain: { value: number };
  connect(node: unknown): GainNodeLike;
}

export function createBrowserAudioContext(): AudioContextLike {
  return new AudioContext() as unknown as AudioContextLike;
}

/** Decode a base64 audio blob (WAV or MP3 — both decode natively). */
export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export class AudioEngine {
  private ctx: AudioContextLike;
  private gain: GainNodeLike;
  private source: AudioBufferSourceNodeLike | null = null;
  private buffer: AudioBufferLike | null = null;
  private startCtxTime = 0; // ctx.currentTime when the current run started
  private startOffsetMs = 0; // buffer offset (ms) at the current run start
  private playing = false;
  private rate = 1.0;
  /** Fires when the buffer ends naturally (not on stop()/seek()). */
  onEnded: (() => void) | null = null;

  constructor(ctx?: AudioContextLike) {
    this.ctx = ctx ?? createBrowserAudioContext();
    this.gain = this.ctx.createGain();
    this.gain.gain.value = 1.0;
    this.gain.connect(undefined);
  }

  async decode(b64: string): Promise<AudioBufferLike> {
    return this.ctx.decodeAudioData(base64ToArrayBuffer(b64));
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  /** Current position within the buffer's timeline (ms). */
  positionMs(): number {
    if (!this.playing) return this.startOffsetMs;
    const elapsedSec = this.ctx.currentTime - this.startCtxTime;
    return this.startOffsetMs + elapsedSec * this.rate * 1000;
  }

  /** Play a buffer from an offset; ends with onEnded when it runs out. */
  async play(buffer: AudioBufferLike, offsetMs = 0, rate = 1.0): Promise<void> {
    await this.ctx.resume();
    this.stopSource();
    this.buffer = buffer;
    this.rate = rate;
    this.startOffsetMs = offsetMs;
    this.startCtxTime = this.ctx.currentTime;
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.playbackRate.value = rate;
    source.connect(this.gain);
    source.onended = () => {
      if (this.source === source && this.playing) {
        this.playing = false;
        this.startOffsetMs = buffer.duration * 1000;
        this.source = null;
        this.onEnded?.();
      }
    };
    this.source = source;
    this.playing = true;
    source.start(0, offsetMs / 1000);
  }

  /** Stop playback and remember the position (pause). */
  pause(): number {
    const pos = this.positionMs();
    this.stopSource();
    this.playing = false;
    this.startOffsetMs = pos;
    return pos;
  }

  /** Resume the current buffer from where pause() left it. */
  async resume(): Promise<void> {
    if (this.playing || !this.buffer) return;
    await this.play(this.buffer, this.startOffsetMs, this.rate);
  }

  /** Change the playback rate, keeping the current position. */
  async setRate(rate: number): Promise<void> {
    if (rate === this.rate) return;
    if (!this.playing) {
      this.rate = rate;
      return;
    }
    const pos = this.positionMs();
    await this.play(this.buffer!, pos, rate);
  }

  private stopSource(): void {
    if (this.source) {
      this.source.onended = null;
      try {
        this.source.stop();
      } catch {
        /* already stopped */
      }
      this.source = null;
    }
  }
}
