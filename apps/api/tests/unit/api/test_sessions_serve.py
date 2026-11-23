"""Content-type handling in the session artifact/upload server (sandboxed_file_response).

Regression fence for the stored-XSS fix: script-capable artifact types must be
served with a sandbox CSP *and* forced to download, while known-safe media may
render inline. A future edit that lets an active type render inline on the API
origin (which holds the session cookie) must fail here.
"""

from collections.abc import Callable
from pathlib import Path

from fastapi.responses import FileResponse
import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app.utils.sandboxed_file_response import sandboxed_file_response


def _cd(response: FileResponse) -> str:
    return response.headers.get("content-disposition", "")


@pytest.fixture
def artifact_file(tmp_path: Path) -> Callable[[str], Path]:
    def _make(name: str) -> Path:
        p = tmp_path / name
        p.write_bytes(b"<svg>x</svg>")
        return p

    return _make


# Script-capable types: sandbox CSP + forced download.
ACTIVE_CASES = [
    ("report.html", "text/html"),
    ("diagram.svg", "image/svg+xml"),
    ("data.xml", "application/xml"),
]

# Known-safe media: rendered inline, no forced download, no CSP.
INLINE_CASES = [
    ("photo.png", "image/png"),
    ("scan.jpg", "image/jpeg"),
    ("doc.pdf", "application/pdf"),
]


@pytest.mark.parametrize(("name", "content_type"), ACTIVE_CASES)
def test_active_types_are_sandboxed_and_downloaded(
    artifact_file: Callable[[str], Path], name: str, content_type: str
) -> None:
    response = sandboxed_file_response(artifact_file(name), cache_control="private, max-age=60")

    assert response.media_type == content_type
    assert response.headers.get("content-security-policy") == "sandbox"
    assert _cd(response).split(";")[0].strip() == "attachment"
    assert response.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.parametrize(("name", "content_type"), INLINE_CASES)
def test_safe_media_renders_inline(
    artifact_file: Callable[[str], Path], name: str, content_type: str
) -> None:
    response = sandboxed_file_response(artifact_file(name), cache_control="private, max-age=60")

    assert response.media_type == content_type
    assert "content-security-policy" not in response.headers
    # Inline: no attachment disposition so <img>/<iframe src> can render it.
    assert "attachment" not in _cd(response)
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_unknown_type_is_forced_to_download(artifact_file: Callable[[str], Path]) -> None:
    # Anything not on the safe-inline allowlist (here: octet-stream) is
    # downloaded, never rendered.
    response = sandboxed_file_response(
        artifact_file("mystery.bin"), cache_control="private, max-age=60"
    )

    assert response.media_type == "application/octet-stream"
    assert _cd(response).split(";")[0].strip() == "attachment"


def test_plain_text_is_downloaded_not_inlined(artifact_file: Callable[[str], Path]) -> None:
    # text/plain is not on the safe-inline allowlist, so it must download.
    response = sandboxed_file_response(
        artifact_file("notes.txt"), cache_control="private, max-age=60"
    )

    assert response.media_type == "text/plain"
    assert _cd(response).split(";")[0].strip() == "attachment"


def test_malicious_filename_cannot_break_the_attachment_header(
    artifact_file: Callable[[str], Path],
) -> None:
    # An agent-chosen name with a quote must not close the quoted-string and
    # neuter the attachment disposition — FileResponse RFC-encodes it.
    response = sandboxed_file_response(artifact_file('a".svg'), cache_control="private, max-age=60")

    cd = _cd(response)
    assert cd.split(";")[0].strip() == "attachment"
    # The bare quote is percent-encoded, not emitted raw inside filename="...".
    assert '"a".svg"' not in cd
    assert "%22" in cd


async def _served(response: FileResponse) -> httpx.Response:
    """Send the response over a real ASGI exchange, the way a browser receives it."""
    app = Starlette(routes=[Route("/", lambda _request: response)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/")


async def test_the_served_bytes_are_the_files_own(artifact_file: Callable[[str], Path]) -> None:
    served = await _served(
        sandboxed_file_response(artifact_file("photo.png"), cache_control="private, max-age=60")
    )

    assert served.status_code == 200
    assert served.content == b"<svg>x</svg>"
    assert served.headers["cache-control"] == "private, max-age=60"


async def test_our_content_type_table_wins_over_the_servers_guess(
    artifact_file: Callable[[str], Path],
) -> None:
    """A .toml is text the agent wrote; the server's own guess would call it opaque bytes."""
    served = await _served(
        sandboxed_file_response(artifact_file("config.toml"), cache_control="no-store")
    )

    assert served.headers["content-type"].split(";")[0] == "text/plain"


async def test_an_unrecognised_extension_is_served_as_opaque_bytes(
    artifact_file: Callable[[str], Path],
) -> None:
    """A type our table does not know is never left to the server's own guess (text/plain)."""
    served = await _served(
        sandboxed_file_response(artifact_file("payload.zzz"), cache_control="no-store")
    )

    assert served.headers["content-type"] == "application/octet-stream"
    assert served.headers["content-disposition"].split(";")[0] == "attachment"
