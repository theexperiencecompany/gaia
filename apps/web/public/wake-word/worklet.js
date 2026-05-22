/**
 * AudioWorkletProcessor for the @gaia/wake-word capture path.
 *
 * Runs in the AudioWorkletGlobalScope (no DOM, no module imports). Mirrors
 * `libs/wake-word/src/web/worklet.ts` — kept as plain JS so any bundler /
 * browser can load it directly via `audioContext.audioWorklet.addModule()`
 * without a TypeScript step.
 *
 * Captures mic at the AudioContext's native sample rate, downsamples to
 * 16 kHz mono via linear interpolation, and batches into 1280-sample (80 ms)
 * frames that are posted to the main thread as transferable ArrayBuffers.
 */

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 1280;

class WakeWordCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.frame = new Float32Array(FRAME_SAMPLES);
    this.frameFill = 0;
    this.resamplerPos = 0;
    this.prevLastSample = 0;
  }

  process(inputs) {
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
      const a = idx < 0 ? lastSample : input[idx] || 0;
      const b = input[idx + 1] ?? a;
      out[i] = a + (b - a) * frac;
    }
    this.prevLastSample = input[input.length - 1] || this.prevLastSample;
    const consumed = Math.trunc(expectedOut * this.ratio);
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
