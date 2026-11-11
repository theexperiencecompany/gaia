"""The paintings the framed families hang: catalogue, hosting and fit to each frame."""

import json
from pathlib import Path
import re

import pytest

from app.constants.briefing import ArtFamily
from app.services.briefing.editions import artworks
from app.services.briefing.editions.artworks import (
    ART_FRAMES,
    ARTWORKS_JSON,
    artwork_catalogue,
    artwork_weights,
    artworks_for,
)

_JS_DIR = Path(artworks.__file__).parent / "explorer" / "js"
_REGISTERED_ID = re.compile(r'EXPLORER\.register\(\{\s*id:\s*"([a-z0-9-]+)"')
_HOSTED_URL = re.compile(
    r"^https://res\.cloudinary\.com/[a-z0-9]+/image/upload/briefing/artworks/(?P<slug>[a-z0-9-]+)\.webp$"
)
# Enough that a daily reader sees no repeat for months.
_MIN_WORKS_PER_FAMILY = 50


def _families_reading_the_painting() -> set[str]:
    """Return every template family whose render reads ed.art."""
    families: set[str] = set()
    for js_file in _JS_DIR.glob("tpl-*.js"):
        chunks = re.split(r"(?=EXPLORER\.register\(\{)", js_file.read_text())
        for chunk in chunks:
            registered = _REGISTERED_ID.match(chunk)
            if registered and "ed.art" in chunk:
                families.add(registered.group(1))
    return families


@pytest.mark.unit
class TestCatalogue:
    def test_the_framed_families_are_exactly_the_templates_that_hang_a_painting(self) -> None:
        assert {family.value for family in ArtFamily} == _families_reading_the_painting()

    def test_the_catalogue_is_a_large_set_of_distinct_met_works(self) -> None:
        rows = json.loads(ARTWORKS_JSON.read_text())

        assert 60 <= len(rows) <= 100
        assert len({row["slug"] for row in rows}) == len(rows)
        assert len({row["met_object_id"] for row in rows}) == len(rows)

    def test_the_catalogue_is_every_row_of_the_json_keyed_by_slug(self) -> None:
        artwork_catalogue.cache_clear()

        assert {slug: work.title for slug, work in artwork_catalogue().items()} == {
            row["slug"]: row["title"] for row in json.loads(ARTWORKS_JSON.read_text())
        }

    def test_every_work_is_hosted_at_its_own_versionless_url(self) -> None:
        for slug, work in artwork_catalogue().items():
            hosted = _HOSTED_URL.match(work.url)
            assert hosted is not None, work.url
            assert hosted.group("slug") == slug

    def test_every_work_carries_the_caption_line_and_its_met_record(self) -> None:
        for work in artwork_catalogue().values():
            assert work.title and work.artist and work.date and work.medium
            assert work.medium == work.medium.strip() and not work.medium[0].isupper()
            assert work.source_url == (
                f"https://www.metmuseum.org/art/collection/search/{work.met_object_id}"
            )

    def test_every_work_fits_each_frame_it_is_catalogued_for(self) -> None:
        for work in artwork_catalogue().values():
            assert work.families, work.slug
            for family in work.families:
                assert ART_FRAMES[family].fits(work.width, work.height), (work.slug, family)

    def test_every_hosted_image_is_no_larger_than_its_largest_frame_needs(self) -> None:
        for work in artwork_catalogue().values():
            covers = [
                work.width >= w and work.height >= h
                for w, h in (ART_FRAMES[family].min_size_px for family in work.families)
            ]
            shrunk = [
                work.width - 1 >= w and work.height - 1 >= h
                for w, h in (ART_FRAMES[family].min_size_px for family in work.families)
            ]
            assert all(covers) and not all(shrunk), work.slug

    @pytest.mark.parametrize("family", list(ArtFamily))
    def test_each_family_has_months_of_works_to_draw_from(self, family: ArtFamily) -> None:
        assert len(artworks_for(family)) >= _MIN_WORKS_PER_FAMILY


@pytest.mark.unit
class TestDrawablePool:
    def test_the_bag_holds_every_work_once(self) -> None:
        assert artwork_weights() == dict.fromkeys(artwork_catalogue(), 1)

    @pytest.mark.parametrize("family", list(ArtFamily))
    def test_a_family_is_offered_only_the_works_that_fit_its_frame(self, family: ArtFamily) -> None:
        catalogue = artwork_catalogue()

        assert artworks_for(family) == {
            slug for slug, work in catalogue.items() if family in work.families
        }

    def test_a_too_wide_work_is_offered_to_the_broadsheet_alone(self) -> None:
        screens = artwork_catalogue()["irises-yatsuhashi"]

        assert screens.families == {ArtFamily.BROADSHEET}
        assert "irises-yatsuhashi" in artworks_for(ArtFamily.BROADSHEET)
        assert "irises-yatsuhashi" not in artworks_for(ArtFamily.EXHIBITION)


@pytest.mark.unit
class TestArtFrame:
    def test_the_exhibition_frame_needs_its_scaled_box_at_the_3x_export(self) -> None:
        assert ART_FRAMES[ArtFamily.EXHIBITION].min_size_px == (1815, 1209)

    @pytest.mark.parametrize(
        ("size", "fits"),
        [
            ((1815, 1209), True),
            ((1814, 1209), False),
            ((2200, 1208), False),
            ((2200, 1210), True),
            ((3700, 1300), False),
            ((1815, 1700), False),
        ],
    )
    def test_the_exhibition_frame_takes_only_images_that_cover_it_at_a_fair_crop(
        self, size: tuple[int, int], fits: bool
    ) -> None:
        assert ART_FRAMES[ArtFamily.EXHIBITION].fits(*size) is fits
