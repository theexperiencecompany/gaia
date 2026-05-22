# Hey GAIA wake-word training

This directory trains a custom **"Hey GAIA"** classifier head for the
openWakeWord pipeline. The head is a tiny model (~200 KB ONNX) that consumes
the frozen Google speech-embedding output and emits a wake probability.

## Quick start

```bash
# 1. Install deps (uses uv, mise will run this)
uv sync

# 2. Generate synthetic training audio (~75k clips, ~1 hour on a laptop)
uv run python -m src.synthesize \
    --phrases configs/hey_gaia.yaml \
    --output data/synthetic \
    --n_positive 50000 \
    --n_hard_negative 25000

# 3. (optional) Download MUSAN noise + RIR datasets
bash scripts/download_audio_corpora.sh data/

# 4. Train. ~1 hour on a single GPU, ~6 hours on CPU
uv run python -m src.train \
    --config configs/hey_gaia.yaml \
    --data data/synthetic \
    --models ../models
```

Output: `../models/hey_gaia.onnx` (drops into the TS library).

## Why this works

openWakeWord's design separates the **shared frozen feature extractor**
(melspec + speech embedding, ~2 MB combined) from a **tiny per-wake-word head**.
Training only the head means:

- 50× less data than training end-to-end
- 100× less compute
- Zero risk of forgetting (the shared backbone is frozen)
- Tiny artifact (200 KB) that ships with the app

## False-positive killers

The config emphasizes **hard negatives** — phonetic neighbours like "hey gaby",
"hey gaza", "gaia" alone, "hey google", etc. These get 3× the loss weight of
random negatives. The model learns the boundary, not just "speech that sounds
like the positives."

## Eval gates

`configs/hey_gaia.yaml` declares minimum recall and maximum FP rates per
evaluation corpus (LibriSpeech, MUSAN). Training refuses to export a model
that regresses on these metrics.

## See also

- [`../README.md`](../README.md) — high-level wake-word lib
- [openWakeWord training tutorial](https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb)
- [LiveKit wake-word](https://github.com/livekit/livekit-wakeword) — drop-in
  replacement with better FP characteristics once their JS runtime ships
