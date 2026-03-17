#!/usr/bin/env python3
# apps/manifesto-video/assemble.py
# Generates the black end card clip, concatenates all clips into raw_cut.mp4.

import subprocess
import sys
from pathlib import Path

from config import CLIPS, CLIPS_RAW, FPS, OUTPUT, VIDEO_H, VIDEO_W


def generate_black_clip(out: Path, duration: int = 9) -> bool:
    """Generate a solid black clip for the GAIA end card."""
    if out.exists():
        print(f"  [SKIP] gaia_black already exists")
        return True

    print(f"  Generating gaia_black ({duration}s)...")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={VIDEO_W}x{VIDEO_H}:r={FPS}",
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-an",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] gaia_black: {result.stderr[-400:]}")
        return False
    print(f"  [DONE] gaia_black")
    return True


def build_concat_list(concat_file: Path) -> list[str]:
    """Write ffmpeg concat list. Returns list of missing clip IDs."""
    missing = []
    lines   = []

    for clip in CLIPS:
        src = CLIPS_RAW / f"{clip['id']}.mp4"
        if not src.exists():
            missing.append(clip["id"])
        else:
            lines.append(f"file '{src.resolve()}'\n")

    # Add generated black end card
    black_path = CLIPS_RAW / "gaia_black.mp4"
    if not black_path.exists():
        missing.append("gaia_black")
    else:
        lines.append(f"file '{black_path.resolve()}'\n")

    concat_file.write_text("".join(lines))
    return missing


def get_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    CLIPS_RAW.mkdir(parents=True, exist_ok=True)

    # Generate black end card
    black_path = CLIPS_RAW / "gaia_black.mp4"
    if not generate_black_clip(black_path, duration=9):
        sys.exit(1)

    concat_file = OUTPUT / "concat_list.txt"
    raw_cut     = OUTPUT / "raw_cut.mp4"

    missing = build_concat_list(concat_file)
    if missing:
        print(f"\nMissing clips — run download.py first: {missing}")
        sys.exit(1)

    print("\nAssembling raw_cut.mp4...")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(raw_cut),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] assembly failed:\n{result.stderr[-800:]}")
        sys.exit(1)

    duration = get_duration(raw_cut)
    print(f"[DONE] raw_cut.mp4  —  {duration:.1f}s total")
    print("\nReview output/raw_cut.mp4.")
    print("Adjust start/duration in config.py CLIPS if needed, re-run download.py + assemble.py.")


if __name__ == "__main__":
    main()
