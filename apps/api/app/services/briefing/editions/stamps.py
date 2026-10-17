"""Air Mail city stamps: the founder's 85 city artworks and their postage.

The artworks are hosted on Cloudinary (uploaded by scripts/upload_city_stamps.py),
never committed. explorer/assets/stamps/ holds cities.json and countries.json. A
brief's stamp city is drawn from the user's shuffle bag; stamp_for turns it into the
city skin the vendored postal template reads.
"""

from functools import lru_cache
import json
from pathlib import Path
from typing import TypedDict

_STAMPS_DIR = Path(__file__).parent / "explorer" / "assets" / "stamps"
_CITIES_JSON = _STAMPS_DIR / "cities.json"
_COUNTRIES_JSON = _STAMPS_DIR / "countries.json"
# The asset key the postal template reads the drawn city's stamp art from.
STAMP_ASSET_KEY = "STAMP_CITY"
# The postal template's own city axis (a legacy brief without a drawn city picks
# from it): each option's asset key and the catalogued city whose art it shows.
_AXIS_CITY_SLUGS: dict[str, str] = {
    "CITY_TOKYO": "tokyo",
    "CITY_PARIS": "paris",
    "CITY_LONDON": "london",
    "CITY_NEWYORK": "new_york_city",
    "CITY_MUMBAI": "mumbai",
    "CITY_ISTANBUL": "istanbul",
}
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


class _City(TypedDict):
    slug: str
    name: str
    country: str
    url: str | None


class _Postage(TypedDict):
    denom: str
    air: str
    airSub: str


@lru_cache(maxsize=1)
def _cities() -> dict[str, _City]:
    rows: list[_City] = json.loads(_CITIES_JSON.read_text())
    return {row["slug"]: row for row in rows}


@lru_cache(maxsize=1)
def _postage() -> dict[str, _Postage]:
    data: dict[str, _Postage] = json.loads(_COUNTRIES_JSON.read_text())
    return data


def hosted_stamp_weights() -> dict[str, int]:
    """Return the drawable stamp cities, once per pass of the user's stamp bag.

    Every catalogued city whose art is uploaded is drawable.
    """
    cities: dict[str, _City] = _cities()
    return {slug: 1 for slug, city in cities.items() if city["url"]}


def stamp_for(slug: str) -> Stamp:
    """Return the stamp skin for one city: its art key, name and air-mail phrase."""
    city: _City = _cities()[slug]
    postage: _Postage = _postage()[city["country"]]
    air = postage["air"]
    return {
        "id": slug,
        "label": city["name"],
        "key": STAMP_ASSET_KEY,
        "city": city["name"].upper(),
        "air": "" if air.lower() in _LABEL_PHRASES else air,
    }


def axis_stamp_assets() -> dict[str, str]:
    """Return the hosted art of the postal template's own city axis, by asset key."""
    return {key: stamp_asset_url(slug) for key, slug in _AXIS_CITY_SLUGS.items()}


def stamp_asset_url(slug: str) -> str:
    """Return the city's hosted stamp art, loaded by the render page as the stamp image."""
    city: _City | None = _cities().get(slug)
    url = city["url"] if city else None
    if not url:
        raise KeyError(f"stamp city {slug!r} has no hosted art (run scripts/upload_city_stamps.py)")
    return url
