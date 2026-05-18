"""Download Piper voice models in parallel from HuggingFace.

Idempotent: skips files that already exist with a non-zero size.
"""

from __future__ import annotations

import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

VOICES = [
    # (relative_path, voice_name)
    ("en/en_US/amy/medium", "en_US-amy-medium"),
    ("en/en_US/ryan/high", "en_US-ryan-high"),
    ("en/en_US/lessac/medium", "en_US-lessac-medium"),
    ("en/en_US/hfc_female/medium", "en_US-hfc_female-medium"),
    ("en/en_US/libritts/high", "en_US-libritts-high"),
    ("en/en_GB/alan/medium", "en_GB-alan-medium"),
    ("en/en_GB/jenny_dioco/medium", "en_GB-jenny_dioco-medium"),
]


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 1024:
        print(f"  ok  {dest.name} ({dest.stat().st_size:,} bytes)")
        return
    print(f"  get {dest.name}")
    with urllib.request.urlopen(url) as r, dest.open("wb") as f:
        # 1 MB chunks
        while chunk := r.read(1 << 20):
            f.write(chunk)
    print(f"  ok  {dest.name} ({dest.stat().st_size:,} bytes)")


def fetch_voice(relpath: str, name: str, out_dir: Path) -> None:
    download(f"{BASE}/{relpath}/{name}.onnx", out_dir / f"{name}.onnx")
    download(f"{BASE}/{relpath}/{name}.onnx.json", out_dir / f"{name}.onnx.json")


def main() -> None:
    out_dir = Path(__file__).parent.parent / "data" / "voices"
    out_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda v: fetch_voice(v[0], v[1], out_dir), VOICES))
    files = sorted(out_dir.glob("*.onnx"))
    total = sum(f.stat().st_size for f in files)
    print(f"\n{len(files)} voices, {total / 1e6:.1f} MB total")


if __name__ == "__main__":
    sys.exit(main() or 0)
