/**
 * Public types for @gaia/wake-word.
 *
 * Pipeline: PCM (16 kHz mono) → melspectrogram → speech embedding → classifier head.
 * Models are stored as ONNX and shared across web/electron/react-native via thin runtime adapters.
 */

export const SAMPLE_RATE = 16_000;
export const FRAME_SAMPLES = 1280; // 80 ms @ 16 kHz — the openWakeWord native frame
export const MEL_FRAMES_PER_CHUNK = 76; // melspec window the embedding model expects
export const EMBEDDING_DIM = 96; // speech_embedding output dim
export const CLASSIFIER_WINDOW = 16; // sequence length the classifier head expects

export type DetectorState =
  | "idle"
  | "listening"
  | "detecting"
  | "cooldown"
  | "error";

export interface DetectionEvent {
  /** Calibrated probability in [0, 1] from the classifier head. */
  score: number;
  /** Wall-clock timestamp (ms since epoch). */
  timestamp: number;
  /** Frame index since detector start — useful for offline analysis. */
  frameIndex: number;
  /** Optional verifier output if a per-user verifier model is configured. */
  verifierScore?: number;
}

export interface DetectorScoreSample {
  score: number;
  timestamp: number;
  frameIndex: number;
  vadProb?: number;
}

export interface WakeWordModelBundle {
  /** Mel spectrogram preprocessor ONNX URL or asset locator. */
  melspectrogram: ModelSource;
  /** Frozen speech embedding model ONNX URL or asset locator. */
  embedding: ModelSource;
  /** Custom-trained classifier head ONNX URL or asset locator. */
  classifier: ModelSource;
  /** Optional Silero VAD model for pre-gating (highly recommended). */
  vad?: ModelSource;
  /** Optional per-user verifier model (logistic regression on embeddings). */
  verifier?: ModelSource;
}

/**
 * A model can be referenced by URL (web), bundled asset (react-native),
 * or raw bytes (anywhere). The adapter resolves it for its runtime.
 */
export type ModelSource =
  | { kind: "url"; url: string }
  | { kind: "asset"; asset: string | number }
  | { kind: "bytes"; bytes: ArrayBuffer | Uint8Array };

export interface DetectorOptions {
  /**
   * Wake-word probability threshold. Higher → fewer false positives, more false rejects.
   * openWakeWord scores are well-calibrated; start at 0.6 and tune.
   */
  threshold?: number;
  /**
   * Number of consecutive frames above threshold required to fire.
   * Acts as a debounce; defaults to 2 (≈160 ms of evidence).
   */
  consecutiveHits?: number;
  /**
   * Refractory period after a detection (ms). Default 1500 ms — prevents
   * stutter-fires when the user is mid-conversation.
   */
  cooldownMs?: number;
  /**
   * If true, skip wake-word inference when Silero VAD reports < vadThreshold
   * speech probability. Default true; major false-positive reducer.
   */
  vadGate?: boolean;
  vadThreshold?: number;
  /**
   * Sustained-quiet window (ms) after which to release the VAD gate. Default 500 ms.
   */
  vadHangoverMs?: number;
  /**
   * Optional verifier threshold (0..1). Only fires if the per-user
   * verifier model also clears this. Default 0.6.
   */
  verifierThreshold?: number;
}

/**
 * Minimal contract a runtime adapter implements. Web wraps onnxruntime-web,
 * native wraps onnxruntime-react-native. The core detector is runtime-agnostic.
 */
export interface InferenceSession {
  run(
    feeds: Record<string, TypedTensor>,
    outputNames?: readonly string[],
  ): Promise<Record<string, TypedTensor>>;
  inputNames(): readonly string[];
  outputNames(): readonly string[];
  release(): Promise<void>;
}

export interface TypedTensor {
  readonly data: Float32Array | Int32Array | BigInt64Array;
  readonly dims: readonly number[];
  readonly type: "float32" | "int32" | "int64";
}

export interface InferenceRuntime {
  loadSession(source: ModelSource): Promise<InferenceSession>;
  /** Create a float32 tensor with the given shape. Adapter handles native bindings. */
  tensor(data: Float32Array, dims: readonly number[]): TypedTensor;
  /** Create an int64 tensor (Silero VAD `sr` input needs this). */
  int64(value: bigint | number, dims?: readonly number[]): TypedTensor;
}

export type FrameSource = AsyncIterable<Float32Array>;

export interface DetectorListener {
  onDetection?(event: DetectionEvent): void;
  onScore?(sample: DetectorScoreSample): void;
  onStateChange?(state: DetectorState): void;
  onError?(error: Error): void;
}
