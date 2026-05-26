"""Download REAL human speech negatives — random English utterances from the
LibriSpeech ASR corpus (test-clean split). These are recordings of real
people reading aloud, perfect background-speech negatives that no synthetic
Piper voice can match for realism.

The model trained against only synthetic negatives is far less robust against
real speech — this corpus closes that gap.

Run:
    uv run python -m src.fetch_real_negatives --n 5000 --output data/synthetic/real_negative

Each clip is sliced to ~2-4 seconds at 16 kHz mono PCM.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from tqdm import tqdm

# Pre-baked LibriSpeech test-clean URLs. Slimmest split (~340 MB tar) but
# loading it as raw audio chunks is heavy. Easier: use the HuggingFace
# parquet shards via streaming.

HF_DATASET = "openslr/librispeech_asr"
HF_CONFIG = "clean"
HF_SPLIT = "train.100"  # train-clean-100: ~28k examples, ~100 hours, 251 speakers
# Pin the dataset revision for reproducible, tamper-evident downloads.
HF_REVISION = "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1"  # pragma: allowlist secret


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5000)
    parser.add_argument("--output", type=Path, default=Path("data/synthetic/real_negative"))
    parser.add_argument("--min_seconds", type=float, default=2.5)
    parser.add_argument("--max_seconds", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # Use HuggingFace `datasets` in streaming mode — no full download.
    from datasets import load_dataset

    print(f"streaming {HF_DATASET}/{HF_CONFIG} split={HF_SPLIT} ...")
    ds = load_dataset(
        HF_DATASET,
        HF_CONFIG,
        split=HF_SPLIT,
        revision=HF_REVISION,
        streaming=True,
        trust_remote_code=True,
    )

    saved = 0
    rng = np.random.default_rng(args.seed)
    pbar = tqdm(total=args.n, desc="real_negative")
    for ex in ds:
        if saved >= args.n:
            break
        audio = ex["audio"]
        arr = audio["array"].astype(np.float32)
        sr = audio["sampling_rate"]
        # crop to a random window of [min_seconds, max_seconds]
        target_seconds = rng.uniform(args.min_seconds, args.max_seconds)
        target_samples = int(target_seconds * sr)
        if len(arr) < target_samples:
            continue
        start = int(rng.integers(0, len(arr) - target_samples + 1))
        clip = arr[start : start + target_samples]
        # resample to 16k if needed
        if sr != 16000:
            import librosa

            clip = librosa.resample(clip, orig_sr=sr, target_sr=16000)
        sf.write(args.output / f"real_{saved:06d}.wav", clip, 16000, subtype="PCM_16")
        saved += 1
        pbar.update(1)
    pbar.close()
    print(f"saved {saved} real-speech negative clips to {args.output}")


if __name__ == "__main__":
    main()
