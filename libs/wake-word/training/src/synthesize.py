"""Generate synthetic positive + hard-negative samples for the 'Hey GAIA' model.

Uses Piper TTS (Python API, in-process, fast) to render each phrase across many
voices with random synthesis-time variation, then applies post-synthesis
augmentation (speed, pitch, gain, additive noise, RIR convolution, silence
padding) so the trained model sees realistic variation.

Run:
    uv run python -m src.synthesize \
        --voices data/voices \
        --output data/synthetic \
        --n_positive 30000 \
        --n_hard_negative 15000 \
        --n_random_negative 15000

Outputs per category:
    data/synthetic/positive/*.wav
    data/synthetic/hard_negative/*.wav
    data/synthetic/random_negative/*.wav
    data/synthetic/{category}/manifest.jsonl

All output WAVs are 16 kHz mono PCM_16, matching the openWakeWord pipeline.
"""

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from piper import PiperVoice
from piper.config import SynthesisConfig
from scipy.signal import fftconvolve
from tqdm import tqdm

TARGET_SR = 16_000

# Primary wake-word phrase — appears multiple times in POSITIVE_PHRASES so it is
# sampled more often during synthesis.
HEY_GAIA = "hey gaia"


# ---------------------------- Phrases ---------------------------------------

POSITIVE_PHRASES = [
    # Phoneme-verified — every entry resolves to /heɪ ɡaɪə/ or a small set of
    # natural variants ("hi gaia", "hey gaya" = /heɪ ɡeɪə/). Entries that
    # phonemize to wrong sounds (e.g. "gye" → /dʒaɪ/) are excluded — they
    # would teach the model the wrong target.
    HEY_GAIA,  # /heɪ ɡaɪə/ — primary
    HEY_GAIA,  # weight: appear twice as often
    HEY_GAIA,
    "hey guyah",  # /heɪ ɡaɪə/ — same sound, different orthography
    "hey, gaia",  # comma changes prosody slightly
    "hey gaia.",  # final punctuation prosody
    "hi gaia",  # /haɪ ɡaɪə/ — natural rephrasing users will say
    "hi, gaia",  # comma form
    "hey gaya",  # /heɪ ɡeɪə/ — alternate pronunciation (gay-uh)
    "okay gaia",  # /oʊkeɪ ɡaɪə/ — natural rephrasing
    "yo gaia",  # /joʊ ɡaɪə/ — casual rephrasing
]

HARD_NEGATIVE_PHRASES = [
    # Phonetic near-misses that share onset or rime with "hey gaia" — these
    # are the FP killers. The model must learn to discriminate.
    "hey google",
    "hey siri",
    "hey alexa",
    "hey jarvis",
    "hey jane",
    "hey kayla",
    "hey gaby",
    "hey gabriel",
    "hey gabby",
    "hey gala",
    "hey gaza",
    "hey gary",
    "hey gail",
    "hey kaia",  # rhymes with gaia
    "hey maya",  # rhymes
    "hey sophia",  # rhymes
    "hey aya",  # rhymes
    "hey gye",  # /dʒaɪ/ — phonemizer renders this as "J" sound, good confusable
    "hey ge a",  # /dʒiː eɪ/ — another sound-alike near-miss
    "gaia",  # the word alone — must NOT fire on it
    "gaya",
    "guy uh",
    "guyah",
    "hey there",
    "hey you",
    "hey",
    "they got ya",
    "say hi to",
    "hey, guy",
    "hey, the guy",
    "hey buddy",
    "hey friend",
    "say gaia",
    "the gaia",
    "to gaia",
    "called gaia",
    "ai called gaia",
    "named gaia",
]

# Random conversational sentences for "background English" negatives.
# Drawn from a mix of everyday speech, questions, and statements so the model
# learns that arbitrary speech is NOT a wake word.
RANDOM_NEGATIVE_TEMPLATES = [
    "i was just thinking about that yesterday",
    "what time does the meeting start tomorrow",
    "can you pick up some milk on your way home",
    "the weather has been really nice this week",
    "i'm going to grab a coffee, do you want one",
    "she said the project would be ready by friday",
    "did you watch the game last night",
    "remind me to call my mom this weekend",
    "the new restaurant on main street is amazing",
    "i'll be there in about fifteen minutes",
    "could you send me that document again",
    "we should plan a vacation this summer",
    "the kids are doing great at school",
    "i don't think i can make it to the party",
    "let me check my calendar and get back to you",
    "have you seen my keys anywhere",
    "the traffic is terrible this morning",
    "i finished the book you recommended",
    "what do you want for dinner tonight",
    "they're moving to a bigger apartment next month",
    "the dog needs to go for a walk",
    "i'll text you the address when i get there",
    "this coffee is really strong",
    "can you turn down the volume a bit",
    "i'm running a little late, sorry",
    "did you remember to lock the door",
    "the printer is out of paper again",
    "let's grab lunch together this week",
    "i need to renew my passport before the trip",
    "the new movie was actually pretty good",
    "i'll see you at the gym at seven",
    "she's been working really hard lately",
    "the package should arrive by thursday",
    "i forgot to charge my phone last night",
    "we ran out of milk this morning",
    "the meeting was longer than i expected",
    "can you proofread this for me",
    "i love this song, who's the artist",
    "tomorrow's forecast says it might rain",
    "let me know if you need any help",
    "the new coffee shop opened on the corner",
    "i'm going to bed early tonight",
    "did you finish your homework already",
    "the weekend went by way too fast",
    "i should probably get a haircut soon",
    "the cat knocked over the plant again",
    "i'm not really hungry right now",
    "we need to leave in about ten minutes",
    "i can't believe it's already december",
    "the conference is next thursday and friday",
]


# ---------------------------- Augmentation ---------------------------------


@dataclass(frozen=True)
class Augmentation:
    speed: float
    pitch_semitones: float
    gain_db: float
    noise_snr_db: float | None
    use_rir: bool
    pre_silence_ms: int
    post_silence_ms: int
    length_scale: float  # Piper synthesis-time speed factor
    noise_scale: float  # Piper synthesis-time prosody variance
    noise_w_scale: float


def random_augmentation(rng: np.random.Generator) -> Augmentation:
    return Augmentation(
        speed=float(rng.uniform(0.88, 1.12)),
        pitch_semitones=float(rng.uniform(-2.0, 2.0)),
        gain_db=float(rng.uniform(-6.0, 6.0)),
        noise_snr_db=float(rng.uniform(5.0, 25.0)) if rng.random() < 0.7 else None,
        use_rir=bool(rng.random() < 0.5),
        pre_silence_ms=int(rng.integers(0, 251)),
        post_silence_ms=int(rng.integers(0, 351)),
        # Piper synth params: vary cadence/prosody at generation time too
        length_scale=float(rng.uniform(0.85, 1.15)),
        noise_scale=float(rng.uniform(0.45, 0.85)),
        noise_w_scale=float(rng.uniform(0.6, 1.0)),
    )


# ---------------------------- Piper helpers --------------------------------


def load_voices(voices_dir: Path) -> dict[str, PiperVoice]:
    """Load every Piper voice in `voices_dir` into a dict keyed by name."""
    voices: dict[str, PiperVoice] = {}
    for onnx in sorted(voices_dir.glob("*.onnx")):
        name = onnx.stem
        try:
            voices[name] = PiperVoice.load(onnx)
        except Exception as exc:
            print(f"  skip {name}: {exc}")
    if not voices:
        raise SystemExit(f"No voices loaded from {voices_dir}")
    return voices


def piper_synthesize(
    voice: PiperVoice,
    text: str,
    aug: Augmentation,
    voice_lock: threading.Lock,
    target_sr: int = TARGET_SR,
) -> np.ndarray:
    """Render `text` with `voice` and return mono float32 audio at `target_sr`.

    PiperVoice instances are NOT thread-safe; `voice_lock` serializes concurrent
    `.synthesize()` calls against the same voice across worker threads.
    """
    cfg = SynthesisConfig(
        length_scale=aug.length_scale,
        noise_scale=aug.noise_scale,
        noise_w_scale=aug.noise_w_scale,
    )
    # `synthesize` returns an iterable of AudioChunk (raw int16 bytes + metadata).
    # Inference runs lazily during iteration, so hold the lock for the full loop.
    chunks: list[np.ndarray] = []
    src_sr = voice.config.sample_rate
    with voice_lock:
        for chunk in voice.synthesize(text, syn_config=cfg):
            # AudioChunk exposes `audio_int16_array` (numpy int16) in piper>=1.4
            arr = np.asarray(chunk.audio_int16_array, dtype=np.int16)
            chunks.append(arr.astype(np.float32) / 32768.0)
    if not chunks:
        return np.zeros(target_sr, dtype=np.float32)
    audio = np.concatenate(chunks)
    if src_sr != target_sr:
        audio = librosa.resample(audio, orig_sr=src_sr, target_sr=target_sr)
    return audio.astype(np.float32)


# ---------------------------- Post-synth augment ---------------------------


def apply_speed(audio: np.ndarray, speed: float) -> np.ndarray:
    if abs(speed - 1.0) < 1e-3:
        return audio
    new_len = max(1, int(round(len(audio) / speed)))
    idx = np.linspace(0, len(audio) - 1, new_len)
    return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


def apply_pitch(audio: np.ndarray, semitones: float, sr: int) -> np.ndarray:
    if abs(semitones) < 1e-3:
        return audio
    return librosa.effects.pitch_shift(audio, sr=sr, n_steps=semitones).astype(np.float32)


def apply_gain(audio: np.ndarray, gain_db: float) -> np.ndarray:
    factor = 10.0 ** (gain_db / 20.0)
    return np.clip(audio * factor, -1.0, 1.0).astype(np.float32)


def apply_noise(
    audio: np.ndarray, noise: np.ndarray, snr_db: float, rng: np.random.Generator
) -> np.ndarray:
    if noise is None or len(noise) == 0:
        return audio
    # tile / trim noise to match
    if len(noise) < len(audio):
        reps = int(np.ceil(len(audio) / len(noise)))
        noise = np.tile(noise, reps)[: len(audio)]
    else:
        start = int(rng.integers(0, len(noise) - len(audio) + 1))
        noise = noise[start : start + len(audio)]
    signal_power = np.mean(audio**2) + 1e-10
    noise_power = np.mean(noise**2) + 1e-10
    target = signal_power / (10.0 ** (snr_db / 10.0))
    noise = noise * np.sqrt(target / noise_power)
    return np.clip(audio + noise, -1.0, 1.0).astype(np.float32)


def apply_rir(audio: np.ndarray, rir: np.ndarray) -> np.ndarray:
    if rir is None or len(rir) == 0:
        return audio
    convolved = fftconvolve(audio, rir, mode="full")[: len(audio)]
    peak = np.max(np.abs(convolved)) + 1e-10
    return (convolved / peak * np.max(np.abs(audio))).astype(np.float32)


def pad_silence(audio: np.ndarray, pre_ms: int, post_ms: int, sr: int) -> np.ndarray:
    pre = np.zeros(int(pre_ms * sr / 1000), dtype=np.float32)
    post = np.zeros(int(post_ms * sr / 1000), dtype=np.float32)
    return np.concatenate([pre, audio, post])


# ---------------------------- Worker --------------------------------------


def synth_one(
    out_path: Path,
    voice: PiperVoice,
    voice_lock: threading.Lock,
    phrase: str,
    aug: Augmentation,
    noise: np.ndarray | None,
    rir: np.ndarray | None,
    rng: np.random.Generator,
    min_total_ms: int = 2400,
) -> tuple[str, str]:
    audio = piper_synthesize(voice, phrase, aug, voice_lock)
    audio = apply_speed(audio, aug.speed)
    audio = apply_pitch(audio, aug.pitch_semitones, TARGET_SR)
    audio = apply_gain(audio, aug.gain_db)
    if aug.noise_snr_db is not None and noise is not None:
        audio = apply_noise(audio, noise, aug.noise_snr_db, rng)
    if aug.use_rir and rir is not None:
        audio = apply_rir(audio, rir)
    audio = pad_silence(audio, aug.pre_silence_ms, aug.post_silence_ms, TARGET_SR)
    # Critical: the openWakeWord pipeline emits its FIRST classifier window
    # only after ~2.08 s of audio (10 frames to fill mel buffer + 16 to fill
    # the embedding ring). If the clip is shorter than that, featurization
    # yields zero windows. Pad with LEADING silence so the wake word lands
    # in the last embedding window of the resulting feature sequence.
    min_samples = int(min_total_ms * TARGET_SR / 1000)
    if len(audio) < min_samples:
        lead = np.zeros(min_samples - len(audio), dtype=np.float32)
        audio = np.concatenate([lead, audio])
    sf.write(out_path, audio, TARGET_SR, subtype="PCM_16")
    return phrase, out_path.name


def _load_audio_pool(directory: Path | None) -> list[np.ndarray]:
    if directory is None or not directory.exists():
        return []
    pool = []
    for path in sorted(directory.glob("*.wav")):
        try:
            samples, sr = sf.read(path, dtype="float32")
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            if sr != TARGET_SR:
                samples = librosa.resample(samples, orig_sr=sr, target_sr=TARGET_SR)
            pool.append(samples.astype(np.float32))
        except Exception as exc:
            print(f"  skip {path.name}: {exc}")
            continue
    return pool


# ---------------------------- Batch generation -----------------------------


def generate_batch(
    voices: dict[str, PiperVoice],
    phrases: list[str],
    n_samples: int,
    out_dir: Path,
    label: str,
    seed: int,
    noise_pool: list[np.ndarray],
    rir_pool: list[np.ndarray],
    max_workers: int = 8,
) -> None:
    if n_samples <= 0:
        print(f"  skip {label}: n_samples=0")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    # Independent per-task generators so worker threads stay deterministic.
    task_seeds = np.random.SeedSequence(seed).spawn(n_samples)
    voice_names = list(voices.keys())
    # PiperVoice instances are not thread-safe — one lock per voice serializes
    # concurrent .synthesize() calls against the same instance.
    voice_locks = {name: threading.Lock() for name in voice_names}
    manifest: list[dict] = []
    plan = []
    for i in range(n_samples):
        voice_name = voice_names[int(rng.integers(0, len(voice_names)))]
        phrase = phrases[int(rng.integers(0, len(phrases)))]
        aug = random_augmentation(rng)
        noise = noise_pool[int(rng.integers(0, len(noise_pool)))] if noise_pool else None
        rir = rir_pool[int(rng.integers(0, len(rir_pool)))] if rir_pool else None
        plan.append((i, voice_name, phrase, aug, noise, rir))

    # IO-bound + numpy-bound — threads are fine (Piper holds the GIL only inside
    # native ORT inference, which releases for matmul kernels).
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for i, voice_name, phrase, aug, noise, rir in plan:
            out_path = out_dir / f"{label}_{i:06d}.wav"
            task_rng = np.random.default_rng(task_seeds[i])
            fut = pool.submit(
                synth_one,
                out_path,
                voices[voice_name],
                voice_locks[voice_name],
                phrase,
                aug,
                noise,
                rir,
                task_rng,
            )
            futures[fut] = (i, voice_name, phrase, aug, out_path.name)
        for fut in tqdm(as_completed(futures), total=len(futures), desc=label):
            i, voice_name, phrase, aug, name = futures[fut]
            try:
                fut.result()
                manifest.append(
                    {
                        "i": i,
                        "file": name,
                        "voice": voice_name,
                        "phrase": phrase,
                        "aug": asdict(aug),
                    }
                )
            except Exception as exc:
                print(f"  ! {name}: {exc}")
    (out_dir / "manifest.jsonl").write_text(
        "\n".join(json.dumps(m) for m in manifest), encoding="utf-8"
    )


# ---------------------------- CLI --------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", type=Path, default=Path("data/voices"))
    parser.add_argument("--output", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--n_positive", type=int, default=30000)
    parser.add_argument("--n_hard_negative", type=int, default=15000)
    parser.add_argument("--n_random_negative", type=int, default=15000)
    parser.add_argument("--noise_dir", type=Path, default=None)
    parser.add_argument("--rir_dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    print(f"Loading voices from {args.voices} ...")
    voices = load_voices(args.voices)
    print(f"  loaded {len(voices)}: {list(voices.keys())}")

    noise_pool = _load_audio_pool(args.noise_dir)
    rir_pool = _load_audio_pool(args.rir_dir)
    print(f"  noise samples: {len(noise_pool)}  RIR samples: {len(rir_pool)}")

    generate_batch(
        voices=voices,
        phrases=POSITIVE_PHRASES,
        n_samples=args.n_positive,
        out_dir=args.output / "positive",
        label="pos",
        seed=args.seed,
        noise_pool=noise_pool,
        rir_pool=rir_pool,
        max_workers=args.workers,
    )
    generate_batch(
        voices=voices,
        phrases=HARD_NEGATIVE_PHRASES,
        n_samples=args.n_hard_negative,
        out_dir=args.output / "hard_negative",
        label="hn",
        seed=args.seed + 1,
        noise_pool=noise_pool,
        rir_pool=rir_pool,
        max_workers=args.workers,
    )
    generate_batch(
        voices=voices,
        phrases=RANDOM_NEGATIVE_TEMPLATES,
        n_samples=args.n_random_negative,
        out_dir=args.output / "random_negative",
        label="rn",
        seed=args.seed + 2,
        noise_pool=noise_pool,
        rir_pool=rir_pool,
        max_workers=args.workers,
    )


if __name__ == "__main__":
    main()
