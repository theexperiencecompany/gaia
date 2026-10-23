"""The Air Mail city stamps: catalogue, hosting, derived stamp furniture."""

from collections.abc import Iterator
import json
from pathlib import Path

import pytest

from app.services.briefing.editions import stamps
from app.services.briefing.editions.stamps import (
    StampCity,
    city_axis,
    city_axis_assets,
    hosted_stamp_weights,
    stamp_asset_url,
    stamp_for,
)

_CATALOGUE = Path(stamps.__file__).parent / "explorer" / "assets" / "stamps" / "cities.json"
_PARIS_URL = "https://res.cloudinary.com/x/image/upload/briefing/stamps/paris.webp"


@pytest.fixture(autouse=True)
def _cold_catalogue() -> Iterator[None]:
    """Start every test with the lru-cached catalogue loaders unread."""
    stamps.stamp_catalogue.cache_clear()
    stamps._postage.cache_clear()
    yield
    stamps.stamp_catalogue.cache_clear()
    stamps._postage.cache_clear()


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paris and Tokyo uploaded, Osaka not yet."""
    rows = {
        "paris": StampCity(
            slug="paris", name="Paris", country="France", lat=48.86, lng=2.35, url=_PARIS_URL
        ),
        "tokyo": StampCity(
            slug="tokyo", name="Tokyo", country="Japan", lat=35.68, lng=139.69, url="https://t"
        ),
        "osaka": StampCity(
            slug="osaka", name="Osaka", country="Japan", lat=34.69, lng=135.5, url=None
        ),
    }
    monkeypatch.setattr(stamps, "stamp_catalogue", lambda: rows)


@pytest.mark.unit
class TestCatalogue:
    def test_the_repo_carries_the_catalogue_and_no_stamp_images(self) -> None:
        rows = json.loads(_CATALOGUE.read_text())

        assert len(rows) == 85
        assert all(set(row) == {"slug", "name", "country", "lat", "lng", "url"} for row in rows)
        assert not list(_CATALOGUE.parent.glob("*.webp"))
        assert not list(_CATALOGUE.parent.glob("*.png"))

    def test_every_catalogued_country_has_an_air_mail_phrase(self) -> None:
        rows = json.loads(_CATALOGUE.read_text())

        for row in rows:
            assert stamp_for(row["slug"])["label"] == row["name"]

    def test_a_real_city_yields_the_full_postal_skin(self) -> None:
        assert stamp_for("tokyo") == {
            "id": "tokyo",
            "label": "Tokyo",
            "key": "CITY_TOKYO",
            "city": "TOKYO",
            "air": "Kōkūbin",
        }

    @pytest.mark.parametrize("slug", ["paris", "london", "new_york_city"])
    def test_a_phrase_the_air_mail_label_already_prints_is_not_repeated(self, slug: str) -> None:
        assert stamp_for(slug)["air"] == ""

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

        assert (stamp["key"], stamp["city"], stamp["label"]) == ("CITY_PARIS", "PARIS", "Paris")

    def test_the_city_axis_is_every_uploaded_city_and_its_art(self) -> None:
        assert [stamp["id"] for stamp in city_axis()] == ["paris", "tokyo"]
        assert city_axis_assets() == {"CITY_PARIS": _PARIS_URL, "CITY_TOKYO": "https://t"}

    def test_an_unknown_city_fails_loud(self) -> None:
        with pytest.raises(KeyError):
            stamp_for("atlantis")
