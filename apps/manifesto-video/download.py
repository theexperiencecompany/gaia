#!/usr/bin/env python3
# apps/manifesto-video/download.py
# Downloads specific segments from archive.org using ffmpeg HTTP streaming.
# Much faster than downloading full files — seeks directly to the timestamp.

import subprocess
import sys
from pathlib import Path

from config import CLIPS, CLIPS_RAW, COLOR_GRADE, FPS, VIDEO_H, VIDEO_W


def download_clip(clip: dict, force: bool = False) -> bool:
    clip_id  = clip["id"]
    url      = clip["url"]
    start    = clip["start"]
    duration = clip["duration"]
    out      = CLIPS_RAW / f"{clip_id}.mp4"

    if out.exists() and not force:
        size_mb = out.stat().st_size / 1_000_000
        print(f"  [SKIP] {clip_id} already exists ({size_mb:.1f} MB)")
        return True

    print(f"  Downloading {clip_id}  [{start} + {duration}s]")
    print(f"    {url[:80]}...")

    # Scale + pad to target resolution, apply color grade
    scale_filter = (
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    vf = f"{scale_filter},{COLOR_GRADE}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", start,           # seek BEFORE -i for fast HTTP range seek
        "-i", url,
        "-t", str(duration),
        "-vf", vf,
        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-an",                  # strip audio — music added at render step
        str(out),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] {clip_id}")
        print(result.stderr[-800:])
        return False

    size_mb = out.stat().st_size / 1_000_000
    print(f"  [DONE]  {clip_id}  ({size_mb:.1f} MB)")
    return True


def main() -> None:
    CLIPS_RAW.mkdir(parents=True, exist_ok=True)
    force = "--force" in sys.argv

    print(f"Downloading {len(CLIPS)} clips (force={force})...\n")
    failed = []
    for clip in CLIPS:
        ok = download_clip(clip, force=force)
        if not ok:
            failed.append(clip["id"])

    print()
    if failed:
        print(f"FAILED: {failed}")
        print("Adjust start/duration timestamps in config.py and re-run.")
        sys.exit(1)
    else:
        print(f"All {len(CLIPS)} clips downloaded to clips/raw/")


if __name__ == "__main__":
    main()
