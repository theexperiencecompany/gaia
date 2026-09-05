"""Plumbing shared by every edition renderer — font embedding and date
formatting are identical regardless of which family's markup wraps them."""

import base64
from datetime import date
from html import escape
from pathlib import Path

# The raster viewport every edition targets; each renderer's page is exactly
# this width.
CANVAS_PX = 1180

FONTS_DIR = Path(__file__).parent / "fonts"


def font_face(family: str, filename: str, weight: int) -> str:
    """Build one ``@font-face`` rule with the woff2 embedded as a data URI."""
    # codecs.lookup normalises the codec name, so "ascii" and "ASCII" select the
    # same decoder — that mutation is unobservable, hence the pragma.
    encoded = base64.b64encode((FONTS_DIR / filename).read_bytes()).decode(  # pragma: no mutate
        "ascii"
    )
    return (
        f"@font-face{{font-family:'{family}';font-style:normal;"
        f"font-weight:{weight};font-display:block;"
        f"src:url(data:font/woff2;base64,{encoded}) format('woff2');}}"
    )


def format_date(iso: str) -> str:
    """Format an ISO ``YYYY-MM-DD`` date as ``July 5, 2026``.

    An unparseable value is escaped and returned verbatim so the dateline is
    never silently dropped.
    """
    try:
        parsed = date.fromisoformat(iso)
    except ValueError:
        return escape(iso)
    return f"{parsed:%B} {parsed.day}, {parsed.year}"
