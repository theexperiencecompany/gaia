import {
  CLASSIFIER_WINDOW,
  EMBEDDING_DIM,
  FRAME_SAMPLES,
  type InferenceRuntime,
  type InferenceSession,
  MEL_FRAMES_PER_CHUNK,
  type WakeWordModelBundle,
} from "../types/index";

/**
 * openWakeWord-compatible 3-stage streaming pipeline.
 *
 *   PCM(1280) ─► melspec(480+1280) ─► mel(8×32) ─► append to melBuffer
 *   melBuffer(76×32) ─► embedding ─► emb(96) ─► push to embeddingRing
 *   embeddingRing(16×96) ─► classifier ─► score
 *
 * Verified against v0.5.1 model exports:
 *   • melspectrogram.onnx input "input" [batch, samples] → output [1,1,T,32]
 *     where T = (samples − 480) / 160. So 1280 samples alone gives 5 frames,
 *     but feeding (last 480 of previous frame) + 1280 new samples = 1760 samples
 *     yields exactly 8 NEW mel frames per 80 ms — matching the 10 ms hop the
 *     embedding model was trained against.
 *   • embedding_model.onnx input "input_1" [N, 76, 32, 1] → "conv2d_19" [N,1,1,96]
 *   • classifier (e.g. hey_jarvis_v0.1) input "x.1" [1, 16, 96] → [1, 1] scalar
 */

const MELSPEC_WINDOW = 480; // analysis window in samples (30 ms)
const MELSPEC_HOP = 160; // analysis hop in samples (10 ms)
const NEW_MEL_FRAMES_PER_AUDIO_FRAME = 8; // 80 ms / 10 ms
const MEL_FEATURE_DIM = 32;

export class WakeWordPipeline {
  private melSession: InferenceSession | null = null;
  private embSession: InferenceSession | null = null;
  private clsSession: InferenceSession | null = null;

  private melInputName = "input";
  private embInputName = "input_1";
  private clsInputName = "x.1";

  private readonly audioContext = new Float32Array(MELSPEC_WINDOW); // 480 samples of carry-over
  private readonly melInput = new Float32Array(MELSPEC_WINDOW + FRAME_SAMPLES); // 1760 samples
  private hasAudioContext = false;

  private readonly melBuffer = new Float32Array(
    MEL_FRAMES_PER_CHUNK * MEL_FEATURE_DIM,
  ); // 76 × 32 ring of latest mel frames
  private melFramesBuffered = 0;

  /** Embeddings stored sequentially in a ring; classifier needs them ordered oldest→newest. */
  private readonly embeddingRing = new Float32Array(
    CLASSIFIER_WINDOW * EMBEDDING_DIM,
  );
  private embeddingWriteIdx = 0;
  private embeddingsSeen = 0;

  /** How often (in audio frames since last embedding) we run the embedding+classifier. */
  private framesSinceLastEmbedding = 0;
  /** Run embedding every N audio frames. openWakeWord default is 1 (every 80 ms). */
  readonly embeddingStride = 1;

  constructor(private readonly runtime: InferenceRuntime) {}

  async load(bundle: WakeWordModelBundle): Promise<void> {
    const [mel, emb, cls] = await Promise.all([
      this.runtime.loadSession(bundle.melspectrogram),
      this.runtime.loadSession(bundle.embedding),
      this.runtime.loadSession(bundle.classifier),
    ]);
    this.melSession = mel;
    this.embSession = emb;
    this.clsSession = cls;
    const melInputs = mel.inputNames();
    const embInputs = emb.inputNames();
    const clsInputs = cls.inputNames();
    if (melInputs[0]) this.melInputName = melInputs[0];
    if (embInputs[0]) this.embInputName = embInputs[0];
    if (clsInputs[0]) this.clsInputName = clsInputs[0];
  }

  /**
   * Push one frame (FRAME_SAMPLES = 1280 samples @ 16 kHz mono) of audio.
   * Returns the latest classifier score in [0, 1] once warmup is complete,
   * otherwise null. Warmup takes ~26 frames (~2.1 s) of audio.
   */
  async pushFrame(frame: Float32Array): Promise<number | null> {
    if (frame.length !== FRAME_SAMPLES) {
      throw new Error(
        `Frame must be ${FRAME_SAMPLES} samples, got ${frame.length}`,
      );
    }
    const melSession = this.melSession;
    if (!melSession || !this.embSession || !this.clsSession) {
      throw new Error("Pipeline.load() not called");
    }

    // 1. Build mel input: last 480 audio samples (or zeros on first call) + new 1280.
    if (this.hasAudioContext) {
      this.melInput.set(this.audioContext, 0);
    } else {
      this.melInput.fill(0, 0, MELSPEC_WINDOW);
    }
    this.melInput.set(frame, MELSPEC_WINDOW);

    // 2. Run melspec → produces NEW_MEL_FRAMES_PER_AUDIO_FRAME (8) frames.
    const melTensor = this.runtime.tensor(this.melInput, [
      1,
      MELSPEC_WINDOW + FRAME_SAMPLES,
    ]);
    const melOut = await melSession.run({ [this.melInputName]: melTensor });
    const melResult = Object.values(melOut)[0];
    if (!melResult || !(melResult.data instanceof Float32Array)) {
      throw new Error("melspectrogram returned unexpected tensor");
    }
    const expectedFrames =
      (MELSPEC_WINDOW + FRAME_SAMPLES - MELSPEC_WINDOW) / MELSPEC_HOP; // = 8
    const actualFrames = melResult.data.length / MEL_FEATURE_DIM;
    if (Math.abs(actualFrames - expectedFrames) > 0.5) {
      throw new Error(
        `melspec produced ${actualFrames} frames, expected ${expectedFrames}`,
      );
    }
    // openWakeWord applies a calibration transform: x / 10 + 2.
    const melframes = new Float32Array(melResult.data.length);
    for (let i = 0; i < melframes.length; i++) {
      melframes[i] = (melResult.data[i] ?? 0) / 10 + 2;
    }

    // 3. Slide mel buffer and append.
    this.appendMelFrames(melframes, NEW_MEL_FRAMES_PER_AUDIO_FRAME);

    // 4. Save context for next call (last 480 samples of the current 1280 frame).
    this.audioContext.set(frame.subarray(FRAME_SAMPLES - MELSPEC_WINDOW));
    this.hasAudioContext = true;

    this.framesSinceLastEmbedding += 1;
    if (
      this.melFramesBuffered < MEL_FRAMES_PER_CHUNK ||
      this.framesSinceLastEmbedding < this.embeddingStride
    ) {
      return null;
    }
    this.framesSinceLastEmbedding = 0;

    // 5. Run embedding model on the latest 76 mel frames.
    const embeddingInput = this.runtime.tensor(this.melBuffer, [
      1,
      MEL_FRAMES_PER_CHUNK,
      MEL_FEATURE_DIM,
      1,
    ]);
    const embOut = await this.embSession.run({
      [this.embInputName]: embeddingInput,
    });
    const embResult = Object.values(embOut)[0];
    if (!embResult || !(embResult.data instanceof Float32Array)) {
      throw new Error("embedding_model returned unexpected tensor");
    }
    // Output is [1,1,1,96] — take first 96 floats.
    this.pushEmbedding(embResult.data);

    if (this.embeddingsSeen < CLASSIFIER_WINDOW) return null;

    // 6. Run classifier on the ring (ordered oldest→newest).
    return this.runClassifier();
  }

  /** Snapshot of the 16 most-recent embeddings, ordered oldest→newest. */
  embeddingSnapshot(): Float32Array {
    const out = new Float32Array(CLASSIFIER_WINDOW * EMBEDDING_DIM);
    for (let i = 0; i < CLASSIFIER_WINDOW; i++) {
      const srcIdx =
        ((this.embeddingWriteIdx + i) % CLASSIFIER_WINDOW) * EMBEDDING_DIM;
      out.set(
        this.embeddingRing.subarray(srcIdx, srcIdx + EMBEDDING_DIM),
        i * EMBEDDING_DIM,
      );
    }
    return out;
  }

  reset(): void {
    this.audioContext.fill(0);
    this.hasAudioContext = false;
    this.melBuffer.fill(0);
    this.melFramesBuffered = 0;
    this.embeddingRing.fill(0);
    this.embeddingWriteIdx = 0;
    this.embeddingsSeen = 0;
    this.framesSinceLastEmbedding = 0;
  }

  async release(): Promise<void> {
    await Promise.all([
      this.melSession?.release(),
      this.embSession?.release(),
      this.clsSession?.release(),
    ]);
    this.melSession = this.embSession = this.clsSession = null;
  }

  private appendMelFrames(frames: Float32Array, frameCount: number): void {
    const dim = MEL_FEATURE_DIM;
    const incomingSamples = frameCount * dim;
    if (frames.length < incomingSamples) {
      throw new Error("mel frame buffer underflow");
    }
    const cap = this.melBuffer.length;
    const heldSamples = this.melFramesBuffered * dim;
    if (heldSamples + incomingSamples <= cap) {
      this.melBuffer.set(frames.subarray(0, incomingSamples), heldSamples);
      this.melFramesBuffered += frameCount;
      return;
    }
    // Need to shift out (heldSamples + incomingSamples - cap) samples
    const shiftBy = heldSamples + incomingSamples - cap;
    this.melBuffer.copyWithin(0, shiftBy, heldSamples);
    this.melBuffer.set(
      frames.subarray(0, incomingSamples),
      heldSamples - shiftBy,
    );
    this.melFramesBuffered = MEL_FRAMES_PER_CHUNK;
  }

  private pushEmbedding(data: Float32Array): void {
    const offset = this.embeddingWriteIdx * EMBEDDING_DIM;
    this.embeddingRing.set(data.subarray(0, EMBEDDING_DIM), offset);
    this.embeddingWriteIdx = (this.embeddingWriteIdx + 1) % CLASSIFIER_WINDOW;
    this.embeddingsSeen = Math.min(this.embeddingsSeen + 1, 1_000_000);
  }

  private async runClassifier(): Promise<number> {
    const session = this.clsSession;
    if (!session) return 0;
    const snapshot = this.embeddingSnapshot();
    const tensor = this.runtime.tensor(snapshot, [
      1,
      CLASSIFIER_WINDOW,
      EMBEDDING_DIM,
    ]);
    const out = await session.run({ [this.clsInputName]: tensor });
    const result = Object.values(out)[0];
    if (!result || !(result.data instanceof Float32Array)) return 0;
    return result.data[0] ?? 0;
  }
}
