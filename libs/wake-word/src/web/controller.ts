import { WakeWordDetector } from "../core/detector";
import type {
  DetectionEvent,
  DetectorListener,
  DetectorOptions,
  DetectorState,
  WakeWordModelBundle,
} from "../types/index";
import { WebRuntime, type WebRuntimeOptions } from "./runtime";

/**
 * High-level controller that owns the AudioContext, AudioWorklet, and detector
 * lifecycle for a browser or Electron renderer. Designed to be used directly,
 * or wrapped in a React hook (see `useWakeWord` in `react.ts`).
 *
 *     const controller = new WakeWordController({
 *       models: { ... }, // ModelSource per stage
 *       workletUrl: new URL("@gaia/wake-word/worklet", import.meta.url),
 *     });
 *     controller.on("detection", e => console.log("WAKE", e));
 *     await controller.start();
 *     // ...
 *     await controller.stop();
 */

export interface WakeWordControllerOptions {
  models: WakeWordModelBundle;
  /** URL of the AudioWorklet bundle (see `web/worklet.ts`). */
  workletUrl: URL | string;
  /** Detector tuning. */
  detector?: DetectorOptions;
  /** ORT-Web runtime tuning. */
  runtime?: WebRuntimeOptions;
  /** Override `getUserMedia` constraints. */
  audioConstraints?: MediaTrackConstraints;
}

type EventMap = {
  detection: DetectionEvent;
  state: DetectorState;
  error: Error;
  score: number;
};

export class WakeWordController {
  private detector: WakeWordDetector | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private stream: MediaStream | null = null;
  private listeners = new Map<
    keyof EventMap,
    Set<(payload: unknown) => void>
  >();
  private starting = false;

  constructor(private readonly opts: WakeWordControllerOptions) {}

  on<E extends keyof EventMap>(
    event: E,
    cb: (payload: EventMap[E]) => void,
  ): () => void {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    set.add(cb as (payload: unknown) => void);
    return () => set?.delete(cb as (payload: unknown) => void);
  }

  /**
   * Acquire mic, load models, start the AudioWorklet. Resolves once the
   * detector is in `listening` state (warmup will follow over ~2 s of audio).
   */
  async start(): Promise<void> {
    if (this.starting || this.detector) return;
    this.starting = true;
    let detector: WakeWordDetector | null = null;
    try {
      const runtime = new WebRuntime(this.opts.runtime);
      detector = new WakeWordDetector(runtime, this.opts.detector);
      const detectorListener: DetectorListener = {
        onDetection: (e) => this.emit("detection", e),
        onStateChange: (s) => this.emit("state", s),
        onScore: (s) => this.emit("score", s.score),
        onError: (err) => this.emit("error", err),
      };
      detector.setListener(detectorListener);
      await detector.load(this.opts.models);

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: this.opts.audioConstraints ?? {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      this.stream = stream;

      const context = new AudioContext({ latencyHint: "interactive" });
      this.context = context;
      await context.audioWorklet.addModule(this.opts.workletUrl.toString());
      const source = context.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(context, "gaia-wake-word-capture");
      this.node = node;
      const activeDetector = detector;
      node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        const frame = new Float32Array(event.data);
        void activeDetector.push(frame);
      };
      source.connect(node);
      // Only mark as started once every resource is wired up. If anything
      // above threw, `this.detector` stays null so a later start() can retry.
      this.detector = detector;
    } catch (err) {
      await detector?.release().catch(() => undefined);
      await this.stop();
      throw err;
    } finally {
      this.starting = false;
    }
  }

  async stop(): Promise<void> {
    this.node?.port.close();
    this.node?.disconnect();
    this.node = null;
    if (this.stream) {
      for (const track of this.stream.getTracks()) track.stop();
      this.stream = null;
    }
    await this.context?.close();
    this.context = null;
    await this.detector?.release();
    this.detector = null;
  }

  private emit<E extends keyof EventMap>(event: E, payload: EventMap[E]): void {
    const set = this.listeners.get(event);
    if (!set) return;
    for (const cb of set) cb(payload);
  }
}
