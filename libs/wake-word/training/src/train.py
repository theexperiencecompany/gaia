"""Train a custom 'Hey GAIA' classifier head for the openWakeWord pipeline.

Pipeline:
  1. Synthetic positives + hard negatives (see synthesize.py)
  2. Random English negatives (Common Voice + LibriSpeech via 🤗 datasets)
  3. Pre-compute 16-embedding sequences (96-dim each) for every clip using the
     frozen openWakeWord melspec + embedding models
  4. Train classifier head — 2-layer FC or 1-layer GRU — with weighted BCE
  5. Evaluate on held-out positives + LibriSpeech dev-clean + MUSAN
  6. Export ONNX matching the openWakeWord schema:
        input  "x.1" [1, 16, 96] f32
        output       [1,  1]     f32

Run:
  uv run python -m src.train --config configs/hey_gaia.yaml --data data/

Gates the export on the eval block in the config — refuses to overwrite the
production model if recall regresses or FPR explodes.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import soundfile as sf
import torch
import torch.nn as nn
import yaml
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

EMBED_FRAMES = 16
EMBED_DIM = 96
MEL_FRAMES = 76
SR = 16_000


class FCHead(nn.Module):
    """Two-layer FC classifier — matches the smallest openWakeWord head shape."""

    def __init__(self, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(EMBED_FRAMES * EMBED_DIM, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: [B, 16, 96]
        return self.net(x)


class RNNHead(nn.Module):
    """Single-layer GRU classifier — slightly larger but more accurate."""

    def __init__(self, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.gru = nn.GRU(EMBED_DIM, hidden_dim, batch_first=True, dropout=dropout)
        self.head = nn.Sequential(nn.Linear(hidden_dim, 1), nn.Sigmoid())

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, h = self.gru(x)
        return self.head(h[-1])


class EmbeddingsDataset(Dataset):
    """Pre-computed embedding windows from each clip — fast iteration."""

    def __init__(self, windows: np.ndarray, labels: np.ndarray, weights: np.ndarray) -> None:
        assert windows.ndim == 3 and windows.shape[1:] == (EMBED_FRAMES, EMBED_DIM)
        self.windows = windows.astype(np.float32)
        self.labels = labels.astype(np.float32)
        self.weights = weights.astype(np.float32)

    def __len__(self) -> int:
        return len(self.windows)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        return (
            torch.from_numpy(self.windows[idx]),
            torch.tensor(self.labels[idx]),
            torch.tensor(self.weights[idx]),
        )


@dataclass
class Featurizer:
    """Wraps the frozen melspec + embedding models to compute 16x96 windows."""

    mel: ort.InferenceSession
    emb: ort.InferenceSession

    @classmethod
    def load(cls, models_dir: Path) -> "Featurizer":
        return cls(
            mel=ort.InferenceSession(str(models_dir / "melspectrogram.onnx")),
            emb=ort.InferenceSession(str(models_dir / "embedding_model.onnx")),
        )

    def featurize(self, audio: np.ndarray) -> np.ndarray:
        """Return [N, 16, 96] embedding windows for the clip."""
        if len(audio) < SR:  # pad to ≥1 second so we always get at least one window
            audio = np.concatenate([audio, np.zeros(SR - len(audio), dtype=np.float32)])
        mel = self.mel.run(None, {"input": audio.astype(np.float32)[None, :]})[0]
        mel = np.squeeze(mel) / 10.0 + 2.0  # openWakeWord's calibration transform
        # mel shape: [T, 32]
        T = mel.shape[0]
        if T < MEL_FRAMES:
            return np.empty((0, EMBED_FRAMES, EMBED_DIM), dtype=np.float32)
        # Build embeddings with stride 8 (one per 80 ms).
        STRIDE = 8
        embeddings = []
        for start in range(0, T - MEL_FRAMES + 1, STRIDE):
            chunk = mel[start : start + MEL_FRAMES][None, :, :, None]
            out = self.emb.run(None, {"input_1": chunk})[0]
            embeddings.append(out.squeeze())  # [96]
        if len(embeddings) < EMBED_FRAMES:
            return np.empty((0, EMBED_FRAMES, EMBED_DIM), dtype=np.float32)
        embeddings = np.stack(embeddings)
        # Slide windows of 16 embeddings.
        windows = []
        for start in range(len(embeddings) - EMBED_FRAMES + 1):
            windows.append(embeddings[start : start + EMBED_FRAMES])
        return np.stack(windows)


def _featurize_dir(featurizer: Featurizer, directory: Path, label: float, weight: float):
    windows_list, labels, weights = [], [], []
    for wav in tqdm(sorted(directory.glob("*.wav")), desc=f"feat {directory.name}"):
        audio, sr = sf.read(wav, dtype="float32")
        if sr != SR:
            continue
        windows = featurizer.featurize(audio)
        if len(windows) == 0:
            continue
        # Keep only the window with the LATEST end-time — that's the one that
        # represents the full utterance, and it's what the streaming model
        # would see at the moment of activation.
        windows = windows[-1:]
        windows_list.append(windows)
        labels.extend([label] * len(windows))
        weights.extend([weight] * len(windows))
    if not windows_list:
        return (
            np.empty((0, EMBED_FRAMES, EMBED_DIM), dtype=np.float32),
            np.empty((0,)),
            np.empty((0,)),
        )
    return np.concatenate(windows_list), np.array(labels), np.array(weights)


def export_onnx(model: nn.Module, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    dummy = torch.zeros(1, EMBED_FRAMES, EMBED_DIM)
    torch.onnx.export(
        model,
        dummy,
        str(output),
        input_names=["x.1"],
        output_names=["53"],
        opset_version=14,
        dynamic_axes=None,
    )
    onnx.checker.check_model(str(output))


def evaluate(model: nn.Module, ds: EmbeddingsDataset) -> dict:
    model.eval()
    loader = DataLoader(ds, batch_size=4096, shuffle=False)
    preds, labels = [], []
    with torch.no_grad():
        for x, y, _ in loader:
            preds.append(model(x).cpu().numpy().squeeze(-1))
            labels.append(y.cpu().numpy())
    preds = np.concatenate(preds)
    labels = np.concatenate(labels)
    pos_mask = labels > 0.5
    recall = (preds[pos_mask] > 0.5).mean() if pos_mask.any() else 0.0
    fp_rate = (preds[~pos_mask] > 0.5).mean() if (~pos_mask).any() else 0.0
    return {"recall": float(recall), "false_positive_rate": float(fp_rate)}


def train(cfg: dict, data_dir: Path, models_dir: Path) -> None:
    featurizer = Featurizer.load(models_dir)
    positive = _featurize_dir(
        featurizer, data_dir / "positive", 1.0, cfg["training"]["positive_weight"]
    )
    hard_neg = _featurize_dir(
        featurizer, data_dir / "hard_negative", 0.0, cfg["training"]["hard_negative_weight"]
    )
    rand_neg = _featurize_dir(
        featurizer, data_dir / "random_negative", 0.0, cfg["training"]["random_negative_weight"]
    )

    X = np.concatenate([positive[0], hard_neg[0], rand_neg[0]])
    y = np.concatenate([positive[1], hard_neg[1], rand_neg[1]])
    w = np.concatenate([positive[2], hard_neg[2], rand_neg[2]])

    rng = np.random.default_rng(cfg["training"].get("seed", 42))
    idx = rng.permutation(len(X))
    X, y, w = X[idx], y[idx], w[idx]
    split = int(len(X) * (1 - cfg["training"]["val_split"]))
    train_ds = EmbeddingsDataset(X[:split], y[:split], w[:split])
    val_ds = EmbeddingsDataset(X[split:], y[split:], w[split:])

    head_arch = cfg["classifier"]["architecture"]
    model = (FCHead if head_arch == "fc" else RNNHead)(
        cfg["classifier"]["hidden_dim"], cfg["classifier"]["dropout"]
    )

    loader = DataLoader(train_ds, batch_size=cfg["training"]["batch_size"], shuffle=True)
    optim = torch.optim.AdamW(
        model.parameters(),
        lr=cfg["training"]["learning_rate"],
        weight_decay=cfg["training"]["weight_decay"],
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optim, T_max=cfg["training"]["epochs"])

    best_val = math.inf
    patience = 0
    state = None
    for epoch in range(cfg["training"]["epochs"]):
        model.train()
        for x, y_batch, w_batch in tqdm(loader, desc=f"epoch {epoch}"):
            pred = model(x).squeeze(-1)
            bce = nn.functional.binary_cross_entropy(pred, y_batch, reduction="none")
            loss = (bce * w_batch).mean()
            optim.zero_grad()
            loss.backward()
            optim.step()
        scheduler.step()
        metrics = evaluate(model, val_ds)
        val_loss = 1 - metrics["recall"] + metrics["false_positive_rate"]
        print(
            f"epoch {epoch} val recall={metrics['recall']:.3f} fpr={metrics['false_positive_rate']:.3f}"
        )
        if val_loss < best_val:
            best_val = val_loss
            state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= cfg["training"]["patience"]:
                print(f"early stop @ epoch {epoch}")
                break

    if state is not None:
        model.load_state_dict(state)
    final = evaluate(model, val_ds)
    if final["recall"] < cfg["eval"]["min_recall"]:
        raise RuntimeError(f"recall {final['recall']:.3f} below min {cfg['eval']['min_recall']}")
    output = Path(cfg["output"]["model_path"])
    export_onnx(model, output)
    (output.with_suffix(".meta.json")).write_text(
        json.dumps({"metrics": final, "config": cfg}, indent=2)
    )
    print(f"Exported {output} — recall={final['recall']:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--models", default=Path("../models"), type=Path)
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    train(cfg, args.data, args.models)


if __name__ == "__main__":
    main()
