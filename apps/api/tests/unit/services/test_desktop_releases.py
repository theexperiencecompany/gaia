"""Resolving the newest desktop release, and what the download page is told when it fails.

The envelope's why is shown to the person trying to download GAIA, so it says
what they can act on; the transport error that actually happened is wide-event
context and stays off the wire.
"""

from unittest.mock import patch

import httpx
import pytest

from app.services.desktop import releases as releases_module
from app.utils.errors import AppError

pytestmark = pytest.mark.unit

_RELEASE = {
    "tag_name": "desktop-v1.2.3",
    "name": "Desktop 1.2.3",
    "html_url": "https://github.com/x/releases/desktop-v1.2.3",
    "published_at": "2026-01-02T03:04:05Z",
    "assets": [
        {
            "name": "GAIA.dmg",
            "browser_download_url": "https://example.test/GAIA.dmg",
            "size": 42,
            "content_type": "application/octet-stream",
        }
    ],
}


def _github(handler: httpx.MockTransport):
    """Drive the real client against a stubbed GitHub, with the cache out of the way."""
    real_client = httpx.AsyncClient

    def build(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=handler, base_url="https://api.github.com")

    return patch.object(releases_module.httpx, "AsyncClient", build)


async def _resolve():
    return await releases_module.get_latest_desktop_release.__wrapped__()


async def test_the_newest_desktop_tag_and_its_assets_are_returned() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json=[{"tag_name": "api-v9"}, _RELEASE, {"tag_name": "desktop-v1.0.0"}]
        )
    )
    with _github(transport):
        release = await _resolve()

    assert release.tag == "desktop-v1.2.3"
    assert [asset.name for asset in release.assets] == ["GAIA.dmg"]


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
async def test_an_unpublished_release_is_not_offered_for_download(flag: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=[{**_RELEASE, flag: True}])
    )
    with _github(transport), pytest.raises(AppError) as exc:
        await _resolve()

    assert exc.value.status_code == 404


async def test_no_desktop_tag_at_all_is_a_404() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[{"tag_name": "api"}]))
    with _github(transport), pytest.raises(AppError) as exc:
        await _resolve()

    assert exc.value.status_code == 404
    assert exc.value.message == "No published desktop release was found"


async def test_an_unreachable_github_keeps_its_error_off_the_download_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with _github(httpx.MockTransport(handler)), pytest.raises(AppError) as exc:
        await _resolve()

    error = exc.value
    assert error.status_code == 502
    assert error.why == "GitHub's releases API did not answer"
    assert error.public == {}
    assert error.meta == {"error_type": "ConnectTimeout", "error": "timed out"}


async def test_a_github_error_status_is_the_same_unreachable_answer() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    with _github(transport), pytest.raises(AppError) as exc:
        await _resolve()

    assert exc.value.status_code == 502
    assert exc.value.meta["error_type"] == "HTTPStatusError"
