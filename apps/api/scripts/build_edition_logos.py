# /// script
# dependencies = ["pillow==12.0.0", "resvg-py==0.5.0"]
# ///
"""Build the app marks the brief editions print beside an item into editions/logos/logos.json.

Reads the integration-logos registry (libs/shared/ts/src/icons/integration-logos.ts) and the
web app's icon files, so an edition shows the same mark the app does. Each mark is stored
twice as a 96px PNG data URI: as shipped ("color"), and as an alpha mask an edition paints
in its own ink ("mask"). A mono mark (one colour by brand rule) always prints in ink.

The mask is the mark's ink: every pixel that is not the white of its tile or knockout, so
Reddit's face and LinkedIn's letters stay cut out. A mark drawn in white on transparency
(GitHub, Linear, Vercel) is its alpha instead.

Usage (from the repo root)::

    uv run apps/api/scripts/build_edition_logos.py
"""

import base64
import io
import json
from pathlib import Path
import re

from PIL import Image
import resvg_py

REPO = Path(__file__).resolve().parents[3]
REGISTRY_TS = REPO / "libs/shared/ts/src/icons/integration-logos.ts"
ICONS = REPO / "apps/web/public/images/icons"
OUT = REPO / "apps/api/app/services/briefing/editions/logos/logos.json"

LOGO_PX = 96
# A channel above this on all three is the white of a tile or a knockout, not ink.
WHITE_FLOOR = 225
# Marks drawn in white on transparency: their ink is their alpha.
WHITE_MARKS = frozenset({"github", "linear", "vercel"})
# Single-colour marks by brand rule: printed in the edition's ink even where colour is allowed.
MONO_MARKS = frozenset({"github", "linear", "notion", "vercel"})


def registry_files() -> dict[str, str]:
    """Return INTEGRATION_LOGO_FILES: integration id -> icon file name."""
    block = REGISTRY_TS.read_text().split("INTEGRATION_LOGO_FILES", 1)[1].split("};", 1)[0]
    return dict(re.findall(r'^\s+(\w+):\s*"([^"]+)"', block, re.M))


def load(path: Path) -> Image.Image:
    if path.suffix == ".svg":
        png = resvg_py.svg_to_bytes(svg_path=str(path), width=LOGO_PX, height=LOGO_PX)
        image = Image.open(io.BytesIO(png))
    else:
        image = Image.open(path)
    rgba = image.convert("RGBA")
    rgba.thumbnail((LOGO_PX, LOGO_PX), Image.Resampling.LANCZOS)
    return rgba


def mask(image: Image.Image, white_mark: bool) -> Image.Image:
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.putdata(
        [
            (0, 0, 0, a if white_mark or min(r, g, b) < WHITE_FLOOR else 0)
            for r, g, b, a in image.getdata()
        ]
    )
    return out


def png_uri(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    logos: dict[str, dict[str, str]] = {}
    for key, file in sorted(registry_files().items()):
        image = load(ICONS / file)
        logos[key] = {
            "kind": "mono" if key in MONO_MARKS else "color",
            "color": png_uri(image),
            "mask": png_uri(mask(image, key in WHITE_MARKS)),
        }
        print(f"{key:18} {file}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(logos, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
