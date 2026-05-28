"""Inspect ONNX model signatures so we can validate the TS pipeline against reality."""

import json
from pathlib import Path
import sys

import onnx
import onnxruntime as ort


def describe(model_path: Path) -> dict:
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    return {
        "size_bytes": model_path.stat().st_size,
        "ir_version": onnx.load(str(model_path)).ir_version,
        "inputs": [{"name": i.name, "shape": i.shape, "type": i.type} for i in sess.get_inputs()],
        "outputs": [{"name": o.name, "shape": o.shape, "type": o.type} for o in sess.get_outputs()],
    }


def main() -> None:
    here = Path(__file__).parent
    out = {}
    for name in ("melspectrogram", "embedding_model", "hey_jarvis_v0.1", "silero_vad"):
        path = here / f"{name}.onnx"
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            continue
        out[name] = describe(path)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
