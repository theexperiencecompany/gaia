"""Content-type handling in the session artifact/upload server (``_serve``).

Regression fence for the stored-XSS fix: script-capable artifact types must be
served with a sandbox CSP *and* forced to download, while known-safe media may
render inline. A future edit that lets an active type render inline on the API
origin (which holds the session cookie) must fail here.
"""

from collections.abc import Callable
from pathlib import Path

from fastapi.responses import FileResponse
import pytest

from app.api.v1.endpoints.sessions import _serve


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
    response = _serve(artifact_file(name), is_artifact=True, filename=name)

    assert response.media_type == content_type
    assert response.headers.get("content-security-policy") == "sandbox"
    assert _cd(response).split(";")[0].strip() == "attachment"
    assert response.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.parametrize(("name", "content_type"), INLINE_CASES)
def test_safe_media_renders_inline(
    artifact_file: Callable[[str], Path], name: str, content_type: str
) -> None:
    response = _serve(artifact_file(name), is_artifact=True, filename=name)

    assert response.media_type == content_type
    assert "content-security-policy" not in response.headers
    # Inline: no attachment disposition so <img>/<iframe src> can render it.
    assert "attachment" not in _cd(response)
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_unknown_type_is_forced_to_download(artifact_file: Callable[[str], Path]) -> None:
    # Anything not on the safe-inline allowlist (here: octet-stream) is
    # downloaded, never rendered.
    response = _serve(artifact_file("mystery.bin"), is_artifact=True, filename="mystery.bin")

    assert response.media_type == "application/octet-stream"
    assert _cd(response).split(";")[0].strip() == "attachment"


def test_plain_text_is_downloaded_not_inlined(artifact_file: Callable[[str], Path]) -> None:
    # text/plain is not on the safe-inline allowlist, so it must download.
    response = _serve(artifact_file("notes.txt"), is_artifact=True, filename="notes.txt")

    assert response.media_type == "text/plain"
    assert _cd(response).split(";")[0].strip() == "attachment"


def test_malicious_filename_cannot_break_the_attachment_header(
    artifact_file: Callable[[str], Path],
) -> None:
    # An agent-chosen name with a quote must not close the quoted-string and
    # neuter the attachment disposition — FileResponse RFC-encodes it.
    evil = 'a".svg'
    response = _serve(artifact_file("real.svg"), is_artifact=True, filename=evil)

    cd = _cd(response)
    assert cd.split(";")[0].strip() == "attachment"
    # The bare quote is percent-encoded, not emitted raw inside filename="...".
    assert '"a".svg"' not in cd
    assert "%22" in cd
