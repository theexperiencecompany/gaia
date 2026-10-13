"""Air Mail city stamps: the founder's 85 city artworks and their postage.

``explorer/assets/stamps/`` holds one ~600px WebP per city, ``cities.json``
(slug, name, country) and ``countries.json`` (postcard-rate denomination and
Latin-script air-mail etiquette per country). A brief's stamp city is drawn from
the user's shuffle bag (``STAMP_CITY_WEIGHTS``); ``stamp_for`` turns it into the
``city`` skin the vendored ``postal`` template reads, so the stamp art, the
"GAIA Post · CITY" line, the denomination and the postmark all name one city.
"""

import base64
from functools import lru_cache
import json
from pathlib import Path
from typing import TypedDict

_STAMPS_DIR = Path(__file__).parent / "explorer" / "assets" / "stamps"
# The asset key the postal template reads the stamp art from.
STAMP_ASSET_KEY = "STAMP_CITY"
# Engraved-frame colours of the vendored postal stamps, cycled across cities.
_FRAME_COLORS = ("#9c3b34", "#2f5233", "#26467a", "#8c2f4a", "#2f6b46", "#7a2f2f")


class StampExtra(TypedDict):
    kind: str
    code: str
    sub: str


class Stamp(TypedDict):
    """The postal template's ``skin.city`` shape, verbatim."""

    id: str
    label: str
    src: str
    city: str
    air: str
    airSub: str
    denom: str
    frame: str
    extra: StampExtra


class _City(TypedDict):
    slug: str
    name: str
    country: str


class _Postage(TypedDict):
    denom: str
    air: str
    airSub: str


@lru_cache(maxsize=1)
def _cities() -> dict[str, _City]:
    rows: list[_City] = json.loads((_STAMPS_DIR / "cities.json").read_text())
    return {row["slug"]: row for row in rows}


@lru_cache(maxsize=1)
def _postage() -> dict[str, _Postage]:
    data: dict[str, _Postage] = json.loads((_STAMPS_DIR / "countries.json").read_text())
    return data


STAMP_CITY_WEIGHTS: dict[str, int] = dict.fromkeys(_cities(), 1)


def stamp_for(slug: str) -> Stamp:
    """The stamp skin for one city: its art key, name, postage and frame."""
    city = _cities()[slug]
    postage = _postage()[city["country"]]
    return {
        "id": slug,
        "label": f"{city['name']}, {city['country']}",
        "src": STAMP_ASSET_KEY,
        "city": city["name"].upper(),
        "air": postage["air"],
        "airSub": postage["airSub"],
        "denom": postage["denom"],
        "frame": _FRAME_COLORS[sorted(_cities()).index(slug) % len(_FRAME_COLORS)],
        "extra": {"kind": "customs", "code": "CN 22", "sub": "Customs · Douane"},
    }


def stamp_asset_uri(slug: str) -> str:
    """The city's stamp art as a data URI, inlined into the render document."""
    if slug not in _cities():
        raise KeyError(f"unknown stamp city: {slug!r}")
    encoded = base64.b64encode((_STAMPS_DIR / f"{slug}.webp").read_bytes()).decode()
    return f"data:image/webp;base64,{encoded}"
