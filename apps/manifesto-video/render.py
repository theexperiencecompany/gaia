#!/usr/bin/env python3
# apps/manifesto-video/render.py
# Burns manifesto text overlays onto raw_cut.mp4 and mixes in music.
# Output: output/final.mp4

import subprocess
import sys
from pathlib import Path

from config import (
    BORDER_COLOR,
    BORDER_W,
    FONT_COLOR,
    FONT_FILE,
    FONT_SIZE,
    MUSIC_FADE_START,
    MUSIC_FILE,
    MUSIC_VOLUME,
    OUTPUT,
    TEXT_TIMELINE,
    TEXT_X,
    TEXT_Y,
)


def escape_drawtext(text: str) -> str:
    """Escape special characters for ffmpeg drawtext filter."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'",  "\u2019")  # typographic apostrophe avoids shell quoting issues
        .replace(":",  "\\:")
        .replace(",",  "\\,")
        .replace("[",  "\\[")
        .replace("]",  "\\]")
        .replace("%",  "\\%")
    )


def build_drawtext_chain() -> str:
    """Build a chained drawtext filtergraph from TEXT_TIMELINE."""
    filters = []
    for entry in TEXT_TIMELINE:
        t_start = entry["time"]
        t_end   = t_start + entry["dur"]
        text    = escape_drawtext(entry["text"])
        enable  = f"between(t\\,{t_start}\\,{t_end})"

        f = (
            f"drawtext="
            f"fontfile={FONT_FILE}:"
            f"text='{text}':"
            f"fontcolor={FONT_COLOR}:"
            f"fontsize={FONT_SIZE}:"
            f"x={TEXT_X}:"
            f"y={TEXT_Y}:"
            f"bordercolor={BORDER_COLOR}:"
            f"borderw={BORDER_W}:"
            f"enable='{enable}'"
        )
        filters.append(f)

    return ",".join(filters)


def main() -> None:
    raw_cut = OUTPUT / "raw_cut.mp4"
    final   = OUTPUT / "final.mp4"

    if not raw_cut.exists():
        print("raw_cut.mp4 not found — run assemble.py first")
        sys.exit(1)

    has_music = MUSIC_FILE.exists()
    if not has_music:
        print(f"No music at {MUSIC_FILE} — rendering without audio")

    drawtext = build_drawtext_chain()

    # Cover PeriscopeFilm.com watermark on rocket launch clip (0–4s, bottom strip)
    watermark_cover = (
        "drawbox=x=300:y=970:w=1400:h=110"
        ":color=black@1:t=fill"
        ":enable='between(t\\,0\\,4)'"
    )
    video_filters = f"{drawtext},{watermark_cover}"

    print("Rendering final.mp4  (this takes ~30-60s)...")

    if has_music:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_cut),
            "-i", str(MUSIC_FILE),
            "-filter_complex",
                f"[0:v]{video_filters}[v];"
                f"[1:a]volume={MUSIC_VOLUME},afade=t=out:st={MUSIC_FADE_START}:d=4[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "16",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(final),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_cut),
            "-vf", video_filters,
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "16",
            "-an",
            str(final),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] render failed:\n{result.stderr[-1200:]}")
        sys.exit(1)

    size_mb = final.stat().st_size / 1_000_000
    print(f"[DONE] output/final.mp4  ({size_mb:.1f} MB)")
    print("\nTo iterate on text timing: edit TEXT_TIMELINE in config.py and re-run render.py only.")


if __name__ == "__main__":
    main()
