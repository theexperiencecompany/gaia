"""The codes an edition prints: each symbology's modules, traced into one SVG path, each encoding the link.

Nothing is faked; the encoders are the real ones and the oracle is their own output.
"""

import re

from barcode import Code128
import pdf417gen
import pytest
import segno

from app.services.briefing.editions.codes import (
    FAMILY_SYMBOLOGIES,
    CodeGeometry,
    Symbology,
    code_geometry,
    family_codes,
)

LINK = "https://heygaia.link/brief-abc123"


def _drawn(code: CodeGeometry) -> list[str]:
    """Read the path back as the module grid it draws: 1 where a rectangle covers a module."""
    grid = [["0"] * code["width"] for _ in range(code["height"])]
    rectangles = re.findall(r"M\d+ \d+h\d+v1h-\d+z", code["path"])
    assert "".join(rectangles) == code["path"], "the path is only unit-high rectangles"
    for rectangle in rectangles:
        match = re.fullmatch(r"M(\d+) (\d+)h(\d+)v1h-(\d+)z", rectangle)
        assert match is not None and match[3] == match[4]
        x, y, run = int(match[1]), int(match[2]), int(match[3])
        for module in range(x, x + run):
            assert grid[y][module] == "0", "no module is drawn twice"
            grid[y][module] = "1"
    return ["".join(row) for row in grid]


class TestCodeGeometry:
    def test_a_qr_draws_exactly_the_modules_of_a_medium_correction_symbol(self) -> None:
        link = f"{LINK}/{'x' * 60}"
        qr = segno.make_qr(link, error="m")
        expected = ["".join("1" if dark else "0" for dark in row) for row in qr.matrix]

        code = code_geometry(Symbology.QR, link)

        assert _drawn(code) == expected
        assert (code["width"], code["height"]) == (len(expected[0]), len(expected))

    def test_a_code128_draws_exactly_the_bars_of_its_encoding(self) -> None:
        expected = Code128(LINK).build()

        code = code_geometry(Symbology.CODE128, LINK)

        assert _drawn(code) == expected
        assert (code["width"], code["height"]) == (len(expected[0]), len(expected))

    def test_a_pdf417_draws_exactly_its_six_column_codewords(self) -> None:
        codes = pdf417gen.encode(LINK, columns=6, security_level=2)
        expected = ["".join(format(word, "b") for word in row) for row in codes]

        code = code_geometry(Symbology.PDF417, LINK)

        assert _drawn(code) == expected
        assert (code["width"], code["height"]) == (len(expected[0]), len(expected))


class TestFamilyCodes:
    @pytest.mark.parametrize("family", sorted(FAMILY_SYMBOLOGIES))
    def test_a_family_prints_each_of_its_symbologies_encoding_the_link(self, family: str) -> None:
        codes = family_codes(family, LINK)

        assert list(codes) == list(FAMILY_SYMBOLOGIES[family])
        assert all(codes[s] == code_geometry(s, LINK) for s in codes)

    def test_a_family_without_codes_prints_none_even_without_a_link(self) -> None:
        assert family_codes("memo", None) == {}

    def test_a_family_that_prints_a_code_needs_the_briefs_link(self) -> None:
        with pytest.raises(ValueError, match="the invoice edition prints the brief's link"):
            family_codes("invoice", None)
