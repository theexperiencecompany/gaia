import type { WakeWordModelBundle } from "@gaia/wake-word";

/**
 * Default model bundle for the web app. The ONNX files are served from
 * `public/wake-word/` so the browser can fetch them with cache headers.
 *
 * If you train a new hey_gaia.onnx, drop it in `public/wake-word/` and bump
 * the path here.
 */
export const HEY_GAIA_MODEL_BUNDLE: WakeWordModelBundle = {
  melspectrogram: { kind: "url", url: "/wake-word/melspectrogram.onnx" },
  embedding: { kind: "url", url: "/wake-word/embedding_model.onnx" },
  classifier: { kind: "url", url: "/wake-word/hey_gaia.onnx" },
  vad: { kind: "url", url: "/wake-word/silero_vad.onnx" },
};
