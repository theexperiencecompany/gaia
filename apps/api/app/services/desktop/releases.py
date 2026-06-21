"""Resolve the latest published GAIA desktop release from GitHub Releases.

Every app in the monorepo publishes into one GitHub Releases feed, so the newest
``desktop-*`` tag is usually buried several entries below the most recent web/api
releases. The web download page calls this (cached) so its buttons can link
straight to the right platform binary instead of dumping users on the raw GitHub
releases list.
"""

import httpx

from app.agents.skills.utils import GITHUB_API_BASE, get_github_headers
from app.constants.cache import DESKTOP_RELEASE_CACHE_KEY, DESKTOP_RELEASE_CACHE_TTL
from app.constants.desktop import (
    DESKTOP_RELEASE_TAG_PREFIX,
    DESKTOP_RELEASES_PAGE_SIZE,
    GAIA_GITHUB_REPO,
    GITHUB_RELEASES_TIMEOUT_SECONDS,
)
from app.decorators.caching import Cacheable
from app.schemas.desktop_schemas import DesktopReleaseAsset, DesktopReleaseResponse
from app.utils.errors import create_error
from shared.py.wide_events import log


@Cacheable(
    key=DESKTOP_RELEASE_CACHE_KEY,
    ttl=DESKTOP_RELEASE_CACHE_TTL,
    model=DesktopReleaseResponse,
)
async def get_latest_desktop_release() -> DesktopReleaseResponse:
    """Return the newest non-draft ``desktop-*`` release and its assets.

    Raises ``AppError`` 502 if GitHub is unreachable, or 404 if no desktop
    release has been published yet.
    """
    url = f"{GITHUB_API_BASE}/repos/{GAIA_GITHUB_REPO}/releases"

    try:
        async with httpx.AsyncClient(timeout=GITHUB_RELEASES_TIMEOUT_SECONDS) as client:
            response = await client.get(
                url,
                params={"per_page": DESKTOP_RELEASES_PAGE_SIZE},
                headers=get_github_headers(),
            )
            response.raise_for_status()
            releases = response.json()
    except httpx.HTTPError as exc:
        raise create_error(
            message="Could not reach GitHub to resolve the latest desktop release",
            why=str(exc),
            fix="Retry shortly; the download page falls back to the GitHub releases list",
            status_code=502,
        ) from exc

    latest = next(
        (
            release
            for release in releases
            if release.get("tag_name", "").startswith(DESKTOP_RELEASE_TAG_PREFIX)
            and not release.get("draft")
            and not release.get("prerelease")
        ),
        None,
    )

    if latest is None:
        raise create_error(
            message="No published desktop release was found",
            why=(
                f"No '{DESKTOP_RELEASE_TAG_PREFIX}*' tag in the "
                f"{DESKTOP_RELEASES_PAGE_SIZE} most recent releases"
            ),
            status_code=404,
        )

    assets = [
        DesktopReleaseAsset(
            name=asset["name"],
            download_url=asset["browser_download_url"],
            size=asset.get("size", 0),
            content_type=asset.get("content_type"),
        )
        for asset in latest.get("assets", [])
    ]

    log.set(desktop_release={"tag": latest["tag_name"], "asset_count": len(assets)})

    return DesktopReleaseResponse(
        tag=latest["tag_name"],
        name=latest.get("name"),
        html_url=latest["html_url"],
        published_at=latest.get("published_at"),
        assets=assets,
    )
