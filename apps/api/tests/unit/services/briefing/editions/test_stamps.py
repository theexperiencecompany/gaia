"""The Air Mail city stamps: catalogue, hosting, derived stamp furniture."""

from collections.abc import Iterator
import json
from pathlib import Path

import pytest

from app.services.briefing.editions import stamps
from app.services.briefing.editions.stamps import (
    hosted_stamp_weights,
    stamp_asset_url,
    stamp_for,
)

_CATALOGUE = Path(stamps.__file__).parent / "explorer" / "assets" / "stamps" / "cities.json"
_PARIS_URL = "https://res.cloudinary.com/x/image/upload/briefing/stamps/paris.webp"


@pytest.fixture(autouse=True)
def _cold_catalogue() -> Iterator[None]:
    """Start every test with the lru-cached catalogue loaders unread."""
    stamps._cities.cache_clear()
    stamps._postage.cache_clear()
    yield
    stamps._cities.cache_clear()
    stamps._postage.cache_clear()


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paris and Tokyo uploaded, Osaka not yet."""
    rows = {
        "paris": {"slug": "paris", "name": "Paris", "country": "France", "url": _PARIS_URL},
        "tokyo": {"slug": "tokyo", "name": "Tokyo", "country": "Japan", "url": "https://t"},
        "osaka": {"slug": "osaka", "name": "Osaka", "country": "Japan", "url": None},
    }
    monkeypatch.setattr(stamps, "_cities", lambda: rows)


@pytest.mark.unit
class TestCatalogue:
    def test_the_repo_carries_the_catalogue_and_no_stamp_images(self) -> None:
        rows = json.loads(_CATALOGUE.read_text())

        assert len(rows) == 85
        assert all(set(row) == {"slug", "name", "country", "url"} for row in rows)
        assert not list(_CATALOGUE.parent.glob("*.webp"))
        assert not list(_CATALOGUE.parent.glob("*.png"))

    def test_every_catalogued_country_has_postage(self) -> None:
        rows = json.loads(_CATALOGUE.read_text())

        for row in rows:
            assert stamp_for(row["slug"])["denom"]

    def test_a_real_city_yields_the_full_postal_skin(self) -> None:
        assert stamp_for("paris") == {
            "id": "paris",
            "label": "Paris, France",
            "src": "STAMP_CITY",
            "city": "PARIS",
            "air": "Par Avion",
            "airSub": "By Air Mail",
            "denom": "€1,96",
            "frame": "#7a2f2f",
            "extra": {"kind": "customs", "code": "CN 22", "sub": "Customs · Douane"},
        }

    def test_frame_colours_cycle_by_the_citys_alphabetical_position(self) -> None:
        assert stamp_for("addis_ababa")["frame"] == "#9c3b34"
        assert stamp_for("ahmedabad")["frame"] == "#2f5233"

    def test_every_catalogued_city_is_hosted_and_drawable(self) -> None:
        rows = json.loads(_CATALOGUE.read_text())

        assert hosted_stamp_weights() == {row["slug"]: 1 for row in rows}
        assert stamp_asset_url("tokyo") == rows[[r["slug"] for r in rows].index("tokyo")]["url"]


@pytest.mark.unit
@pytest.mark.usefixtures("hosted")
class TestHostedStamps:
    def test_only_uploaded_cities_can_be_drawn(self) -> None:
        assert hosted_stamp_weights() == {"paris": 1, "tokyo": 1}

    def test_the_stamp_art_loads_by_its_hosted_url(self) -> None:
        assert stamp_asset_url("paris") == _PARIS_URL

    def test_a_city_not_yet_uploaded_fails_loud(self) -> None:
        with pytest.raises(KeyError, match="osaka"):
            stamp_asset_url("osaka")

    def test_the_stamp_text_is_derived_from_its_city(self) -> None:
        stamp = stamp_for("paris")

        assert stamp["src"] == "STAMP_CITY"
        assert stamp["city"] == "PARIS"
        assert stamp["denom"] == "€1,96"
        assert stamp["air"] == "Par Avion"

    def test_cities_in_one_country_share_its_postage(self) -> None:
        assert stamp_for("tokyo")["denom"] == stamp_for("osaka")["denom"] == "¥110"

    def test_an_unknown_city_fails_loud(self) -> None:
        with pytest.raises(KeyError):
            stamp_for("atlantis")
