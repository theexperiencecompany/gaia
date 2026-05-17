"""Generate synthetic positive + hard-negative samples for the Hey GAIA model.

Uses Piper TTS to render each phrase in many voices, then applies augmentation
(speed, pitch, gain, additive noise, RIR convolution, leading/trailing silence)
so the model sees realistic variation rather than studio-clean TTS.

Run as a module:
    uv run python -m src.synthesize \
        --phrases configs/hey_gaia.yaml \
        --output data/synthetic \
        --n_positive 50000 \
        --n_hard_negative 25000
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml
from scipy.signal import fftconvolve
from tqdm import tqdm


@dataclass(frozen=True)
class Augmentation:
    speed: float
    pitch_semitones: float
    gain_db: float
    snr_db: float
    use_rir: bool
    pre_silence_ms: int
    post_silence_ms: int


def _random_augment(cfg: dict, rng: random.Random) -> Augmentation:
    return Augmentation(
        speed=rng.uniform(*cfg["speed_jitter"]),
        pitch_semitones=rng.uniform(*cfg["pitch_jitter_semitones"]),
        gain_db=rng.uniform(*cfg["gain_db"]),
        snr_db=rng.uniform(*cfg["noise_snr_db"]),
        use_rir=rng.random() < cfg["rir_probability"],
        pre_silence_ms=rng.randint(*cfg["pre_silence_ms"]),
        post_silence_ms=rng.randint(*cfg["post_silence_ms"]),
    )


def _piper_render(phrase: str, voice: str, out_path: Path, sample_rate: int = 16_000) -> None:
    """Render `phrase` with `voice` to a 16 kHz mono WAV at `out_path`."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "piper",
            "--model",
            voice,
            "--output_file",
            str(out_path),
            "--sample_rate",
            str(sample_rate),
        ],
        input=phrase.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"piper failed for voice={voice} phrase={phrase!r}: {proc.stderr.decode('utf-8', 'ignore')}"
        )


def _apply_speed(samples: np.ndarray, speed: float, sr: int) -> np.ndarray:
    if abs(speed - 1.0) < 1e-3:
        return samples
    new_len = int(round(len(samples) / speed))
    idx = np.linspace(0, len(samples) - 1, new_len)
    return np.interp(idx, np.arange(len(samples)), samples).astype(np.float32)


def _apply_pitch(samples: np.ndarray, semitones: float, sr: int) -> np.ndarray:
    if abs(semitones) < 1e-3:
        return samples
    import librosa

    return librosa.effects.pitch_shift(samples, sr=sr, n_steps=semitones)


def _apply_gain(samples: np.ndarray, gain_db: float) -> np.ndarray:
    factor = 10.0 ** (gain_db / 20.0)
    return np.clip(samples * factor, -1.0, 1.0)


def _apply_noise(samples: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    if noise is None or len(noise) == 0:
        return samples
    if len(noise) < len(samples):
        repeats = int(np.ceil(len(samples) / len(noise)))
        noise = np.tile(noise, repeats)
    noise = noise[: len(samples)]
    signal_power = np.mean(samples**2) + 1e-10
    noise_power = np.mean(noise**2) + 1e-10
    target_noise_power = signal_power / (10.0 ** (snr_db / 10.0))
    noise = noise * np.sqrt(target_noise_power / noise_power)
    return np.clip(samples + noise, -1.0, 1.0).astype(np.float32)


def _apply_rir(samples: np.ndarray, rir: np.ndarray) -> np.ndarray:
    if rir is None or len(rir) == 0:
        return samples
    convolved = fftconvolve(samples, rir, mode="full")[: len(samples)]
    peak = np.max(np.abs(convolved)) + 1e-10
    return (convolved / peak * np.max(np.abs(samples))).astype(np.float32)


def _pad_silence(samples: np.ndarray, pre_ms: int, post_ms: int, sr: int) -> np.ndarray:
    pre = np.zeros(int(pre_ms * sr / 1000), dtype=np.float32)
    post = np.zeros(int(post_ms * sr / 1000), dtype=np.float32)
    return np.concatenate([pre, samples, post])


def synthesize_sample(
    phrase: str,
    voice: str,
    aug: Augmentation,
    noise: np.ndarray | None,
    rir: np.ndarray | None,
    out_path: Path,
    sr: int = 16_000,
) -> None:
    tmp = out_path.with_suffix(".tmp.wav")
    _piper_render(phrase, voice, tmp, sr)
    samples, file_sr = sf.read(tmp, dtype="float32")
    tmp.unlink(missing_ok=True)
    if file_sr != sr:
        import librosa

        samples = librosa.resample(samples, orig_sr=file_sr, target_sr=sr)
    samples = _apply_speed(samples, aug.speed, sr)
    samples = _apply_pitch(samples, aug.pitch_semitones, sr)
    samples = _apply_gain(samples, aug.gain_db)
    if noise is not None:
        samples = _apply_noise(samples, noise, aug.snr_db)
    if aug.use_rir and rir is not None:
        samples = _apply_rir(samples, rir)
    samples = _pad_silence(samples, aug.pre_silence_ms, aug.post_silence_ms, sr)
    sf.write(out_path, samples, sr, subtype="PCM_16")


def synthesize_batch(
    phrases: list[str],
    voices: list[str],
    output_dir: Path,
    n_samples: int,
    aug_cfg: dict,
    noise_paths: list[Path],
    rir_paths: list[Path],
    seed: int,
    label: str,
) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    noise_pool = [_load_audio(p) for p in noise_paths] if noise_paths else []
    rir_pool = [_load_audio(p) for p in rir_paths] if rir_paths else []
    manifest = []
    with ProcessPoolExecutor() as pool:
        futures = []
        for i in range(n_samples):
            phrase = rng.choice(phrases)
            voice = rng.choice(voices)
            aug = _random_augment(aug_cfg, rng)
            noise = rng.choice(noise_pool) if noise_pool else None
            rir = rng.choice(rir_pool) if rir_pool else None
            out_path = output_dir / f"{label}_{i:06d}.wav"
            futures.append(pool.submit(synthesize_sample, phrase, voice, aug, noise, rir, out_path))
            manifest.append({"path": str(out_path.name), "phrase": phrase, "voice": voice})
        for fut in tqdm(as_completed(futures), total=len(futures), desc=label):
            fut.result()
    (output_dir / "manifest.jsonl").write_text(
        "\n".join(json.dumps(m) for m in manifest), encoding="utf-8"
    )


def _load_audio(path: Path, sr: int = 16_000) -> np.ndarray:
    samples, file_sr = sf.read(path, dtype="float32")
    if file_sr != sr:
        import librosa

        samples = librosa.resample(samples, orig_sr=file_sr, target_sr=sr)
    return samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phrases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--n_positive", type=int, default=50_000)
    parser.add_argument("--n_hard_negative", type=int, default=25_000)
    parser.add_argument("--noise_dir", type=Path, default=None)
    parser.add_argument("--rir_dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cfg = yaml.safe_load(args.phrases.read_text())
    noise_paths = sorted(args.noise_dir.glob("*.wav")) if args.noise_dir else []
    rir_paths = sorted(args.rir_dir.glob("*.wav")) if args.rir_dir else []

    synthesize_batch(
        phrases=cfg["target_phrase"],
        voices=cfg["piper_voices"],
        output_dir=args.output / "positive",
        n_samples=args.n_positive,
        aug_cfg=cfg["augmentation"],
        noise_paths=noise_paths,
        rir_paths=rir_paths,
        seed=args.seed,
        label="pos",
    )
    synthesize_batch(
        phrases=cfg["hard_negative_phrases"],
        voices=cfg["piper_voices"],
        output_dir=args.output / "hard_negative",
        n_samples=args.n_hard_negative,
        aug_cfg=cfg["augmentation"],
        noise_paths=noise_paths,
        rir_paths=rir_paths,
        seed=args.seed + 1,
        label="hn",
    )


if __name__ == "__main__":
    main()
