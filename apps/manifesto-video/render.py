#!/usr/bin/env python3
# apps/manifesto-video/render.py
# Burns manifesto text overlays + GAIA logo onto raw_cut.mp4 and mixes in music.
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
    ROOT,
    TEXT_TIMELINE,
    TEXT_X,
    TEXT_Y,
)

LOGO_FILE = ROOT / "fonts" / "gaia_wordmark_white.png"
# Logo appears during gaia_black end card (58–67s), fade in over 1s
LOGO_START = 59
LOGO_END = 67
LOGO_WIDTH = 600  # scale logo to this width, keep aspect ratio


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

    has_logo = LOGO_FILE.exists()
    if not has_logo:
        print(f"No logo at {LOGO_FILE} — rendering without logo overlay")

    drawtext = build_drawtext_chain()

    # Cover PeriscopeFilm.com watermark on rocket launch clip (0–4s, bottom strip)
    watermark_cover = (
        "drawbox=x=300:y=920:w=1400:h=160"
        ":color=black@1:t=fill"
        ":enable='between(t\\,0\\,4)'"
    )

    print("Rendering final.mp4  (this takes ~30-60s)...")

    if has_music and has_logo:
        # Full render: video + drawtext + watermark cover + logo overlay + music
        # Inputs: [0] raw_cut.mp4, [1] music, [2] logo PNG
        logo_fade_in = (
            f"[2:v]scale={LOGO_WIDTH}:-1,format=rgba,"
            f"fade=t=in:st=0:d=1:alpha=1[logo]"
        )
        video_chain = (
            f"[0:v]{drawtext},{watermark_cover}[vtmp];"
            f"{logo_fade_in};"
            f"[vtmp][logo]overlay=(W-w)/2:(H-h)/2"
            f":enable='between(t\\,{LOGO_START}\\,{LOGO_END})'[v]"
        )
        audio_chain = (
            f"[1:a]volume={MUSIC_VOLUME},"
            f"afade=t=out:st={MUSIC_FADE_START}:d=4[a]"
        )
        filter_complex = f"{video_chain};{audio_chain}"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_cut),
            "-i", str(MUSIC_FILE),
            "-loop", "1", "-i", str(LOGO_FILE),
            "-filter_complex", filter_complex,
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
    elif has_music:
        video_filters = f"{drawtext},{watermark_cover}"
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
        video_filters = f"{drawtext},{watermark_cover}"
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
        print(f"[ERROR] render failed:\n{result.stderr[-1500:]}")
        sys.exit(1)

    size_mb = final.stat().st_size / 1_000_000
    print(f"[DONE] output/final.mp4  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
