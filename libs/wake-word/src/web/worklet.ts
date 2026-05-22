/// <reference lib="webworker" />

/**
 * AudioWorkletProcessor that captures the mic at the AudioContext's native
 * sample rate, downsamples to 16 kHz mono, batches into 1280-sample frames,
 * and posts each frame to the main thread via `port.postMessage`.
 *
 * This file is intended to be served as a module worklet:
 *
 *     await audioContext.audioWorklet.addModule(
 *       new URL("@gaia/wake-word/worklet", import.meta.url),
 *     );
 *
 * Bundlers must keep this file standalone (no shared imports). Hence the
 * inlined linear resampler — it duplicates the logic in core/resampler.ts on
 * purpose so the worklet can run in any worklet global scope.
 */

declare const sampleRate: number;
declare class AudioWorkletProcessor {
  port: MessagePort;
  constructor();
  process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>,
  ): boolean;
}
declare function registerProcessor(
  name: string,
  cls: typeof AudioWorkletProcessor,
): void;

const TARGET_RATE = 16_000;
const FRAME_SAMPLES = 1280;

class WakeWordCaptureProcessor extends AudioWorkletProcessor {
  private readonly ratio: number;
  private readonly frame = new Float32Array(FRAME_SAMPLES);
  private frameFill = 0;
  private resamplerPos = 0;
  private prevLastSample = 0;

  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
  }

  process(inputs: Float32Array[][]): boolean {
    const input = inputs[0]?.[0];
    if (!input || input.length === 0) return true;

    // 1. Downsample to 16 kHz via linear interpolation.
    const expectedOut = Math.floor(
      (input.length + this.resamplerPos) / this.ratio,
    );
    const out = new Float32Array(expectedOut);
    const lastSample = this.prevLastSample;
    for (let i = 0; i < expectedOut; i++) {
      const pos = i * this.ratio - this.resamplerPos;
      const idx = Math.floor(pos);
      const frac = pos - idx;
      const a = idx < 0 ? lastSample : (input[idx] ?? 0);
      const b = input[idx + 1] ?? a;
      out[i] = a + (b - a) * frac;
    }
    this.prevLastSample = input[input.length - 1] ?? this.prevLastSample;
    const consumed = (expectedOut * this.ratio) | 0;
    this.resamplerPos = input.length - consumed + this.resamplerPos;

    // 2. Batch into 80 ms frames and post.
    let offset = 0;
    while (offset < out.length) {
      const room = FRAME_SAMPLES - this.frameFill;
      const take = Math.min(room, out.length - offset);
      this.frame.set(out.subarray(offset, offset + take), this.frameFill);
      this.frameFill += take;
      offset += take;
      if (this.frameFill === FRAME_SAMPLES) {
        // Copy so the main thread receives an immutable snapshot.
        const copy = new Float32Array(FRAME_SAMPLES);
        copy.set(this.frame);
        this.port.postMessage(copy.buffer, [copy.buffer]);
        this.frameFill = 0;
      }
    }
    return true;
  }
}

registerProcessor("gaia-wake-word-capture", WakeWordCaptureProcessor);

// Re-export an empty default so bundlers that import this as a module URL
// don't choke on an "empty" file.
export {};
