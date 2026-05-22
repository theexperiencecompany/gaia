import { SAMPLE_RATE } from "../types/index";

/**
 * Lightweight linear resampler. The wake-word model is trained at 16 kHz mono.
 * Mobile/desktop mic outputs are commonly 44.1 / 48 kHz — we downsample on the
 * fly with linear interpolation. Quality is enough for keyword spotting; if
 * fidelity becomes an issue we can drop in a polyphase FIR later.
 *
 * Stateful: preserves the last sample across calls so chunk boundaries don't
 * introduce discontinuities.
 */
export class LinearResampler {
  private readonly ratio: number;
  private leftover = 0;
  private positionInSrc = 0;

  constructor(public readonly sourceRate: number) {
    if (sourceRate <= 0) throw new Error("sourceRate must be positive");
    this.ratio = sourceRate / SAMPLE_RATE;
  }

  /** Returns a new Float32Array sized to the resampled length. */
  process(input: Float32Array): Float32Array {
    if (this.sourceRate === SAMPLE_RATE) return input;
    const outLen = Math.floor((input.length + this.positionInSrc) / this.ratio);
    const out = new Float32Array(outLen);
    const srcPos = -this.positionInSrc;
    for (let i = 0; i < outLen; i++) {
      const pos = srcPos + i * this.ratio;
      const idx = Math.floor(pos);
      const frac = pos - idx;
      const a = idx < 0 ? this.leftover : (input[idx] ?? 0);
      const b = input[idx + 1] ?? a;
      out[i] = a + (b - a) * frac;
    }
    // remember fractional offset and last sample for next call
    const consumed = Math.floor(srcPos + outLen * this.ratio) + 1;
    this.positionInSrc = consumed - input.length;
    this.leftover = input.at(-1) ?? this.leftover;
    return out;
  }

  reset(): void {
    this.leftover = 0;
    this.positionInSrc = 0;
  }
}
