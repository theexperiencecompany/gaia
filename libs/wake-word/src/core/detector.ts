import {
  type DetectionEvent,
  type DetectorListener,
  type DetectorOptions,
  type DetectorScoreSample,
  type DetectorState,
  FRAME_SAMPLES,
  type InferenceRuntime,
  type WakeWordModelBundle,
} from "../types/index";
import { WakeWordPipeline } from "./pipeline";
import { VadGate } from "./vad-gate";

const DEFAULT_OPTIONS: Required<DetectorOptions> = {
  threshold: 0.6,
  consecutiveHits: 2,
  cooldownMs: 1500,
  vadGate: true,
  vadThreshold: 0.5,
  vadHangoverMs: 600,
  verifierThreshold: 0.6,
};

/**
 * Cross-platform wake-word detector. Holds the openWakeWord pipeline and
 * (optionally) a Silero VAD pre-gate, and emits events to a listener.
 *
 * The detector accepts arbitrary-length PCM chunks from any source — it
 * internally buffers them into 1280-sample frames before invoking the
 * pipeline. This means callers don't have to align their audio capture.
 */
export class WakeWordDetector {
  private readonly options: Required<DetectorOptions>;
  private readonly pipeline: WakeWordPipeline;
  private readonly vad: VadGate | null;
  private readonly frameBuffer = new Float32Array(FRAME_SAMPLES);
  private frameFill = 0;
  // Serialises overlapping `push()` calls. Callers (e.g. the AudioWorklet
  // message handler) fire pushes without awaiting, so without this chain their
  // awaits could interleave and corrupt the shared frame buffer / counters.
  private chain: Promise<unknown> = Promise.resolve();

  private state: DetectorState = "idle";
  private listener: DetectorListener | null = null;
  private framesProcessed = 0;
  private consecutiveAboveThreshold = 0;
  private lastFireWallMs = 0;
  private syntheticClockMs = 0;
  private useSyntheticClock = false;

  constructor(runtime: InferenceRuntime, options: DetectorOptions = {}) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
    this.pipeline = new WakeWordPipeline(runtime);
    this.vad = this.options.vadGate
      ? new VadGate(
          runtime,
          this.options.vadThreshold,
          this.options.vadHangoverMs,
        )
      : null;
  }

  setListener(listener: DetectorListener | null): void {
    this.listener = listener;
  }

  async load(bundle: WakeWordModelBundle): Promise<void> {
    this.transition("idle");
    await this.pipeline.load(bundle);
    if (this.vad && bundle.vad) {
      await this.vad.load(bundle.vad);
    }
    this.transition("listening");
  }

  /** Use a deterministic clock — required for offline replay / tests. */
  useSyntheticTime(): void {
    this.useSyntheticClock = true;
    this.syntheticClockMs = 0;
    this.vad?.useSyntheticClock();
  }

  async release(): Promise<void> {
    await Promise.all([this.pipeline.release(), this.vad?.release()]);
    this.transition("idle");
  }

  reset(): void {
    this.pipeline.reset();
    this.vad?.reset();
    this.frameFill = 0;
    this.framesProcessed = 0;
    this.consecutiveAboveThreshold = 0;
    this.lastFireWallMs = 0;
    this.syntheticClockMs = 0;
  }

  /**
   * Push PCM samples (any length) at 16 kHz mono. Returns the number of
   * complete 80 ms frames consumed.
   */
  async push(samples: Float32Array): Promise<number> {
    // Run pushes strictly one-at-a-time. Advance the chain regardless of
    // success/failure so a single failed push doesn't poison later ones.
    const result = this.chain.then(() => this.pushInternal(samples));
    this.chain = result.catch(() => undefined);
    return result;
  }

  private async pushInternal(samples: Float32Array): Promise<number> {
    if (this.state === "error" || this.state === "idle") return 0;
    let consumed = 0;
    let offset = 0;
    while (offset < samples.length) {
      const room = FRAME_SAMPLES - this.frameFill;
      const take = Math.min(room, samples.length - offset);
      this.frameBuffer.set(
        samples.subarray(offset, offset + take),
        this.frameFill,
      );
      this.frameFill += take;
      offset += take;
      if (this.frameFill === FRAME_SAMPLES) {
        // Clone the frame before any awaits so the pipeline never holds a
        // reference to the buffer we're about to overwrite for the next frame.
        await this.processFrame(this.frameBuffer.slice());
        this.frameFill = 0;
        consumed += 1;
      }
    }
    return consumed;
  }

  private async processFrame(frame: Float32Array): Promise<void> {
    const frameIndex = this.framesProcessed;
    this.framesProcessed += 1;
    const now = this.now();
    if (this.useSyntheticClock) this.syntheticClockMs += 80;

    let vadProb: number | undefined;
    let vadOpen = true;
    if (this.vad) {
      const result = await this.vad.push(frame, 80);
      vadProb = result.speechProb;
      vadOpen = result.open;
    }

    // Even when the VAD says silence, we still feed the pipeline so its
    // internal state stays warm — but we suppress firing.
    let score: number | null = null;
    try {
      score = await this.pipeline.pushFrame(frame);
    } catch (err) {
      this.transition("error");
      this.listener?.onError?.(err as Error);
      return;
    }

    if (score === null) return;

    const sample: DetectorScoreSample = {
      score,
      timestamp: now,
      frameIndex,
      vadProb,
    };
    this.listener?.onScore?.(sample);

    const inCooldown = now - this.lastFireWallMs < this.options.cooldownMs;
    if (inCooldown) return;

    if (vadOpen && score >= this.options.threshold) {
      this.consecutiveAboveThreshold += 1;
      if (this.consecutiveAboveThreshold >= this.options.consecutiveHits) {
        this.fire(score, now, frameIndex);
      }
    } else {
      this.consecutiveAboveThreshold = 0;
    }
  }

  private fire(score: number, timestamp: number, frameIndex: number): void {
    this.lastFireWallMs = timestamp;
    this.consecutiveAboveThreshold = 0;
    const event: DetectionEvent = { score, timestamp, frameIndex };
    this.transition("detecting");
    this.listener?.onDetection?.(event);
    this.transition("cooldown");
    this.transition("listening");
  }

  private transition(next: DetectorState): void {
    if (next === this.state) return;
    this.state = next;
    this.listener?.onStateChange?.(next);
  }

  private now(): number {
    return this.useSyntheticClock ? this.syntheticClockMs : Date.now();
  }

  /** Diagnostics — current pipeline embedding window (for verifier training). */
  embeddingSnapshot(): Float32Array {
    return this.pipeline.embeddingSnapshot();
  }
}
