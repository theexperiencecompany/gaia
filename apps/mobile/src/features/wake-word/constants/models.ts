import type { WakeWordModelBundle } from "@gaia/wake-word";

/**
 * Default RN model bundle. The ONNX files are bundled as static assets and
 * referenced via `require()` so Metro picks them up.
 *
 * If you train a fresh hey_gaia.onnx, replace assets/wake-word/hey_gaia.onnx
 * and re-bundle.
 */
export const HEY_GAIA_MODEL_BUNDLE: WakeWordModelBundle = {
  melspectrogram: {
    kind: "asset",
    asset: require("../../../../assets/wake-word/melspectrogram.onnx"),
  },
  embedding: {
    kind: "asset",
    asset: require("../../../../assets/wake-word/embedding_model.onnx"),
  },
  classifier: {
    kind: "asset",
    asset: require("../../../../assets/wake-word/hey_gaia.onnx"),
  },
  vad: {
    kind: "asset",
    asset: require("../../../../assets/wake-word/silero_vad.onnx"),
  },
};
