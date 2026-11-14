"""The app marks an edition prints beside an item, as CSS a template paints in colour or in its ink.

logos.json is built from the integration-logos registry by scripts/build_edition_logos.py.
"""

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, RootModel

_LOGOS_JSON = Path(__file__).parent / "logos" / "logos.json"


class AppLogo(BaseModel):
    """One app's mark: as shipped, and as the alpha mask an edition paints in its own ink."""

    model_config = ConfigDict(frozen=True)

    #: A mono mark is one colour by brand rule, so it prints in ink even where colour is allowed.
    kind: Literal["mono", "color"]
    color: str
    mask: str


class _Logos(RootModel[dict[str, AppLogo]]):
    pass


@lru_cache(maxsize=1)
def app_logos() -> dict[str, AppLogo]:
    """Return every registered mark by integration id, read once per process."""
    return _Logos.model_validate_json(_LOGOS_JSON.read_bytes()).root


def logo_key(source: str | None) -> str | None:
    """Return the integration id whose mark an item prints; None for GAIA's own work or an unmarked app."""
    return source if source is not None and source in app_logos() else None


def logo_css(keys: Iterable[str]) -> str:
    """Return the CSS that paints each of the marks, and nothing for the rest."""
    logos = app_logos()
    return "".join(
        f'.xb-logo[data-logo="{key}"]{{--xb-mask:url("{logos[key].mask}");'
        f'--xb-img:url("{logos[key].color}")}}'
        for key in sorted(set(keys))
    )


def logo_kinds(keys: Iterable[str]) -> dict[str, str]:
    """Return each of the marks' kind, for the template to choose colour or ink."""
    logos = app_logos()
    return {key: logos[key].kind for key in sorted(set(keys))}
