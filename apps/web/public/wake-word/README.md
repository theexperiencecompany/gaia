# Wake-word ONNX models

These files are loaded by the browser at runtime to detect the "Hey GAIA" wake
word locally.

| File | Purpose | Source |
|---|---|---|
| `melspectrogram.onnx` | Audio → mel features | openWakeWord v0.5.1 |
| `embedding_model.onnx` | Mel → 96-dim speech embedding | openWakeWord v0.5.1 |
| `silero_vad.onnx` | Voice activity detection (pre-gate) | openWakeWord v0.5.1 |
| `hey_gaia.onnx` | Custom "Hey GAIA" classifier head | Trained from `libs/wake-word/training/configs/hey_gaia.yaml` |

`hey_gaia.onnx` is the custom-trained classifier produced by
`libs/wake-word/training/src/train.py`. Training metrics for the shipped model
live alongside it in `libs/wake-word/models/hey_gaia.meta.json`; re-run the
training pipeline and copy both files here to replace it.

Models are licensed under Apache-2.0 (openWakeWord). The custom-trained
`hey_gaia.onnx` is owned by GAIA.
