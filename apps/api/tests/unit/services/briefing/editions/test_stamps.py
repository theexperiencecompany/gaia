"""The Air Mail city stamps: catalogue, derived stamp furniture, asset."""

import pytest

from app.services.briefing.editions.stamps import (
    STAMP_CITY_WEIGHTS,
    stamp_asset_uri,
    stamp_for,
)


@pytest.mark.unit
class TestStamps:
    def test_all_85_cities_are_drawable_once_per_pass(self) -> None:
        assert len(STAMP_CITY_WEIGHTS) == 85
        assert set(STAMP_CITY_WEIGHTS.values()) == {1}

    def test_the_stamp_text_is_derived_from_its_city(self) -> None:
        stamp = stamp_for("paris")

        assert stamp["id"] == "paris"
        assert stamp["src"] == "STAMP_CITY"
        assert stamp["city"] == "PARIS"
        assert stamp["denom"] == "€1,96"
        assert stamp["air"] == "Par Avion"

    def test_cities_in_one_country_share_its_postage(self) -> None:
        assert stamp_for("tokyo")["denom"] == stamp_for("osaka")["denom"] == "¥110"

    @pytest.mark.parametrize("slug", sorted(STAMP_CITY_WEIGHTS))
    def test_every_city_has_a_small_webp(self, slug: str) -> None:
        uri = stamp_asset_uri(slug)

        assert uri.startswith("data:image/webp;base64,")
        assert len(uri) < 400_000

    def test_an_unknown_city_fails_loud(self) -> None:
        with pytest.raises(KeyError):
            stamp_for("atlantis")
