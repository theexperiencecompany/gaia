import type {
  InferenceRuntime,
  InferenceSession,
  ModelSource,
  TypedTensor,
} from "../types/index";

/**
 * Silero VAD gate (v3/v4 signature, bundled with openWakeWord v0.5.1).
 *
 * Model signature (probed empirically, see models/.fetch/probe.py):
 *   inputs:  input [batch, sequence] f32, sr [] i64, h [2,batch,64] f32, c [2,batch,64] f32
 *   outputs: output [batch, 1] f32, hn [2,batch,64] f32, cn [2,batch,64] f32
 *
 * We use 512-sample windows (Silero's recommended frame size for 16 kHz).
 * The "gate" semantics: remember the most recent moment we saw probability
 * above `threshold`, and stay open for `hangoverMs` after that. Sustained
 * background noise pulses below threshold → gate closes; speech keeps it open.
 */
export class VadGate {
  static readonly FRAME_SAMPLES = 512;

  private session: InferenceSession | null = null;
  private readonly buffer = new Float32Array(VadGate.FRAME_SAMPLES);
  private bufferFill = 0;
  private readonly hState = new Float32Array(2 * 1 * 64);
  private readonly cState = new Float32Array(2 * 1 * 64);
  private lastSpeechMs = 0;
  /** Most recent per-frame VAD probability. */
  private latestProb = 0;
  private syntheticMs = 0;
  private useSynthetic = false;

  constructor(
    private readonly runtime: InferenceRuntime,
    public readonly threshold: number,
    public readonly hangoverMs: number,
  ) {}

  async load(source: ModelSource): Promise<void> {
    this.session = await this.runtime.loadSession(source);
  }

  /**
   * In tests / offline replay we need a deterministic clock. When called the
   * gate uses `syntheticMs` instead of `Date.now()`; advance it via the
   * `syntheticAdvanceMs` argument to `push()`.
   */
  useSyntheticClock(): void {
    this.useSynthetic = true;
    this.syntheticMs = 0;
  }

  async push(
    samples: Float32Array,
    syntheticAdvanceMs = 0,
  ): Promise<{ speechProb: number; open: boolean }> {
    if (!this.session) throw new Error("VadGate.load() not called");

    let offset = 0;
    while (offset < samples.length) {
      const room = VadGate.FRAME_SAMPLES - this.bufferFill;
      const take = Math.min(room, samples.length - offset);
      this.buffer.set(samples.subarray(offset, offset + take), this.bufferFill);
      this.bufferFill += take;
      offset += take;
      if (this.bufferFill === VadGate.FRAME_SAMPLES) {
        this.latestProb = await this.runFrame();
        this.bufferFill = 0;
        if (this.latestProb >= this.threshold) {
          this.lastSpeechMs = this.now();
        }
      }
    }

    if (this.useSynthetic) this.syntheticMs += syntheticAdvanceMs;
    const now = this.now();
    const open =
      this.lastSpeechMs > 0 && now - this.lastSpeechMs <= this.hangoverMs;
    return { speechProb: this.latestProb, open };
  }

  reset(): void {
    this.buffer.fill(0);
    this.bufferFill = 0;
    this.hState.fill(0);
    this.cState.fill(0);
    this.lastSpeechMs = 0;
    this.latestProb = 0;
    this.syntheticMs = 0;
  }

  async release(): Promise<void> {
    await this.session?.release();
    this.session = null;
  }

  private now(): number {
    return this.useSynthetic ? this.syntheticMs : Date.now();
  }

  private async runFrame(): Promise<number> {
    const session = this.session;
    if (!session) return 0;
    const feeds: Record<string, TypedTensor> = {
      input: this.runtime.tensor(this.buffer, [1, VadGate.FRAME_SAMPLES]),
      sr: this.runtime.int64(16000),
      h: this.runtime.tensor(this.hState, [2, 1, 64]),
      c: this.runtime.tensor(this.cState, [2, 1, 64]),
    };
    const out = await session.run(feeds);
    const prob = out.output;
    const hn = out.hn;
    const cn = out.cn;
    if (hn && hn.data instanceof Float32Array) this.hState.set(hn.data);
    if (cn && cn.data instanceof Float32Array) this.cState.set(cn.data);
    if (!prob || !(prob.data instanceof Float32Array)) return 0;
    return prob.data[0] ?? 0;
  }
}
