import { WakeWordDetector } from "../core/detector";
import {
  type DetectionEvent,
  type DetectorListener,
  type DetectorOptions,
  type DetectorState,
  SAMPLE_RATE,
  type WakeWordModelBundle,
} from "../types/index";
import { NativeRuntime } from "./runtime";

/**
 * React Native wake-word controller. Owns an audio-stream subscription and a
 * `WakeWordDetector`. Audio capture is delegated to `react-native-live-audio-stream`
 * (peer dep) — pass it in via `audio` so this lib doesn't import it directly
 * (keeps unit-tests trivial and avoids native linkage at parse time).
 */

/** Minimal contract; matches `react-native-live-audio-stream` and works with
 * any audio source that emits little-endian 16-bit PCM as base64 strings. */
export type NativeAudioStream = {
  init: (options: NativeAudioInitOptions) => void;
  start: () => void;
  stop: () => void;
  on: (event: "data", cb: (base64: string) => void) => void;
};

export interface NativeAudioInitOptions {
  sampleRate: number;
  channels: number;
  bitsPerSample: number;
  bufferSize?: number;
  audioSource?: number;
  /** Some implementations (e.g. react-native-live-audio-stream) require this. */
  wavFile: string;
}

export interface WakeWordNativeOptions {
  models: WakeWordModelBundle;
  detector?: DetectorOptions;
  /** Pass the imported `LiveAudioStream` module from `react-native-live-audio-stream`. */
  audio: NativeAudioStream;
  /**
   * Raw mic sample rate. Defaults to 16 000 (the rate the detector expects).
   * If your device can't deliver 16 kHz, set this to your native rate and
   * the detector will accept up-front resampled data via `pcmConverter`.
   */
  sourceSampleRate?: number;
}

type EventMap = {
  detection: DetectionEvent;
  state: DetectorState;
  error: Error;
};

/** Convert a base64 string of little-endian 16-bit PCM to Float32Array in [-1,1]. */
function base64Pcm16ToFloat32(b64: string): Float32Array {
  // Buffer / Uint8Array path — works in RN.
  const binary =
    typeof Buffer === "undefined"
      ? Uint8Array.from(atob(b64), (c) => c.codePointAt(0) ?? 0)
      : Buffer.from(b64, "base64");
  const dv = new DataView(binary.buffer, binary.byteOffset, binary.byteLength);
  const out = new Float32Array(binary.byteLength / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = dv.getInt16(i * 2, true) / 32768;
  }
  return out;
}

export class WakeWordNativeController {
  private detector: WakeWordDetector | null = null;
  private readonly listeners = new Map<
    keyof EventMap,
    Set<(p: unknown) => void>
  >();
  /**
   * The injected audio module is EventEmitter-style and can't be assumed to
   * support removing a listener, so we attach the `"data"` handler exactly
   * once per controller and route frames to whatever the current detector is.
   * This avoids duplicate ingestion across stop()/start() cycles.
   */
  private audioListenerBound = false;

  constructor(private readonly opts: WakeWordNativeOptions) {}

  on<E extends keyof EventMap>(
    event: E,
    cb: (payload: EventMap[E]) => void,
  ): () => void {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    set.add(cb as (p: unknown) => void);
    return () => set?.delete(cb as (p: unknown) => void);
  }

  async start(): Promise<void> {
    if (this.detector) return;
    const runtime = new NativeRuntime();
    const detector = new WakeWordDetector(runtime, this.opts.detector);
    const detectorListener: DetectorListener = {
      onDetection: (e) => this.emit("detection", e),
      onStateChange: (s) => this.emit("state", s),
      onError: (err) => this.emit("error", err),
    };
    detector.setListener(detectorListener);
    await detector.load(this.opts.models);
    this.detector = detector;

    const audio = this.opts.audio;
    audio.init({
      sampleRate: this.opts.sourceSampleRate ?? SAMPLE_RATE,
      channels: 1,
      bitsPerSample: 16,
      bufferSize: 1280, // 80 ms @ 16 kHz, matches detector frame size
      wavFile: "",
    });
    if (!this.audioListenerBound) {
      audio.on("data", (chunkB64) => {
        const active = this.detector;
        if (!active) return;
        const samples = base64Pcm16ToFloat32(chunkB64);
        void active.push(samples);
      });
      this.audioListenerBound = true;
    }
    audio.start();
  }

  async stop(): Promise<void> {
    this.opts.audio.stop();
    await this.detector?.release();
    this.detector = null;
  }

  private emit<E extends keyof EventMap>(event: E, payload: EventMap[E]): void {
    const set = this.listeners.get(event);
    if (!set) return;
    for (const cb of set) cb(payload);
  }
}
