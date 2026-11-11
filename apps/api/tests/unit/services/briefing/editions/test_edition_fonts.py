"""Unit tests for the edition webfont manifest and its @font-face rules."""

import base64
from pathlib import Path
import re

import pytest

from app.services.briefing.editions.edition_fonts import (
    EDITION_FAMILIES,
    edition_font_faces_css,
    font_faces,
)
from app.services.briefing.editions.explorer_render import explorer_family_ids

_FONTS_DIR = Path(__file__).parents[5] / "app" / "services" / "briefing" / "editions" / "fonts"


@pytest.mark.unit
class TestManifest:
    def test_every_edition_family_names_its_fonts(self) -> None:
        assert set(EDITION_FAMILIES) == set(explorer_family_ids())

    def test_every_named_family_is_built(self) -> None:
        built = {face.family for face in font_faces()}

        for edition, families in EDITION_FAMILIES.items():
            assert set(families) <= built, f"{edition} names a family with no font file"

    def test_every_built_family_is_used_by_an_edition(self) -> None:
        used = {name for families in EDITION_FAMILIES.values() for name in families}

        assert {face.family for face in font_faces()} == used

    def test_the_manifest_lists_exactly_the_woff2_files_on_disk(self) -> None:
        assert {face.file for face in font_faces()} == {
            path.name for path in _FONTS_DIR.glob("*.woff2")
        }

    def test_no_family_declares_the_same_cut_twice(self) -> None:
        cuts = [(f.family, f.weight, f.style) for f in font_faces()]

        assert len(cuts) == len(set(cuts))


@pytest.mark.unit
class TestFontFacesCss:
    def test_each_cut_of_each_family_is_one_rule(self) -> None:
        css = edition_font_faces_css("broadsheet")
        rules = re.findall(
            r"@font-face\{font-family:'([^']+)';font-style:(\w+);font-weight:(\d+)", css
        )

        assert rules == [
            ("Broadsheet Caslon", "normal", "400"),
            ("Broadsheet Caslon", "normal", "700"),
            ("Broadsheet Caslon", "italic", "400"),
            ("Source Serif 4", "normal", "400"),
            ("Source Serif 4", "normal", "700"),
            ("Source Serif 4", "italic", "400"),
            ("Source Serif 4", "italic", "500"),
            ("Source Serif 4", "italic", "600"),
        ]

    def test_the_data_uri_is_the_file_on_disk(self) -> None:
        css = edition_font_faces_css("receipt")
        uris = re.findall(r"data:font/woff2;base64,([A-Za-z0-9+/=]+)", css)

        assert [base64.b64decode(uri) for uri in uris] == [
            (_FONTS_DIR / name).read_bytes()
            for name in (
                "jetbrains-mono-400.woff2",
                "jetbrains-mono-600.woff2",
                "jetbrains-mono-700.woff2",
            )
        ]

    def test_an_unknown_family_fails_loud(self) -> None:
        with pytest.raises(KeyError):
            edition_font_faces_css("nope")
