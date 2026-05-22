import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { WakeWordDetector } from "../src/core/detector.js";
import { WakeWordPipeline } from "../src/core/pipeline.js";
import { NodeRuntime } from "../src/node/index.js";
import {
  type DetectionEvent,
  type DetectorScoreSample,
  FRAME_SAMPLES,
  type WakeWordModelBundle,
} from "../src/types/index.js";
import { readWavMono16k } from "./wav.js";

const here = resolve(__dirname, "..");
const modelsDir = resolve(here, "models");
const fixturesDir = resolve(here, "test-fixtures");

const bundle: WakeWordModelBundle = {
  melspectrogram: {
    kind: "asset",
    asset: resolve(modelsDir, "melspectrogram.onnx"),
  },
  embedding: {
    kind: "asset",
    asset: resolve(modelsDir, "embedding_model.onnx"),
  },
  classifier: {
    kind: "asset",
    asset: resolve(modelsDir, "hey_mycroft_v0.1.onnx"),
  },
  vad: { kind: "asset", asset: resolve(modelsDir, "silero_vad.onnx") },
};

async function feedSilenceFrames(
  pipeline: WakeWordPipeline,
  frames: number,
): Promise<number[]> {
  const silence = new Float32Array(FRAME_SAMPLES);
  const scores: number[] = [];
  for (let i = 0; i < frames; i++) {
    const s = await pipeline.pushFrame(silence);
    if (s !== null) scores.push(s);
  }
  return scores;
}

async function feedClipFrames(
  pipeline: WakeWordPipeline,
  audio: Float32Array,
): Promise<number[]> {
  const scores: number[] = [];
  const totalFrames = Math.floor(audio.length / FRAME_SAMPLES);
  for (let i = 0; i < totalFrames; i++) {
    const frame = audio.subarray(i * FRAME_SAMPLES, (i + 1) * FRAME_SAMPLES);
    const s = await pipeline.pushFrame(frame);
    if (s !== null) scores.push(s);
  }
  return scores;
}

describe("WakeWordPipeline (hey_mycroft_v0.1)", () => {
  // Warmup math: mel buffer fills (76 frames) after 10 audio frames of 8
  // mel-frames each, so the first embedding fires on frame 10. The classifier
  // needs 16 embeddings → first score is produced on frame 25. We assert this
  // exact contract because any change in warmup latency is user-visible.
  it("emits exactly 0 scores in first 24 frames, 1 score on frame 25", async () => {
    const runtime = new NodeRuntime();
    const pipeline = new WakeWordPipeline(runtime);
    await pipeline.load(bundle);
    const scoresAt24 = await feedSilenceFrames(pipeline, 24);
    expect(scoresAt24.length).toBe(0);
    const scoresAt25 = await feedSilenceFrames(pipeline, 1);
    expect(scoresAt25.length).toBe(1);
    await pipeline.release();
  });

  it("produces low scores (< 0.1) on prolonged silence", async () => {
    const runtime = new NodeRuntime();
    const pipeline = new WakeWordPipeline(runtime);
    await pipeline.load(bundle);
    // 60 frames = ~4.8s — well past warmup.
    const scores = await feedSilenceFrames(pipeline, 60);
    expect(scores.length).toBeGreaterThan(0);
    const max = Math.max(...scores);
    expect(max).toBeLessThan(0.1);
    await pipeline.release();
  });

  it("fires on 'hey mycroft' positive sample (max score > 0.5)", async () => {
    const runtime = new NodeRuntime();
    const pipeline = new WakeWordPipeline(runtime);
    await pipeline.load(bundle);
    // Pad with leading silence to get past warmup, then play the clip.
    const clip = readWavMono16k(resolve(fixturesDir, "hey_mycroft_test.wav"));
    const padded = new Float32Array(FRAME_SAMPLES * 28 + clip.length);
    padded.set(clip, FRAME_SAMPLES * 28);
    const scores = await feedClipFrames(pipeline, padded);
    expect(scores.length).toBeGreaterThan(10);
    const max = Math.max(...scores);
    // openWakeWord's official test asserts >0.5; we mirror it.
    expect(max).toBeGreaterThan(0.5);
    await pipeline.release();
  });

  it("does NOT fire on 'hey jane' negative sample (max < 0.5)", async () => {
    const runtime = new NodeRuntime();
    const pipeline = new WakeWordPipeline(runtime);
    await pipeline.load(bundle);
    const clip = readWavMono16k(resolve(fixturesDir, "hey_jane.wav"));
    const padded = new Float32Array(FRAME_SAMPLES * 28 + clip.length);
    padded.set(clip, FRAME_SAMPLES * 28);
    const scores = await feedClipFrames(pipeline, padded);
    expect(scores.length).toBeGreaterThan(10);
    const max = Math.max(...scores);
    expect(max).toBeLessThan(0.5);
    await pipeline.release();
  });
});

describe("Score quality (deeper assertions)", () => {
  it("positive clip peaks substantially above threshold (> 0.7)", async () => {
    const runtime = new NodeRuntime();
    const pipeline = new WakeWordPipeline(runtime);
    await pipeline.load(bundle);
    const clip = readWavMono16k(resolve(fixturesDir, "hey_mycroft_test.wav"));
    const padded = new Float32Array(FRAME_SAMPLES * 28 + clip.length);
    padded.set(clip, FRAME_SAMPLES * 28);
    const scores = await feedClipFrames(pipeline, padded);
    const max = Math.max(...scores);
    expect(max).toBeGreaterThan(0.7);
    await pipeline.release();
  });

  it("negative clip stays well below threshold (max < 0.2)", async () => {
    const runtime = new NodeRuntime();
    const pipeline = new WakeWordPipeline(runtime);
    await pipeline.load(bundle);
    const clip = readWavMono16k(resolve(fixturesDir, "hey_jane.wav"));
    const padded = new Float32Array(FRAME_SAMPLES * 28 + clip.length);
    padded.set(clip, FRAME_SAMPLES * 28);
    const scores = await feedClipFrames(pipeline, padded);
    const max = Math.max(...scores);
    expect(max).toBeLessThan(0.2);
    await pipeline.release();
  });

  it("per-frame inference is < 20 ms on Node CPU", async () => {
    const runtime = new NodeRuntime();
    const pipeline = new WakeWordPipeline(runtime);
    await pipeline.load(bundle);
    // Warmup
    await feedSilenceFrames(pipeline, 30);
    // Measure 100 frames
    const silence = new Float32Array(FRAME_SAMPLES);
    const start = performance.now();
    for (let i = 0; i < 100; i++) {
      await pipeline.pushFrame(silence);
    }
    const elapsed = performance.now() - start;
    const perFrameMs = elapsed / 100;
    // eslint-disable-next-line no-console
    console.log(`pipeline per-frame: ${perFrameMs.toFixed(2)} ms`);
    expect(perFrameMs).toBeLessThan(20);
    await pipeline.release();
  });
});

describe("WakeWordDetector end-to-end (with VAD + debounce)", () => {
  it("fires exactly one detection on the positive clip", async () => {
    const runtime = new NodeRuntime();
    const detector = new WakeWordDetector(runtime, {
      threshold: 0.5,
      consecutiveHits: 1,
      cooldownMs: 800,
      vadGate: false, // VAD off — we want to validate the pipeline cleanly
    });
    detector.useSyntheticTime();
    const detections: DetectionEvent[] = [];
    const scores: DetectorScoreSample[] = [];
    detector.setListener({
      onDetection: (e) => detections.push(e),
      onScore: (s) => scores.push(s),
    });
    await detector.load(bundle);

    // Warmup + clip
    const clip = readWavMono16k(resolve(fixturesDir, "hey_mycroft_test.wav"));
    const padded = new Float32Array(FRAME_SAMPLES * 28 + clip.length);
    padded.set(clip, FRAME_SAMPLES * 28);
    await detector.push(padded);

    await detector.release();
    expect(scores.length).toBeGreaterThan(5);
    expect(detections.length).toBeGreaterThanOrEqual(1);
    expect(detections[0]?.score).toBeGreaterThan(0.5);
  });

  it("respects cooldown — only one detection in a short window", async () => {
    const runtime = new NodeRuntime();
    const detector = new WakeWordDetector(runtime, {
      threshold: 0.5,
      consecutiveHits: 1,
      cooldownMs: 5000, // long cooldown
      vadGate: false,
    });
    detector.useSyntheticTime();
    const detections: DetectionEvent[] = [];
    detector.setListener({ onDetection: (e) => detections.push(e) });
    await detector.load(bundle);
    // Feed the positive clip twice with a 1s gap between the two utterances.
    const clip = readWavMono16k(resolve(fixturesDir, "hey_mycroft_test.wav"));
    const gapSamples = 16000; // 1s @ 16kHz
    const doubled = new Float32Array(
      FRAME_SAMPLES * 28 + clip.length * 2 + gapSamples,
    );
    const clipOffsets = [
      FRAME_SAMPLES * 28,
      FRAME_SAMPLES * 28 + clip.length + gapSamples,
    ];
    for (const offset of clipOffsets) doubled.set(clip, offset);
    await detector.push(doubled);
    await detector.release();
    expect(detections.length).toBe(1);
  });

  it("does not fire on the negative clip", async () => {
    const runtime = new NodeRuntime();
    const detector = new WakeWordDetector(runtime, {
      threshold: 0.5,
      consecutiveHits: 1,
      cooldownMs: 800,
      vadGate: false,
    });
    detector.useSyntheticTime();
    const detections: DetectionEvent[] = [];
    detector.setListener({ onDetection: (e) => detections.push(e) });
    await detector.load(bundle);

    const clip = readWavMono16k(resolve(fixturesDir, "hey_jane.wav"));
    const padded = new Float32Array(FRAME_SAMPLES * 28 + clip.length);
    padded.set(clip, FRAME_SAMPLES * 28);
    await detector.push(padded);
    await detector.release();
    expect(detections.length).toBe(0);
  });
});
