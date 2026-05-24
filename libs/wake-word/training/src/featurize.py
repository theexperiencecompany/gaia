"""Pre-compute openWakeWord features (16x96 embedding windows) for every clip.

The melspectrogram and embedding ONNX models are frozen; we only train the
classifier head. Running them once per clip and caching the resulting feature
windows means training iteration is fast.

Each input WAV is converted to a (variable-length) sequence of 96-dim
embeddings via sliding-window inference, then turned into one or more
classifier-input windows of shape (16, 96).

Run:
    uv run python -m src.featurize --data data/synthetic --models ../models

Output:
    data/synthetic/features/positive.npz
    data/synthetic/features/hard_negative.npz
    data/synthetic/features/random_negative.npz
"""

from __future__ import annotations

import argparse
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
from tqdm import tqdm

TARGET_SR = 16_000
FRAME_SAMPLES = 1280  # 80 ms @ 16 kHz
MELSPEC_WINDOW = 480
MEL_FRAMES_PER_CHUNK = 76
EMBED_DIM = 96
CLASSIFIER_WINDOW = 16
MEL_FEATURE_DIM = 32


class Featurizer:
    """Streaming featurizer that mirrors the TS pipeline byte-for-byte.

    For each 1280-sample audio frame:
      1. melspec on [context(480) || frame(1280)] = 1760 samples → 8 new mel frames
      2. once mel buffer has ≥76 frames → embedding model → one 96-dim vector
      3. embedding goes into a ring of size 16 → classifier-ready window
    """

    def __init__(self, mel_path: Path, emb_path: Path) -> None:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1  # parent code parallelizes across clips
        opts.inter_op_num_threads = 1
        # CoreML EP adds threading overhead for these small models — empirically
        # plain CPU with one ORT thread per worker is fastest on M4 Pro.
        providers = ["CPUExecutionProvider"]
        self.mel = ort.InferenceSession(str(mel_path), opts, providers=providers)
        self.emb = ort.InferenceSession(str(emb_path), opts, providers=providers)

    def embeddings_for(self, audio: np.ndarray) -> np.ndarray:
        """Return a (N, 96) array of per-step embeddings for the clip."""
        if audio.size == 0:
            return np.empty((0, EMBED_DIM), dtype=np.float32)

        # Pad to a whole multiple of FRAME_SAMPLES so the streaming loop
        # exactly consumes the clip (no straggler partial frame).
        pad = (FRAME_SAMPLES - (len(audio) % FRAME_SAMPLES)) % FRAME_SAMPLES
        if pad:
            audio = np.concatenate([audio, np.zeros(pad, dtype=np.float32)])

        # Pre-allocate buffers (mirrors TS code).
        audio_context = np.zeros(MELSPEC_WINDOW, dtype=np.float32)
        mel_buffer = np.zeros(MEL_FRAMES_PER_CHUNK * MEL_FEATURE_DIM, dtype=np.float32)
        mel_held = 0
        embeddings: list[np.ndarray] = []

        n_frames = len(audio) // FRAME_SAMPLES
        for i in range(n_frames):
            frame = audio[i * FRAME_SAMPLES : (i + 1) * FRAME_SAMPLES]
            mel_input = np.concatenate([audio_context, frame])[None, :].astype(np.float32)
            mel_out = self.mel.run(None, {"input": mel_input})[0]
            # Shape: (1, 1, 8, 32). Flatten to (8*32,)
            mel_flat = mel_out.reshape(-1).astype(np.float32)
            mel_flat = mel_flat / 10.0 + 2.0  # openWakeWord calibration

            # Append into ring (sliding window of MEL_FRAMES_PER_CHUNK * 32 floats)
            incoming = mel_flat.size
            held_samples = mel_held * MEL_FEATURE_DIM
            cap = mel_buffer.size
            if held_samples + incoming <= cap:
                mel_buffer[held_samples : held_samples + incoming] = mel_flat
                mel_held += incoming // MEL_FEATURE_DIM
            else:
                shift = held_samples + incoming - cap
                mel_buffer[: held_samples - shift] = mel_buffer[shift:held_samples]
                mel_buffer[held_samples - shift :] = mel_flat
                mel_held = MEL_FRAMES_PER_CHUNK

            # Save context for next frame (last 480 of the current frame)
            audio_context = frame[FRAME_SAMPLES - MELSPEC_WINDOW :]

            if mel_held >= MEL_FRAMES_PER_CHUNK:
                emb_input = mel_buffer.reshape(1, MEL_FRAMES_PER_CHUNK, MEL_FEATURE_DIM, 1)
                emb_out = self.emb.run(None, {"input_1": emb_input})[0]
                embeddings.append(emb_out.reshape(-1)[:EMBED_DIM].astype(np.float32))

        return np.stack(embeddings) if embeddings else np.empty((0, EMBED_DIM), dtype=np.float32)


def make_windows(embeddings: np.ndarray, mode: str) -> np.ndarray:
    """Convert a (N, 96) embedding sequence into classifier windows (M, 16, 96).

    mode="last_only"  -> a single window ending at the final embedding
                         (used for positives — captures the full wake word)
    mode="sliding"    -> overlapping windows with stride 4 (used for negatives)
    """
    n = embeddings.shape[0]
    if n < CLASSIFIER_WINDOW:
        return np.empty((0, CLASSIFIER_WINDOW, EMBED_DIM), dtype=np.float32)

    if mode == "last_only":
        return embeddings[None, -CLASSIFIER_WINDOW:, :].astype(np.float32)

    # Sliding window with stride 4 — captures the negative across the whole clip.
    starts = list(range(0, n - CLASSIFIER_WINDOW + 1, 4))
    return np.stack([embeddings[s : s + CLASSIFIER_WINDOW] for s in starts]).astype(np.float32)


def _read_wav(path: Path) -> np.ndarray:
    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        import librosa

        audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)
    return audio.astype(np.float32)


def _stack_windows(windows: list[np.ndarray]) -> np.ndarray:
    if not windows:
        return np.empty((0, CLASSIFIER_WINDOW, EMBED_DIM), dtype=np.float32)
    return np.concatenate(windows, axis=0)


def _featurize_serial(
    featurizer: Featurizer,
    files: list[Path],
    mode: str,
    desc: str,
) -> np.ndarray:
    windows: list[np.ndarray] = []
    for path in tqdm(files, desc=desc):
        try:
            audio = _read_wav(path)
            embeddings = featurizer.embeddings_for(audio)
            ws = make_windows(embeddings, mode=mode)
            if ws.size:
                windows.append(ws)
        except Exception as exc:
            print(f"  ! {path.name}: {exc}")
    return _stack_windows(windows)


def _featurize_parallel(
    models_dir: Path,
    files: list[Path],
    mode: str,
    workers: int,
    desc: str,
) -> np.ndarray:
    # Thread-local featurizer per worker: ORT InferenceSession.run is NOT safe
    # to call concurrently from multiple threads.
    local = threading.local()

    def get_featurizer() -> Featurizer:
        f = getattr(local, "f", None)
        if f is None:
            f = Featurizer(
                models_dir / "melspectrogram.onnx",
                models_dir / "embedding_model.onnx",
            )
            local.f = f
        return f

    def work(path: Path) -> np.ndarray | None:
        try:
            audio = _read_wav(path)
            embeddings = get_featurizer().embeddings_for(audio)
            ws = make_windows(embeddings, mode=mode)
            return ws if ws.size else None
        except Exception as exc:
            print(f"  ! {path.name}: {exc}")
            return None

    windows: list[np.ndarray] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ws in tqdm(pool.map(work, files), total=len(files), desc=desc):
            if ws is not None:
                windows.append(ws)
    return _stack_windows(windows)


def featurize_directory(
    featurizer: Featurizer | None,
    directory: Path,
    mode: str,
    models_dir: Path | None = None,
    workers: int = 1,
) -> np.ndarray:
    """Featurize a directory of WAVs, optionally in parallel.

    ORT InferenceSession.run is NOT safe to call concurrently from multiple
    threads — each worker gets its own thread-local Featurizer. Pass
    `models_dir` + `workers>1` to enable parallel mode.
    """
    files = sorted(directory.glob("*.wav"))
    if not files:
        return np.empty((0, CLASSIFIER_WINDOW, EMBED_DIM), dtype=np.float32)

    desc = f"feat {directory.name}"
    if models_dir is None or workers <= 1:
        assert featurizer is not None
        return _featurize_serial(featurizer, files, mode, desc)

    return _featurize_parallel(models_dir, files, mode, workers, desc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--models", type=Path, default=Path("../models"))
    parser.add_argument("--out", type=Path, default=Path("data/features"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    f = Featurizer(
        mel_path=args.models / "melspectrogram.onnx",
        emb_path=args.models / "embedding_model.onnx",
    )

    plan = [
        ("positive", "last_only"),
        ("hard_negative", "sliding"),
        ("random_negative", "sliding"),
        ("real_negative", "sliding"),
    ]
    for kind, mode in plan:
        directory = args.data / kind
        if not directory.exists():
            print(f"  skip {kind}: no directory")
            continue
        windows = featurize_directory(
            f,
            directory,
            mode=mode,
            models_dir=args.models if args.workers > 1 else None,
            workers=args.workers,
        )
        out_path = args.out / f"{kind}.npy"
        np.save(out_path, windows)
        print(f"  {kind}: {windows.shape} → {out_path}")


if __name__ == "__main__":
    main()
