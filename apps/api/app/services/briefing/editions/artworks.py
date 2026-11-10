"""The public-domain artworks the Exhibition, Broadsheet and Almanac hang.

Every one is a Metropolitan Museum of Art Open Access image (CC0), hosted on Cloudinary
by scripts/upload_briefing_art.py and catalogued in explorer/assets/artworks/artworks.json
with the families whose frame it fits. A brief draws its artwork from the user's shuffle
bag and records it on the payload, so a re-render hangs the same one.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.constants.briefing import EXPLORER_SCALE, ArtFamily

ARTWORKS_JSON = Path(__file__).parent / "explorer" / "assets" / "artworks" / "artworks.json"


@dataclass(frozen=True)
class ArtFrame:
    """The box a family's template crops its painting to (object-fit: cover), in CSS px."""

    width_css: int
    height_css: int
    #: The painting's width/height range the frame crops without losing its subject.
    min_aspect: float
    max_aspect: float

    @property
    def min_size_px(self) -> tuple[int, int]:
        """Return the pixel size the painting must cover to never upscale in the export."""
        return self.width_css * EXPLORER_SCALE, self.height_css * EXPLORER_SCALE

    def fits(self, width_px: int, height_px: int) -> bool:
        """Return whether an image of this size crops well and never upscales in this frame."""
        min_width, min_height = self.min_size_px
        aspect = width_px / height_px
        return (
            self.min_aspect <= aspect <= self.max_aspect
            and width_px >= min_width
            and height_px >= min_height
        )


# tpl-image.js: 540x360 scaled 1.12; tpl-broadsheet.js: 112% of the 488px column x 250;
# tpl-print.js: 300px figure less its 6px padding and 3px border, x 200.
ART_FRAMES: dict[ArtFamily, ArtFrame] = {
    ArtFamily.EXHIBITION: ArtFrame(605, 403, min_aspect=1.12, max_aspect=1.85),
    ArtFamily.BROADSHEET: ArtFrame(547, 250, min_aspect=1.25, max_aspect=3.0),
    ArtFamily.ALMANAC: ArtFrame(282, 200, min_aspect=1.12, max_aspect=1.9),
}


class Artwork(BaseModel):
    """One catalogued work: its Met record, its caption line and its hosted image."""

    model_config = ConfigDict(frozen=True)

    slug: str
    met_object_id: int
    title: str
    artist: str
    date: str
    #: As the caption reads it ("engraved for this edition after the oil on canvas").
    medium: str
    source_url: str
    families: frozenset[ArtFamily]
    url: str
    width: int
    height: int


@lru_cache(maxsize=1)
def artwork_catalogue() -> dict[str, Artwork]:
    """Return every catalogued artwork keyed by slug."""
    rows = TypeAdapter(list[Artwork]).validate_json(ARTWORKS_JSON.read_text())
    return {row.slug: row for row in rows}


def artwork_weights() -> dict[str, int]:
    """Return the user's artwork bag: every catalogued work once per pass."""
    return dict.fromkeys(artwork_catalogue(), 1)


def artworks_for(family: ArtFamily) -> frozenset[str]:
    """Return the works whose image fits the family's frame."""
    return frozenset(slug for slug, work in artwork_catalogue().items() if family in work.families)
