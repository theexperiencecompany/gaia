#!/usr/bin/env python3
"""
apps/manifesto-video/voiceover.py
Generate ElevenLabs voiceover timed to TEXT_TIMELINE, mix into final.mp4.
Output: output/final_vo.mp4

Uses George (JBFqnCBsd6RMkjVDRZzb) — British, narrative storyteller.
"""
import json
import subprocess
import sys
from pathlib import Path

PYTHON_SITE = "/home/aryan/.local/share/mise/installs/python/3.12.12/lib/python3.12/site-packages"
sys.path.insert(0, PYTHON_SITE)

from elevenlabs.client import ElevenLabs  # noqa: E402
from elevenlabs import VoiceSettings      # noqa: E402

API_KEY  = "sk_c5875771f15d8c9f068f1f51a456b0c586405d88c970aca7"
VOICE_ID = "4QLC5fepxZkYmdD2IGRU"  # Matthew Schmitz
MODEL_ID = "eleven_multilingual_v2"

ROOT   = Path(__file__).parent
VO_DIR = ROOT / "output" / "voiceover"
VO_DIR.mkdir(parents=True, exist_ok=True)

# (start_seconds, spoken_text)
# "GAIA" written as "Gaya" so TTS pronounces it as a word, not letters
LINES = [
    (0.5,  "The work that matters"),
    (3.3,  "doesn't happen in meetings."),
    (6.3,  "It happens in the hours"),
    (9.3,  "when the world goes quiet."),
    (18.3, "Every person"),
    (21.3, "who ever changed anything"),
    (24.3, "protected those hours."),
    (27.5, "Fiercely."),
    (38.3, "Not talent."),
    (41.3, "Hours."),
    (47.5, "They weren't more talented than you."),
    (50.5, "Someone protected their time."),
    (54.2, "Who protects yours?"),
    (60.0, "Gaia."),
    (63.0, "Protect the hours."),
]


def generate_clips(client: ElevenLabs) -> list[tuple[float, Path]]:
    """Generate one MP3 per line. Skips if already exists."""
    clips = []
    for i, (t, text) in enumerate(LINES):
        out = VO_DIR / f"line_{i:02d}.mp3"
        if out.exists():
            print(f"  [SKIP] {i:02d}  '{text[:40]}'")
        else:
            print(f"  [GEN]  {i:02d}  '{text[:40]}' @ {t}s ...")
            audio_iter = client.text_to_speech.convert(
                voice_id=VOICE_ID,
                text=text,
                model_id=MODEL_ID,
                voice_settings=VoiceSettings(
                    stability=0.38,
                    similarity_boost=0.80,
                    style=0.22,
                    use_speaker_boost=True,
                ),
            )
            with open(out, "wb") as f:
                for chunk in audio_iter:
                    f.write(chunk)
        clips.append((t, out))
    return clips


def mix_into_video(clips: list[tuple[float, Path]]) -> Path:
    """
    Delay each VO clip to its timestamp with adelay, mix all VO clips
    together, then blend with the existing video music track.
    """
    final_in  = ROOT / "output" / "final.mp4"
    final_out = ROOT / "output" / "final_vo.mp4"

    if not final_in.exists():
        print("final.mp4 not found — run render.py first")
        sys.exit(1)

    # Build ffmpeg inputs: video first, then each VO clip
    inputs: list[str] = ["-i", str(final_in)]
    for _, clip in clips:
        inputs += ["-i", str(clip)]

    # Build filter_complex
    parts: list[str] = []

    # Delay each VO clip to its video timestamp
    for i, (t, _) in enumerate(clips):
        delay_ms = int(t * 1000)
        # i+1 because input 0 is the video
        parts.append(f"[{i + 1}:a]adelay={delay_ms}:all=1[vo{i}]")

    # Mix all delayed VO clips into one track
    n = len(clips)
    all_vo = "".join(f"[vo{i}]" for i in range(n))
    parts.append(
        f"{all_vo}amix=inputs={n}:duration=longest:normalize=false[votrack]"
    )

    # Duck the background music slightly, boost VO
    parts.append("[0:a]volume=0.55[music]")
    parts.append("[votrack]volume=1.4[vo_loud]")
    parts.append(
        "[music][vo_loud]amix=inputs=2:duration=first:normalize=false[aout]"
    )

    filter_complex = ";".join(parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(final_out),
    ]

    print("\nMixing voiceover into video ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[ERROR]\n{r.stderr[-2000:]}")
        sys.exit(1)

    size_mb = final_out.stat().st_size / 1_000_000
    print(f"[DONE] output/final_vo.mp4  ({size_mb:.1f} MB)")
    return final_out


if __name__ == "__main__":
    client = ElevenLabs(api_key=API_KEY)

    print("Step 1/2 — Generating voiceover clips ...")
    clips = generate_clips(client)

    print("\nStep 2/2 — Mixing into video ...")
    mix_into_video(clips)

    print("\nDone. To re-generate a line, delete output/voiceover/line_XX.mp3 and re-run.")
    print("To adjust volume balance, edit the volume= values in mix_into_video().")
