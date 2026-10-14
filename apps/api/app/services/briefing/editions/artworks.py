"""The public-domain paintings an edition hangs (explorer/assets/assets.json).

Every one is a Metropolitan Museum of Art Open Access image. The edition number picks
the painting, so consecutive editions hang different ones and a re-render of the
same edition hangs the same one.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Artwork:
    """One painting: its asset key in assets.json and its catalogue line."""

    asset_key: str
    title: str
    artist: str
    year: str
    medium: str


ARTWORKS: tuple[Artwork, ...] = (
    Artwork("ART1", "Wheat Field with Cypresses", "Vincent van Gogh", "1889", "oil on canvas"),
    Artwork(
        "STAMP_TOKYO",
        "Under the Wave off Kanagawa",
        "Katsushika Hokusai",
        "ca. 1830–32",
        "woodblock print",
    ),
    Artwork("STAMP_LONDON", "Whalers", "J. M. W. Turner", "ca. 1845", "oil on canvas"),
    Artwork(
        "STAMP_PARIS",
        "The Boulevard Montmartre on a Winter Morning",
        "Camille Pissarro",
        "1897",
        "oil on canvas",
    ),
    Artwork("STAMP_VENICE", "Piazza San Marco", "Canaletto", "late 1720s", "oil on canvas"),
)


def artwork_for(edition_no: int) -> Artwork:
    """Return the painting the edition hangs; the pool rotates one step per edition."""
    return ARTWORKS[edition_no % len(ARTWORKS)]
