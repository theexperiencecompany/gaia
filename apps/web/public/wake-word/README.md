# Wake-word ONNX models

These files are loaded by the browser at runtime to detect the "Hey GAIA" wake
word locally.

| File | Purpose | Source |
|---|---|---|
| `melspectrogram.onnx` | Audio → mel features | openWakeWord v0.5.1 |
| `embedding_model.onnx` | Mel → 96-dim speech embedding | openWakeWord v0.5.1 |
| `silero_vad.onnx` | Voice activity detection (pre-gate) | openWakeWord v0.5.1 |
| `hey_gaia.onnx` | Custom "Hey GAIA" classifier head | Trained from `libs/wake-word/training/configs/hey_gaia.yaml` |

The current `hey_gaia.onnx` is a temporary placeholder using the `hey_mycroft_v0.1`
classifier so end-to-end integration works during development. Replace it with
the output of `libs/wake-word/training/src/train.py` before shipping.

Models are licensed under Apache-2.0 (openWakeWord). The custom-trained
`hey_gaia.onnx` is owned by GAIA.
