"""The Air Mail city stamps: catalogue, the art shipped beside it, derived stamp furniture."""

from collections.abc import Iterator
import json
from pathlib import Path

import pytest

from app.services.briefing.editions import stamps
from app.services.briefing.editions.stamps import (
    city_axis,
    stamp_art,
    stamp_for,
    stamp_weights,
)

_CATALOGUE = Path(stamps.__file__).parent / "explorer" / "assets" / "stamps" / "cities.json"
_WEBP_MAGIC = (b"RIFF", b"WEBP")


@pytest.fixture(autouse=True)
def _cold_catalogue() -> Iterator[None]:
    """Start every test with the lru-cached catalogue loaders unread."""
    stamps.stamp_catalogue.cache_clear()
    stamps._postage.cache_clear()
    yield
    stamps.stamp_catalogue.cache_clear()
    stamps._postage.cache_clear()


@pytest.mark.unit
class TestCatalogue:
    def test_every_catalogued_city_ships_its_art_and_no_hosted_url(self) -> None:
        rows = json.loads(_CATALOGUE.read_text())

        assert len(rows) == 85
        assert all(set(row) == {"slug", "name", "country", "lat", "lng"} for row in rows)
        for row in rows:
            data = stamp_art(row["slug"]).read_bytes()
            assert (data[:4], data[8:12]) == _WEBP_MAGIC, row["slug"]
        assert {p.stem for p in _CATALOGUE.parent.glob("*.webp")} == {r["slug"] for r in rows}

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

    def test_every_catalogued_city_is_drawable_and_on_the_city_axis(self) -> None:
        slugs = [row["slug"] for row in json.loads(_CATALOGUE.read_text())]

        assert stamp_weights() == dict.fromkeys(slugs, 1)
        assert [stamp["id"] for stamp in city_axis()] == slugs

    @pytest.mark.parametrize("slug", ["atlantis", "../cities", "tokyo/../paris"])
    def test_a_slug_off_the_catalogue_has_no_art(self, slug: str) -> None:
        with pytest.raises(KeyError):
            stamp_art(slug)

    def test_an_unknown_city_fails_loud(self) -> None:
        with pytest.raises(KeyError):
            stamp_for("atlantis")
