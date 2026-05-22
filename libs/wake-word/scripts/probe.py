"""Run actual inference with synthetic inputs to confirm output shapes and
behavior. This is the ground truth for the TS pipeline."""

import json
from pathlib import Path

import numpy as np
import onnxruntime as ort


def main() -> None:
    here = Path(__file__).parent
    out: dict = {}
    rng = np.random.default_rng()

    # ---- melspectrogram ----
    mel = ort.InferenceSession(str(here / "melspectrogram.onnx"))
    for samples in (1280, 2 * 1280, 4 * 1280, 1600):
        audio = rng.standard_normal((1, samples)).astype(np.float32) * 0.05
        r = mel.run(None, {"input": audio})
        out.setdefault("melspectrogram", []).append(
            {"input_samples": samples, "output_shape": list(r[0].shape)}
        )

    # ---- embedding_model ----
    emb = ort.InferenceSession(str(here / "embedding_model.onnx"))
    mel_chunk = rng.standard_normal((1, 76, 32, 1)).astype(np.float32)
    r = emb.run(None, {"input_1": mel_chunk})
    out["embedding_model"] = {
        "input_shape": [1, 76, 32, 1],
        "output_shape": list(r[0].shape),
        "output_name": emb.get_outputs()[0].name,
    }

    # ---- classifier (hey_jarvis) ----
    cls = ort.InferenceSession(str(here / "hey_jarvis_v0.1.onnx"))
    feats = np.zeros((1, 16, 96), dtype=np.float32)
    r = cls.run(None, {"x.1": feats})
    out["hey_jarvis"] = {
        "zero_input_score": float(r[0][0, 0]),
        "input_name": cls.get_inputs()[0].name,
        "output_name": cls.get_outputs()[0].name,
        "output_shape": list(r[0].shape),
    }

    # ---- silero_vad — confirm h/c state shapes ----
    vad = ort.InferenceSession(str(here / "silero_vad.onnx"))
    h = np.zeros((2, 1, 64), dtype=np.float32)
    c = np.zeros((2, 1, 64), dtype=np.float32)
    sr = np.array(16000, dtype=np.int64)
    for samples in (480, 512, 1536):
        try:
            audio = rng.standard_normal((1, samples)).astype(np.float32) * 0.05
            r = vad.run(None, {"input": audio, "sr": sr, "h": h, "c": c})
            out.setdefault("silero_vad", []).append(
                {
                    "input_samples": samples,
                    "output_shape": list(r[0].shape),
                    "score": float(r[0][0, 0]),
                    "hn_shape": list(r[1].shape),
                    "cn_shape": list(r[2].shape),
                }
            )
        except Exception as e:
            out.setdefault("silero_vad", []).append({"input_samples": samples, "error": str(e)})

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
