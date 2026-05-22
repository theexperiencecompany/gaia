"""End-to-end validation of a trained hey_gaia.onnx against held-out WAVs.

Runs the full 3-stage openWakeWord pipeline (mel → embedding → classifier) on:
  - held-out synthetic positive clips
  - synthetic hard-negative clips
  - random English clips
  - the openWakeWord test fixtures (real human speech: hey_jane.wav)

Reports per-bucket metrics and a final go/no-go for production.

Run:
    uv run python -m src.validate \\
        --model ../models/hey_gaia.onnx \\
        --data data/synthetic \\
        --fixtures ../test-fixtures
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
from tqdm import tqdm

from src.featurize import Featurizer, make_windows

SR = 16_000


def score_clip(
    feat: Featurizer,
    classifier: ort.InferenceSession,
    audio: np.ndarray,
    input_name: str,
    min_total_ms: int = 2400,
) -> float:
    """Return the MAX wake-word score across every classifier window in the clip.

    Short clips (< 2.4s) get LEADING silence padding so the embedding ring fills
    and at least one classifier window is produced; mirrors synthesize.py.
    """
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)
    min_samples = int(min_total_ms * SR / 1000)
    if len(audio) < min_samples:
        pad = np.zeros(min_samples - len(audio), dtype=np.float32)
        audio = np.concatenate([pad, audio])
    embeddings = feat.embeddings_for(audio)
    windows = make_windows(embeddings, mode="sliding")
    if windows.size == 0:
        return 0.0
    scores = []
    for w in windows:
        out = classifier.run(None, {input_name: w[None, ...]})[0]
        scores.append(float(out[0, 0]))
    return max(scores) if scores else 0.0


def score_directory(
    feat: Featurizer,
    cls: ort.InferenceSession,
    input_name: str,
    directory: Path,
    sample_n: int | None,
    desc: str,
) -> list[tuple[str, float]]:
    files = sorted(directory.glob("*.wav"))
    if sample_n is not None and len(files) > sample_n:
        rng = np.random.default_rng(0)
        idx = rng.choice(len(files), size=sample_n, replace=False)
        files = [files[i] for i in idx]
    results: list[tuple[str, float]] = []
    for path in tqdm(files, desc=desc):
        try:
            audio, sr = sf.read(path, dtype="float32")
            if sr != SR:
                import librosa

                audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
            results.append((path.name, score_clip(feat, cls, audio, input_name)))
        except Exception as exc:
            print(f"  ! {path.name}: {exc}")
    return results


def summarize(name: str, scores: list[float], threshold: float = 0.5) -> dict:
    if not scores:
        return {"name": name, "n": 0}
    arr = np.array(scores)
    return {
        "name": name,
        "n": len(scores),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "p90": float(np.quantile(arr, 0.90)),
        "p99": float(np.quantile(arr, 0.99)),
        "max": float(arr.max()),
        "min": float(arr.min()),
        "fire_rate": float((arr > threshold).mean()),  # % of clips that crossed threshold
    }


def _score_buckets(
    feat: Featurizer,
    cls: ort.InferenceSession,
    input_name: str,
    data_dir: Path,
    sample_n: int | None,
) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = {}
    for kind in ("positive", "hard_negative", "random_negative", "real_negative"):
        directory = data_dir / kind
        if directory.exists():
            r = score_directory(feat, cls, input_name, directory, sample_n, kind)
            buckets[kind] = [s for _, s in r]
    return buckets


def _score_fixtures(
    feat: Featurizer,
    cls: ort.InferenceSession,
    input_name: str,
    fixtures_dir: Path,
) -> list[float]:
    scores: list[float] = []
    if not fixtures_dir.exists():
        return scores
    for path in sorted(fixtures_dir.glob("*.wav")):
        audio, sr = sf.read(path, dtype="float32")
        if sr != SR:
            import librosa

            audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
        s = score_clip(feat, cls, audio, input_name)
        scores.append(s)
        print(f"  fixture {path.name}: score={s:.3f}")
    return scores


def _check_gates(summary: dict) -> list[str]:
    """Run production gates against the summary and return failure messages."""
    fails: list[str] = []

    def check(pred: bool, message: str) -> None:
        status = "PASS" if pred else "FAIL"
        print(f"  [{status}] {message}")
        if not pred:
            fails.append(message)

    pos = summary.get("positive")
    if pos:
        check(pos["fire_rate"] >= 0.90, f"positive recall ≥0.90 (got {pos['fire_rate']:.3f})")
        check(pos["mean"] >= 0.70, f"positive mean ≥0.70 (got {pos['mean']:.3f})")
    hn = summary.get("hard_negative")
    if hn:
        check(hn["fire_rate"] <= 0.05, f"hard-negative FPR ≤0.05 (got {hn['fire_rate']:.3f})")
        check(hn["mean"] <= 0.20, f"hard-negative mean ≤0.20 (got {hn['mean']:.3f})")
    rn = summary.get("random_negative")
    if rn:
        check(rn["fire_rate"] <= 0.02, f"random-negative FPR ≤0.02 (got {rn['fire_rate']:.3f})")
    real = summary.get("real_negative")
    if real:
        check(real["fire_rate"] <= 0.02, f"real-negative FPR ≤0.02 (got {real['fire_rate']:.3f})")
    return fails


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=Path("../models/hey_gaia.onnx"))
    parser.add_argument("--models_dir", type=Path, default=Path("../models"))
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--fixtures", type=Path, default=Path("../test-fixtures"))
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--sample_n", type=int, default=500)
    args = parser.parse_args()

    print(f"Loading {args.model}...")
    cls = ort.InferenceSession(str(args.model))
    input_name = cls.get_inputs()[0].name
    feat = Featurizer(
        args.models_dir / "melspectrogram.onnx",
        args.models_dir / "embedding_model.onnx",
    )

    buckets = _score_buckets(feat, cls, input_name, args.data, args.sample_n)
    fixture_scores = _score_fixtures(feat, cls, input_name, args.fixtures)
    if fixture_scores:
        buckets["fixtures"] = fixture_scores

    summary = {k: summarize(k, scores, args.threshold) for k, scores in buckets.items()}
    print("\n" + json.dumps(summary, indent=2))

    # Production gate
    print("\n--- production gates ---")
    fails = _check_gates(summary)

    if fails:
        print(f"\n{len(fails)} gate(s) failed — model is NOT production ready.")
    else:
        print("\nAll gates PASSED — model is production ready.")

    out = args.model.with_suffix(".validation.json")
    out.write_text(json.dumps({"summary": summary, "fails": fails}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
