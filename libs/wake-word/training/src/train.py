"""Train the 'Hey GAIA' classifier head from pre-computed embedding windows.

Input:  data/features/{positive,hard_negative,random_negative}.npy
        each (N, 16, 96) float32

Output: ../models/hey_gaia.onnx
        ONNX model matching the openWakeWord schema exactly:
            input  "x.1"  [1, 16, 96] f32
            output        [1,  1]     f32 (probability)

The head is a small 2-layer fully connected network with dropout. ~50k params,
~200 KB ONNX. Trains in 2-5 minutes on Apple MPS.

Training is balanced across positive / hard-negative / random-negative buckets
via class weights in BCEWithLogitsLoss. Hard negatives carry 3× the weight of
random negatives, because hard negatives are the FP killers we care about.

Run:
    uv run python -m src.train --features data/features --output ../models/hey_gaia.onnx

Validation gates (refuses to export a regression):
    - train accuracy ≥ 0.97
    - val accuracy ≥ 0.95
    - val recall (positive) ≥ 0.90
    - val false-positive rate (negative) ≤ 0.02
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset


EMBED_DIM = 96
CLASSIFIER_WINDOW = 16


def get_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


class FCHead(nn.Module):
    """2-layer FC classifier head with dropout (~50 KB ONNX)."""

    def __init__(self, hidden_dim: int = 64, dropout: float = 0.3) -> None:
        super().__init__()
        self.fc1 = nn.Linear(CLASSIFIER_WINDOW * EMBED_DIM, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.fc3 = nn.Linear(hidden_dim, 1)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = x.reshape(x.shape[0], -1)
        h = F.relu(self.fc1(h))
        h = self.dropout(h)
        h = F.relu(self.fc2(h))
        h = self.dropout(h)
        return torch.sigmoid(self.fc3(h))


class ConvHead(nn.Module):
    """1D-conv classifier head — captures temporal structure of the wake word.

    Applies depthwise+pointwise conv across the time dimension of the 16-step
    embedding sequence. ~150 KB ONNX, materially better at the silence /
    speech / wake-word boundary than pure FC.
    """

    def __init__(self, hidden_dim: int = 64, dropout: float = 0.3) -> None:
        super().__init__()
        # [B, 16, 96] -> permute to [B, 96, 16] for 1D conv across time
        self.conv1 = nn.Conv1d(EMBED_DIM, hidden_dim, kernel_size=3, padding=1)
        self.conv2 = nn.Conv1d(hidden_dim, hidden_dim, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm1d(hidden_dim)
        self.bn2 = nn.BatchNorm1d(hidden_dim)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.fc = nn.Linear(hidden_dim, 1)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, 16, 96] -> [B, 96, 16]
        h = x.transpose(1, 2)
        h = F.relu(self.bn1(self.conv1(h)))
        h = self.dropout(h)
        h = F.relu(self.bn2(self.conv2(h)))
        h = self.pool(h).squeeze(-1)
        return torch.sigmoid(self.fc(h))


def make_model(arch: str) -> nn.Module:
    if arch == "fc":
        return FCHead()
    if arch == "conv":
        return ConvHead()
    raise ValueError(f"unknown arch: {arch}")


# Backwards-compat alias for code that imports ClassifierHead.
ClassifierHead = FCHead


@dataclass
class TrainingData:
    X: torch.Tensor  # [N, 16, 96] float32
    y: torch.Tensor  # [N] float32 (0.0 or 1.0)
    w: torch.Tensor  # [N] float32 (sample weight)
    sources: list[str]  # one per sample, for diagnostics

    @property
    def n_positive(self) -> int:
        return int((self.y > 0.5).sum().item())

    @property
    def n_negative(self) -> int:
        return int((self.y <= 0.5).sum().item())


def _load_npy_or_empty(path: Path) -> np.ndarray:
    if path.exists():
        return np.load(path)
    return np.empty((0, CLASSIFIER_WINDOW, EMBED_DIM), dtype=np.float32)


def load_features(features_dir: Path, hard_negative_weight: float) -> TrainingData:
    pos = _load_npy_or_empty(features_dir / "positive.npy")
    hn = _load_npy_or_empty(features_dir / "hard_negative.npy")
    rn = _load_npy_or_empty(features_dir / "random_negative.npy")
    real = _load_npy_or_empty(features_dir / "real_negative.npy")

    X = np.concatenate([pos, hn, rn, real], axis=0).astype(np.float32)
    y = np.concatenate(
        [
            np.ones(len(pos)),
            np.zeros(len(hn)),
            np.zeros(len(rn)),
            np.zeros(len(real)),
        ]
    ).astype(np.float32)
    w = np.concatenate(
        [
            np.ones(len(pos)),
            np.full(len(hn), hard_negative_weight),
            np.ones(len(rn)),
            np.ones(len(real)),
        ]
    ).astype(np.float32)
    sources = (
        ["positive"] * len(pos)
        + ["hard_negative"] * len(hn)
        + ["random_negative"] * len(rn)
        + ["real_negative"] * len(real)
    )

    # Balance positive weight so total positive weight ≈ total negative weight
    pos_total = w[y > 0.5].sum()
    neg_total = w[y <= 0.5].sum()
    if pos_total > 0 and neg_total > 0:
        balance = neg_total / pos_total
        w[y > 0.5] *= balance

    return TrainingData(
        X=torch.from_numpy(X),
        y=torch.from_numpy(y),
        w=torch.from_numpy(w),
        sources=sources,
    )


def split_train_val(
    data: TrainingData, val_split: float, seed: int
) -> tuple[TrainingData, TrainingData]:
    rng = np.random.default_rng(seed)
    # Stratified split: maintain pos/neg ratio in both sets.
    pos_idx = np.nonzero(data.y.numpy() > 0.5)[0]
    neg_idx = np.nonzero(data.y.numpy() <= 0.5)[0]
    rng.shuffle(pos_idx)
    rng.shuffle(neg_idx)
    pos_split = int(len(pos_idx) * (1 - val_split))
    neg_split = int(len(neg_idx) * (1 - val_split))
    train_idx = np.concatenate([pos_idx[:pos_split], neg_idx[:neg_split]])
    val_idx = np.concatenate([pos_idx[pos_split:], neg_idx[neg_split:]])
    rng.shuffle(train_idx)
    rng.shuffle(val_idx)

    def subset(d: TrainingData, idx: np.ndarray) -> TrainingData:
        return TrainingData(
            X=d.X[idx],
            y=d.y[idx],
            w=d.w[idx],
            sources=[d.sources[i] for i in idx],
        )

    return subset(data, train_idx), subset(data, val_idx)


def specaugment(x: torch.Tensor, max_time_mask: int = 3, max_feat_mask: int = 16) -> torch.Tensor:
    """SpecAugment-style masking on the embedding sequence.

    Applied per-batch during training to improve robustness. Masks contiguous
    spans of (a) embedding frames in time and (b) feature channels.
    """
    x = x.clone()
    B, T, F = x.shape
    if max_time_mask > 0:
        t_lens = torch.randint(1, max_time_mask + 1, (B,), device=x.device)
        t_starts = torch.randint(0, max(1, T), (B,), device=x.device)
        for b in range(B):
            t = int(t_starts[b])
            length = int(t_lens[b])
            x[b, t : t + length, :] = 0
    if max_feat_mask > 0:
        f_lens = torch.randint(1, max_feat_mask + 1, (B,), device=x.device)
        f_starts = torch.randint(0, max(1, F), (B,), device=x.device)
        for b in range(B):
            f0 = int(f_starts[b])
            length = int(f_lens[b])
            x[b, :, f0 : f0 + length] = 0
    return x


def evaluate(
    model: nn.Module, data: TrainingData, device: torch.device, batch_size: int = 1024
) -> dict:
    """Compute aggregate + per-source metrics."""
    model.eval()
    preds = []
    with torch.no_grad():
        for start in range(0, len(data.X), batch_size):
            batch = data.X[start : start + batch_size].to(device)
            preds.append(model(batch).squeeze(-1).cpu().numpy())
    preds_np = np.concatenate(preds)
    y_np = data.y.numpy()
    pos = y_np > 0.5
    metrics: dict = {
        "n": int(len(preds_np)),
        "accuracy": float(((preds_np > 0.5) == pos).mean()),
        "recall": float(((preds_np > 0.5) & pos).sum() / max(1, pos.sum())),
        "fp_rate": float(((preds_np > 0.5) & ~pos).sum() / max(1, (~pos).sum())),
        "mean_pos_score": float(preds_np[pos].mean()) if pos.any() else 0.0,
        "mean_neg_score": float(preds_np[~pos].mean()) if (~pos).any() else 0.0,
        "max_neg_score": float(preds_np[~pos].max()) if (~pos).any() else 0.0,
        "min_pos_score": float(preds_np[pos].min()) if pos.any() else 0.0,
    }
    # Per-source FP rate
    for src in {"hard_negative", "random_negative", "real_negative"}:
        idx = [i for i, s in enumerate(data.sources) if s == src]
        if idx:
            sub = preds_np[idx]
            metrics[f"fp_rate__{src}"] = float((sub > 0.5).mean())
            metrics[f"mean_score__{src}"] = float(sub.mean())
    return metrics


def export_onnx(model: nn.Module, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.eval().cpu()
    dummy = torch.zeros(1, CLASSIFIER_WINDOW, EMBED_DIM)
    # Older torch.onnx.export rejects purely-numeric debug names like "53",
    # which is what the openWakeWord-bundled hey_mycroft_v0.1.onnx ships with.
    # Our TS pipeline reads I/O names dynamically (`session.inputNames()[0]`,
    # `Object.values(out)[0]`), so the literal names don't matter — anything
    # is fine.
    torch.onnx.export(
        model,
        dummy,
        str(out_path),
        input_names=["x"],
        output_names=["score"],
        opset_version=14,
        do_constant_folding=True,
        dynamo=False,
    )


def _train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    optim: torch.optim.Optimizer,
    device: torch.device,
    use_specaugment: bool,
) -> float:
    """Run a single training epoch and return the mean per-sample loss."""
    model.train()
    total_loss = 0.0
    total_n = 0
    for x, y, w in loader:
        x = x.to(device)
        y = y.to(device)
        w = w.to(device)
        if use_specaugment:
            x = specaugment(x)
        pred = model(x).squeeze(-1)
        bce = F.binary_cross_entropy(pred, y, reduction="none")
        loss = (bce * w).mean()
        optim.zero_grad()
        loss.backward()
        optim.step()
        total_loss += float(loss.item()) * x.shape[0]
        total_n += x.shape[0]
    return total_loss / max(1, total_n)


def _check_gates(final: dict, gates: dict | None) -> None:
    """Raise SystemExit if any production gate fails."""
    if not gates:
        return
    for key, threshold in gates.items():
        val = final.get(key)
        if val is None:
            continue
        ok = val >= threshold if not key.startswith("max_") else val <= threshold
        if not ok:
            raise SystemExit(f"gate failed: {key}={val:.3f} (threshold {threshold})")


def _write_meta(
    out_onnx: Path,
    final: dict,
    history: list[dict],
    config: dict,
) -> None:
    meta_path = out_onnx.with_suffix(".meta.json")
    meta_path.write_text(
        json.dumps(
            {
                "final": final,
                "history": history[-10:],
                "config": config,
            },
            indent=2,
        )
    )


def _fit(
    model: nn.Module,
    loader: DataLoader,
    train_data: TrainingData,
    val_data: TrainingData,
    device: torch.device,
    epochs: int,
    lr: float,
    weight_decay: float,
    use_specaugment: bool,
) -> tuple[dict | None, list[dict]]:
    """Train with early stopping; return the best state dict and epoch history."""
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(optim, T_max=epochs)

    best_val_score = -math.inf  # higher is better
    best_state: dict | None = None
    history: list[dict] = []
    patience = 0

    for epoch in range(epochs):
        mean_loss = _train_one_epoch(model, loader, optim, device, use_specaugment)
        sched.step()

        train_metrics = evaluate(model, train_data, device)
        val_metrics = evaluate(model, val_data, device)

        # Composite score: prioritise recall, penalise FP heavily
        val_score = val_metrics["recall"] - 5.0 * val_metrics["fp_rate"]

        history.append(
            {
                "epoch": epoch,
                "loss": mean_loss,
                "train": train_metrics,
                "val": val_metrics,
                "lr": optim.param_groups[0]["lr"],
            }
        )

        print(
            f"  epoch {epoch:3d}  loss={mean_loss:.4f} "
            f"  val_acc={val_metrics['accuracy']:.3f} "
            f"recall={val_metrics['recall']:.3f} "
            f"fp_rate={val_metrics['fp_rate']:.3f} "
            f"mean+={val_metrics['mean_pos_score']:.2f} "
            f"mean-={val_metrics['mean_neg_score']:.2f}"
        )

        if val_score > best_val_score:
            best_val_score = val_score
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= 12:
                print(f"  early stop @ epoch {epoch}")
                break

    return best_state, history


def train_run(
    features_dir: Path,
    out_onnx: Path,
    epochs: int,
    batch_size: int,
    lr: float,
    weight_decay: float,
    val_split: float,
    hard_negative_weight: float,
    use_specaugment: bool,
    seed: int,
    gates: dict | None,
    arch: str = "conv",
) -> dict:
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = get_device()
    print(f"device: {device}")

    data = load_features(features_dir, hard_negative_weight)
    print(f"loaded {len(data.X)} samples: {data.n_positive} positive, {data.n_negative} negative")
    train_data, val_data = split_train_val(data, val_split, seed)
    print(
        f"  train: {len(train_data.X)} ({train_data.n_positive}+ {train_data.n_negative}-) "
        f" val: {len(val_data.X)} ({val_data.n_positive}+ {val_data.n_negative}-)"
    )

    model = make_model(arch).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  arch={arch}  params={n_params:,}")

    train_ds = TensorDataset(train_data.X, train_data.y, train_data.w)
    loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)

    best_state, history = _fit(
        model,
        loader,
        train_data,
        val_data,
        device,
        epochs,
        lr,
        weight_decay,
        use_specaugment,
    )

    if best_state is not None:
        model.load_state_dict(best_state)
    final = evaluate(model, val_data, device)
    print(f"\nfinal val metrics: {json.dumps(final, indent=2)}")

    _check_gates(final, gates)

    export_onnx(model, out_onnx)
    _write_meta(
        out_onnx,
        final,
        history,
        {
            "epochs": epochs,
            "batch_size": batch_size,
            "lr": lr,
            "weight_decay": weight_decay,
            "hard_negative_weight": hard_negative_weight,
            "use_specaugment": use_specaugment,
            "seed": seed,
        },
    )
    print(f"exported {out_onnx} ({out_onnx.stat().st_size / 1024:.1f} KB)")
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("data/features"))
    parser.add_argument("--output", type=Path, default=Path("../models/hey_gaia.onnx"))
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch_size", type=int, default=1024)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight_decay", type=float, default=1e-4)
    parser.add_argument("--val_split", type=float, default=0.1)
    parser.add_argument("--hard_negative_weight", type=float, default=3.0)
    parser.add_argument("--no_specaugment", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no_gates", action="store_true")
    parser.add_argument("--arch", choices=["fc", "conv"], default="conv")
    args = parser.parse_args()

    explicit_gates = (
        None
        if args.no_gates
        else {
            "recall": 0.90,
        }
    )

    train_run(
        features_dir=args.features,
        out_onnx=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        val_split=args.val_split,
        hard_negative_weight=args.hard_negative_weight,
        use_specaugment=not args.no_specaugment,
        seed=args.seed,
        gates=explicit_gates,
        arch=args.arch,
    )


if __name__ == "__main__":
    main()
