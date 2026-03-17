#!/usr/bin/env python3
# apps/manifesto-video/run.py
# One-shot pipeline: download → assemble → render → done.
# Run from apps/manifesto-video/

import subprocess
import sys
from pathlib import Path


def run_step(name: str, script: str) -> None:
    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}")
    result = subprocess.run(
        [sys.executable, script],
        cwd=Path(__file__).parent,
    )
    if result.returncode != 0:
        print(f"\n[PIPELINE STOPPED] {name} failed.")
        print(f"Fix the issue then re-run: python3 {script}")
        sys.exit(1)


def main() -> None:
    print("GAIA Manifesto Video Pipeline")
    print("================================\n")

    run_step("Step 1/3 — Downloading clips", "download.py")
    run_step("Step 2/3 — Assembling raw cut", "assemble.py")
    run_step("Step 3/3 — Rendering final video", "render.py")

    print("\n================================")
    print("  DONE — output/final.mp4")
    print("================================")
    print("\nTo iterate:")
    print("  Clip pacing:  edit CLIPS in config.py → delete clips/raw/CLIP_ID.mp4 → python3 run.py")
    print("  Text timing:  edit TEXT_TIMELINE in config.py → python3 render.py")
    print("  Music volume: edit MUSIC_VOLUME in config.py → python3 render.py")


if __name__ == "__main__":
    main()
