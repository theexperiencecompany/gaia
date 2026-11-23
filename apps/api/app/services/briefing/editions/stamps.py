"""Air Mail city stamps: the founder's 85 city artworks and their postage.

explorer/assets/stamps/ holds each city's art as <slug>.webp (written by
scripts/build_edition_art.py), shipped in the image so no deployment fetches it from
elsewhere, beside cities.json and countries.json. A brief's stamp city is drawn from the
user's shuffle bag; stamp_for turns it into the city skin the vendored postal template
reads, and the Postmarks page places it on the globe by its lat/lng.
"""

from functools import lru_cache
import json
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, TypeAdapter

_STAMPS_DIR = Path(__file__).parent / "explorer" / "assets" / "stamps"
_DISPLAY_DIR = _STAMPS_DIR / "display"
_CITIES_JSON = _STAMPS_DIR / "cities.json"
_COUNTRIES_JSON = _STAMPS_DIR / "countries.json"
# The air-mail label's own words; a country whose phrase is one of them gets no
# local line above the label.
_LABEL_PHRASES = frozenset({"par avion", "by air mail"})


class Stamp(TypedDict):
    """The postal template's skin.city shape, verbatim."""

    id: str
    #: The city as the letter's dateline names it.
    label: str
    #: The asset key of the stamp art.
    key: str
    #: The city on the postmark's arc.
    city: str
    #: The country's own air-mail phrase, set above PAR AVION; empty when it is
    #: the label's own words.
    air: str


class StampCity(BaseModel):
    """One catalogued city: its name and where it sits on the globe."""

    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    country: str
    lat: float
    lng: float


class _Postage(TypedDict):
    denom: str
    air: str
    airSub: str


@lru_cache(maxsize=1)
def stamp_catalogue() -> dict[str, StampCity]:
    """Return every catalogued stamp city keyed by slug."""
    rows = TypeAdapter(list[StampCity]).validate_json(_CITIES_JSON.read_text())
    return {row.slug: row for row in rows}


@lru_cache(maxsize=1)
def _postage() -> dict[str, _Postage]:
    data: dict[str, _Postage] = json.loads(_COUNTRIES_JSON.read_text())
    return data


def stamp_weights() -> dict[str, int]:
    """Return the user's stamp bag: every catalogued city once per pass."""
    return dict.fromkeys(stamp_catalogue(), 1)


def stamp_for(slug: str) -> Stamp:
    """Return the stamp skin for one city: its art key, name and air-mail phrase."""
    city: StampCity = stamp_catalogue()[slug]
    postage: _Postage = _postage()[city.country]
    air = postage["air"]
    return {
        "id": slug,
        "label": city.name,
        "key": stamp_asset_key(slug),
        "city": city.name.upper(),
        "air": "" if air.lower() in _LABEL_PHRASES else air,
    }


def stamp_asset_key(slug: str) -> str:
    """Return the asset key the postal template reads the city's stamp art from."""
    return f"CITY_{slug.upper()}"


def city_axis() -> list[Stamp]:
    """Return the postal template's city axis: every catalogued city's stamp skin."""
    return [stamp_for(slug) for slug in stamp_catalogue()]


def stamp_art(slug: str) -> Path:
    """Return the file holding a catalogued city's stamp art; KeyError for any other slug."""
    return _STAMPS_DIR / f"{stamp_catalogue()[slug].slug}.webp"


def stamp_display_art(slug: str) -> Path:
    """Return the small web-sized variant of a stamp's art; KeyError for any other slug."""
    return _DISPLAY_DIR / f"{stamp_catalogue()[slug].slug}.webp"
