"""The approved webfonts each explorer edition family is set in, as embeddable @font-face rules.

The WOFF2 files, their licences and fonts.json are built by scripts/build_edition_fonts.py.
"""

import base64
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

_FONTS_DIR = Path(__file__).parent / "fonts"
_MANIFEST = _FONTS_DIR / "fonts.json"

_HEROS = "TeX Gyre Heros"
_AEONIK = "Aeonik Extended"

# Every family a template's CSS names; a rendered glyph never falls through to a system font.
EDITION_FAMILIES: dict[str, tuple[str, ...]] = {
    "almanac": ("Libre Baskerville",),
    "band": (_AEONIK, _HEROS),
    "boardingpass": (_AEONIK, _HEROS, "JetBrains Mono"),
    "broadsheet": ("Broadsheet Caslon", "Source Serif 4"),
    "exhibition": ("Bodoni Moda", _HEROS),
    "flightplan": ("Barlow Condensed",),
    "gradient": ("Schibsted Grotesk", "JetBrains Mono"),
    "instrument": (_AEONIK, "Sofia Sans Condensed"),
    "invoice": (_HEROS,),
    "librarycard": ("Special Elite", "Pinyon Script"),
    "memo": ("Courier Prime",),
    "menu": ("Cormorant", "EB Garamond"),
    "metromap": ("Overpass",),
    "playfair": ("Playfair Display", "Literata"),
    "postal": ("Source Serif 4", "Cutive", _AEONIK, _HEROS),
    "receipt": ("JetBrains Mono",),
    "swiss": (_AEONIK, _HEROS),
    "weekly": ("Newsreader", _HEROS),
}


class FontFace(BaseModel):
    """One WOFF2 cut in fonts.json."""

    model_config = ConfigDict(frozen=True)

    family: str
    file: str
    weight: int
    style: Literal["normal", "italic"]
    size_adjust: int | None


class _Manifest(BaseModel):
    faces: list[FontFace]


@lru_cache(maxsize=1)
def font_faces() -> tuple[FontFace, ...]:
    """Return every built cut, read from fonts.json."""
    return tuple(_Manifest.model_validate_json(_MANIFEST.read_bytes()).faces)


def _face_rule(face: FontFace) -> str:
    data = base64.b64encode((_FONTS_DIR / face.file).read_bytes()).decode()
    size_adjust = f"size-adjust:{face.size_adjust}%;" if face.size_adjust else ""
    return (
        f"@font-face{{font-family:'{face.family}';font-style:{face.style};"
        f"font-weight:{face.weight};font-display:block;{size_adjust}"
        f"src:url(data:font/woff2;base64,{data}) format('woff2');}}"
    )


@lru_cache(maxsize=1)
def _family_rules() -> dict[str, str]:
    """Return each family's @font-face rules, every cut inlined as a data URI; read once per process."""
    rules: dict[str, str] = {}
    for face in font_faces():
        rules[face.family] = rules.get(face.family, "") + _face_rule(face)
    return rules


def edition_font_faces_css(family: str) -> str:
    """Return the @font-face rules for the families one edition family is set in."""
    rules = _family_rules()
    return "".join(rules[name] for name in EDITION_FAMILIES[family])
