"""The app marks an edition prints: read from logos.json, keyed by integration id."""

import json

import pytest

from app.services.briefing.editions import edition_logos
from app.services.briefing.editions.edition_logos import (
    app_logos,
    logo_css,
    logo_key,
    logo_kinds,
)

pytestmark = pytest.mark.unit

_RAW = json.loads(edition_logos._LOGOS_JSON.read_text())
_FIRST, _SECOND = sorted(_RAW)[:2]


class TestAppLogos:
    def test_every_mark_in_the_registry_file_is_read_by_its_integration_id(self) -> None:
        app_logos.cache_clear()

        logos = app_logos()

        assert set(logos) == set(_RAW)
        assert logos[_FIRST].color == _RAW[_FIRST]["color"]
        assert logos[_FIRST].mask == _RAW[_FIRST]["mask"]
        assert logos[_FIRST].kind == _RAW[_FIRST]["kind"]


class TestLogoKey:
    def test_a_registered_app_prints_its_own_mark_and_gaia_or_an_unmarked_app_none(self) -> None:
        assert logo_key(_FIRST) == _FIRST
        assert logo_key("gaia") is None
        assert logo_key(None) is None


class TestLogoCss:
    def test_each_mark_is_one_rule_in_id_order_and_a_repeat_is_painted_once(self) -> None:
        css = logo_css([_SECOND, _FIRST, _SECOND])

        assert css == (
            f'.xb-logo[data-logo="{_FIRST}"]{{--xb-mask:url("{_RAW[_FIRST]["mask"]}");'
            f'--xb-img:url("{_RAW[_FIRST]["color"]}")}}'
            f'.xb-logo[data-logo="{_SECOND}"]{{--xb-mask:url("{_RAW[_SECOND]["mask"]}");'
            f'--xb-img:url("{_RAW[_SECOND]["color"]}")}}'
        )

    def test_no_marks_are_no_css(self) -> None:
        assert logo_css([]) == ""


class TestLogoKinds:
    def test_each_mark_names_its_kind(self) -> None:
        assert logo_kinds([_SECOND, _FIRST]) == {
            _FIRST: _RAW[_FIRST]["kind"],
            _SECOND: _RAW[_SECOND]["kind"],
        }
