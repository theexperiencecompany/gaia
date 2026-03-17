#!/usr/bin/env python3
"""Probe candidate timestamps from remote URLs, extracting preview frames."""
import subprocess
import sys
from pathlib import Path

PROBE_DIR = Path(__file__).parent / "clips" / "probe"
PROBE_DIR.mkdir(parents=True, exist_ok=True)

CANDIDATES = [
    # (label, url, timestamp)
    # --- TIMESTAMP FIXES ---
    ("einstein_005",   "https://ia600303.us.archive.org/0/items/capsca_00009/capsca_00009_access.HD.mp4", "00:00:05"),
    ("einstein_030",   "https://ia600303.us.archive.org/0/items/capsca_00009/capsca_00009_access.HD.mp4", "00:00:30"),
    ("einstein_100",   "https://ia600303.us.archive.org/0/items/capsca_00009/capsca_00009_access.HD.mp4", "00:01:00"),

    ("mlk_1140",  "https://archive.org/download/youtube-1UV1fs8lAbg/1UV1fs8lAbg.mp4", "00:11:40"),
    ("mlk_1200",  "https://archive.org/download/youtube-1UV1fs8lAbg/1UV1fs8lAbg.mp4", "00:12:00"),
    ("mlk_1230",  "https://archive.org/download/youtube-1UV1fs8lAbg/1UV1fs8lAbg.mp4", "00:12:30"),

    ("ali_030",   "https://archive.org/download/youtube-Ku0Mo3Lzqss/Ku0Mo3Lzqss.mp4", "00:00:30"),
    ("ali_100",   "https://archive.org/download/youtube-Ku0Mo3Lzqss/Ku0Mo3Lzqss.mp4", "00:01:00"),

    ("mj_300",    "https://archive.org/download/michael-jackson-billie-jean-1983-motown-25-live/Michael%20Jackson%20-%20Billie%20Jean%20%5B1983%20Motown%2025%20Live%5D.mp4", "00:03:00"),
    ("mj_310",    "https://archive.org/download/michael-jackson-billie-jean-1983-motown-25-live/Michael%20Jackson%20-%20Billie%20Jean%20%5B1983%20Motown%2025%20Live%5D.mp4", "00:03:10"),
    ("mj_315",    "https://archive.org/download/michael-jackson-billie-jean-1983-motown-25-live/Michael%20Jackson%20-%20Billie%20Jean%20%5B1983%20Motown%2025%20Live%5D.mp4", "00:03:15"),

    ("maradona_015", "https://archive.org/download/2331687-maradona-onderstreept-zijn-status-met-prachtige-sologoal-op-wk-86/2331687-maradona-onderstreept-zijn-status-met-prachtige-sologoal-op-wk-86.mp4", "00:00:15"),
    ("maradona_025", "https://archive.org/download/2331687-maradona-onderstreept-zijn-status-met-prachtige-sologoal-op-wk-86/2331687-maradona-onderstreept-zijn-status-met-prachtige-sologoal-op-wk-86.mp4", "00:00:25"),
    ("maradona_040", "https://archive.org/download/2331687-maradona-onderstreept-zijn-status-met-prachtige-sologoal-op-wk-86/2331687-maradona-onderstreept-zijn-status-met-prachtige-sologoal-op-wk-86.mp4", "00:00:40"),

    ("bolt_630",  "https://archive.org/download/UsainBoltWinsOlympic100mGoldLondon2012Olympics/Usain%20Bolt%20Wins%20Olympic%20100m%20Gold%20-%20London%202012%20Olympics.mp4", "00:06:30"),
    ("bolt_700",  "https://archive.org/download/UsainBoltWinsOlympic100mGoldLondon2012Olympics/Usain%20Bolt%20Wins%20Olympic%20100m%20Gold%20-%20London%202012%20Olympics.mp4", "00:07:00"),
    ("bolt_720",  "https://archive.org/download/UsainBoltWinsOlympic100mGoldLondon2012Olympics/Usain%20Bolt%20Wins%20Olympic%20100m%20Gold%20-%20London%202012%20Olympics.mp4", "00:07:20"),

    ("bruce_11000", "https://archive.org/download/bruce-lee-a-warriors-journey/Bruce%20Lee%20A%20Warriors%20Journey%20%282000%29.ia.mp4", "01:10:00"),
    ("bruce_11500", "https://archive.org/download/bruce-lee-a-warriors-journey/Bruce%20Lee%20A%20Warriors%20Journey%20%282000%29.ia.mp4", "01:15:00"),
    ("bruce_12000", "https://archive.org/download/bruce-lee-a-warriors-journey/Bruce%20Lee%20A%20Warriors%20Journey%20%282000%29.ia.mp4", "01:20:00"),

    ("federer_200", "https://archive.org/download/2018-roger-federer-v.-novak-djokovic-2018-cincinnati-f-highlights/2018%20-%20Roger%20Federer%20v.%20Novak%20Djokovic%20%7C%202018%20Cincinnati%20F%20Highlights.mp4", "00:02:00"),
    ("federer_230", "https://archive.org/download/2018-roger-federer-v.-novak-djokovic-2018-cincinnati-f-highlights/2018%20-%20Roger%20Federer%20v.%20Novak%20Djokovic%20%7C%202018%20Cincinnati%20F%20Highlights.mp4", "00:02:30"),
    ("federer_300", "https://archive.org/download/2018-roger-federer-v.-novak-djokovic-2018-cincinnati-f-highlights/2018%20-%20Roger%20Federer%20v.%20Novak%20Djokovic%20%7C%202018%20Cincinnati%20F%20Highlights.mp4", "00:03:00"),

    ("gould_2000", "https://ia800506.us.archive.org/24/items/cities-1979-glenn-goulds-toronto/Glenn%20Gould%27s%20Toronto.mp4", "00:20:00"),
    ("gould_2500", "https://ia800506.us.archive.org/24/items/cities-1979-glenn-goulds-toronto/Glenn%20Gould%27s%20Toronto.mp4", "00:25:00"),
    ("gould_3000", "https://ia800506.us.archive.org/24/items/cities-1979-glenn-goulds-toronto/Glenn%20Gould%27s%20Toronto.mp4", "00:30:00"),

    # --- SOURCE REPLACEMENTS ---
    # Armstrong moon — try different URL at actual moonwalk
    ("armstrong_nasa1", "https://archive.org/download/gov.archives.arc.45017/gov.archives.arc.45017.mp4", "00:10:00"),
    ("armstrong_nasa2", "https://archive.org/download/gov.archives.arc.45017/gov.archives.arc.45017.mp4", "00:06:00"),

    # Pele — try 1970 World Cup footage
    ("pele_1970_a", "https://archive.org/download/1958_Brasil_Sweden_World_Cup_Final_Football_Soccer/1958_Brasil_Sweden_World_Cup_Final_Football_Soccer.mp4", "00:05:00"),
]


def probe(label: str, url: str, ts: str) -> bool:
    out = PROBE_DIR / f"{label}.jpg"
    if out.exists():
        print(f"  [SKIP] {label}")
        return True
    print(f"  Probing {label} @ {ts}...")
    cmd = [
        "ffmpeg", "-y",
        "-ss", ts,
        "-i", url,
        "-frames:v", "1",
        "-q:v", "2",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not out.exists():
        print(f"    [FAIL] {label}: {r.stderr[-300:]}")
        return False
    print(f"    [OK] {label}")
    return True


if __name__ == "__main__":
    label_filter = sys.argv[1] if len(sys.argv) > 1 else None
    for label, url, ts in CANDIDATES:
        if label_filter and label_filter not in label:
            continue
        probe(label, url, ts)
    print(f"\nDone. Frames saved to {PROBE_DIR}")
