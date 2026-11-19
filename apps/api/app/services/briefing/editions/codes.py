"""The machine-readable codes an edition prints, each encoding the brief's link.

Geometry is computed here from maintained encoders (segno for QR, python-barcode
for Code 128, pdf417gen for PDF417); the vendored templates only draw it, through
EXPLORER.code in explorer_render.py.
"""

from enum import StrEnum
from typing import TypedDict

from barcode import Code128
import pdf417gen
import segno

# M recovers ~15% of the symbol: room for the paper grain printed over the Invoice's QR.
_QR_ERROR_LEVEL = "m"
_DARK = "1"


class Symbology(StrEnum):
    """A barcode symbology an edition family prints."""

    QR = "qr"
    CODE128 = "code128"
    PDF417 = "pdf417"


class CodeGeometry(TypedDict):
    """One code as dark modules on a width x height module grid, as an SVG path."""

    width: int
    height: int
    path: str


# The codes each family prints; the Boarding Pass's skin picks one of its two.
FAMILY_SYMBOLOGIES: dict[str, tuple[Symbology, ...]] = {
    "invoice": (Symbology.QR,),
    "receipt": (Symbology.CODE128,),
    "boardingpass": (Symbology.CODE128, Symbology.PDF417),
}


def _geometry(rows: list[str]) -> CodeGeometry:
    """Trace each row's runs of dark modules into one path of unit-high rectangles."""
    path: list[str] = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if row[x] != _DARK:
                x += 1
                continue
            run = len(row[x:]) - len(row[x:].lstrip(_DARK))
            path.append(f"M{x} {y}h{run}v1h-{run}z")
            x += run
    return {"width": len(rows[0]), "height": len(rows), "path": "".join(path)}


def _qr_rows(link: str) -> list[str]:
    qr = segno.make_qr(link, error=_QR_ERROR_LEVEL)
    return ["".join(_DARK if dark else "0" for dark in row) for row in qr.matrix_iter(border=0)]


def _pdf417_rows(link: str) -> list[str]:
    # pdf417gen is untyped: each row is a list of codeword bit patterns. Its defaults, six
    # data columns and security level 2, suit the Boarding Pass's stacked strip.
    codes: list[list[int]] = pdf417gen.encode(link)
    return ["".join(format(word, "b") for word in row) for row in codes]


def code_geometry(symbology: Symbology, link: str) -> CodeGeometry:
    """Encode link in symbology and return the modules to draw."""
    if symbology is Symbology.QR:
        return _geometry(_qr_rows(link))
    if symbology is Symbology.CODE128:
        return _geometry(Code128(link).build())
    return _geometry(_pdf417_rows(link))


def family_codes(family: str, link: str | None) -> dict[Symbology, CodeGeometry]:
    """Return every code the family prints, keyed by symbology, each encoding link.

    Raises ValueError when the family prints a code and the brief has no link yet.
    """
    symbologies = FAMILY_SYMBOLOGIES.get(family, ())
    if not symbologies:
        return {}
    if link is None:
        raise ValueError(f"the {family} edition prints the brief's link but the brief has none")
    return {s: code_geometry(s, link) for s in symbologies}
