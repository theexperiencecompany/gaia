"""Stream a public URL to bytes, under an SSRF guard and a hard size cap.

The download counterpart to ``webpage_fetch``: that renders an HTML page to text,
this pulls a file (image, PDF, dataset) down so the agent can ``read`` it back
from the workspace. Both walk redirects through ``url_safety`` so a public URL
can't bounce to an internal address mid-chain — the difference is this path
streams to a byte budget instead of buffering a body to convert.
"""

from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from app.constants.download import (
    DOWNLOAD_TIMEOUT_SECONDS,
    DOWNLOAD_TOO_LARGE,
    DOWNLOAD_USER_AGENT,
    MAX_DOWNLOAD_BYTES,
)
from app.utils.url_safety import open_public_http_url


class DownloadError(ValueError):
    """A URL that can't be fetched: blocked by SSRF policy, too large, or a bad response."""


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    data: bytes
    content_type: str | None


def _content_type(response: httpx.Response) -> str | None:
    raw: str | None = response.headers.get("content-type")
    return raw.split(";", 1)[0].strip().lower() if raw else None


async def download_public_url(url: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> DownloadedFile:
    """Fetch ``url`` to bytes. Raises ``DownloadError`` on any refusal or failure.

    The body streams under ``max_bytes`` and the server's ``Content-Length`` is
    never trusted — a lying or chunked response is cut off the moment it crosses
    the cap. Redirects are walked by ``open_public_http_url``, which re-checks the
    SSRF policy before every hop.
    """
    headers = {"User-Agent": DOWNLOAD_USER_AGENT}
    async with httpx.AsyncClient(
        timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=False, headers=headers
    ) as client:
        try:
            async with open_public_http_url(url, lambda hop: client.stream("GET", hop)) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise DownloadError(
                        f"server returned {response.status_code} for {response.url}"
                    ) from exc
                data = await _read_capped(response, max_bytes, url)
                return DownloadedFile(data=data, content_type=_content_type(response))
        except DownloadError:
            raise  # DownloadError is a ValueError; don't re-wrap our own refusals
        except ValueError as exc:
            raise DownloadError(str(exc)) from exc
        except httpx.RequestError as exc:
            raise DownloadError(f"network error fetching {url}: {exc}") from exc


async def _read_capped(response: httpx.Response, max_bytes: int, url: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise DownloadError(
                DOWNLOAD_TOO_LARGE.format(url=url, limit_mb=max_bytes // (1024 * 1024))
            )
        chunks.append(chunk)
    return b"".join(chunks)


def download_filename(url: str, ext: str) -> str:
    """A stable, collision-resistant on-disk name for a URL's download.

    Keyed on the URL so re-downloading is idempotent (same name, last-writer-wins)
    and the path stays constant across turns. The hash also strips any hostile
    path components — the model never influences the on-disk name directly.
    """
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"download-{digest}{ext}"


def extension_from_url(url: str) -> str:
    """A real file extension named in the URL path, or ``""`` if there isn't one."""
    suffix = PurePosixPath(urlparse(url).path).suffix.lower()
    # A short alnum suffix is a real file extension (.png, .pdf, .tar); a long or
    # symbol-laden one is almost certainly a path segment that merely contains a
    # dot, so ignore it rather than bake garbage into the filename.
    return suffix if suffix and suffix[1:].isalnum() and len(suffix) <= 6 else ""


def extension_from_content_type(content_type: str | None) -> str:
    """A file extension for a response's content type, or ``""`` if unknown."""
    if not content_type:
        return ""
    return mimetypes.guess_extension(content_type) or ""
