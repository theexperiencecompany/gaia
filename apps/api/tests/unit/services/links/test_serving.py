"""The content origin's header table: each render mode gets exactly its headers, and HTML and SVG never land top-level."""

import pytest

from app.config.settings import settings
from app.models.short_link_models import LinkSnapshot, RenderMode
from app.services.links.serving import download_response, snapshot_response, thumbnail_response

LINK = "https://heygaia.link/abcdefghijk"
SHARED = {
    "x-content-type-options": "nosniff",
    "cross-origin-resource-policy": "cross-origin",
    "cross-origin-opener-policy": "same-origin",
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex, nofollow",
}


@pytest.fixture(autouse=True)
def app_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://heygaia.io")


def _snapshot(render: RenderMode, mime: str, filename: str = "report.html") -> LinkSnapshot:
    return LinkSnapshot(
        filename=filename, mime=mime, size_bytes=4, render=render, content_id="a" * 26
    )


def _assert_shared(headers: dict[str, str]) -> None:
    for name, value in SHARED.items():
        assert headers[name] == value
    assert "permissions-policy" in headers
    assert "camera=()" in headers["permissions-policy"]
    assert not any(name.startswith("access-control-allow") for name in headers)
    assert "set-cookie" not in headers


class TestActiveHtml:
    def test_inside_an_iframe_it_runs_with_no_network_write_path(self) -> None:
        response = snapshot_response(
            b"<p>", _snapshot(RenderMode.FRAME_ACTIVE, "text/html"), "iframe", LINK
        )
        headers = dict(response.headers)

        _assert_shared(headers)
        assert response.status_code == 200
        assert headers["content-type"] == "text/html; charset=utf-8"
        assert headers["content-disposition"] == "inline"
        csp = headers["content-security-policy"]
        assert csp.startswith("sandbox allow-scripts allow-forms allow-modals allow-popups ")
        assert "allow-same-origin" not in csp
        assert "allow-top-navigation" not in csp
        for directive in (
            "connect-src 'none'",
            "form-action 'none'",
            "base-uri 'none'",
            "frame-src 'none'",
            "worker-src 'none'",
            "frame-ancestors https://heygaia.io",
        ):
            assert directive in csp
        assert headers["cache-control"] == "private, max-age=600"

    @pytest.mark.parametrize("dest", ["document", None, "image", "embed", "object", ""])
    def test_anywhere_else_it_goes_back_to_the_link(self, dest: str | None) -> None:
        response = snapshot_response(
            b"<p>", _snapshot(RenderMode.FRAME_ACTIVE, "text/html"), dest, LINK
        )
        assert response.status_code == 302
        assert response.headers["location"] == LINK
        assert response.body == b""


class TestSvg:
    def test_inside_an_img_it_renders_inline(self) -> None:
        response = snapshot_response(
            b"<svg>", _snapshot(RenderMode.IMAGE_SVG, "image/svg+xml", "logo.svg"), "image", LINK
        )
        headers = dict(response.headers)
        _assert_shared(headers)
        assert headers["content-type"] == "image/svg+xml"
        assert headers["content-disposition"] == "inline"
        assert (
            headers["content-security-policy"]
            == "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        )

    @pytest.mark.parametrize("dest", ["document", "iframe", None])
    def test_anywhere_else_it_downloads(self, dest: str | None) -> None:
        response = snapshot_response(
            b"<svg>", _snapshot(RenderMode.IMAGE_SVG, "image/svg+xml", "logo.svg"), dest, LINK
        )
        assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''logo.svg"


def test_a_pdf_renders_in_the_browser_viewer_framed_only_by_the_app() -> None:
    response = snapshot_response(
        b"%PDF", _snapshot(RenderMode.PDF, "application/pdf", "d.pdf"), "iframe", LINK
    )
    headers = dict(response.headers)
    _assert_shared(headers)
    assert headers["content-type"] == "application/pdf"
    assert headers["content-disposition"] == "inline"
    assert headers["content-security-policy"] == (
        "default-src 'none'; object-src 'self'; frame-ancestors https://heygaia.io"
    )


@pytest.mark.parametrize(
    ("render", "mime", "content_type"),
    [
        (RenderMode.IMAGE, "image/png", "image/png"),
        (RenderMode.MEDIA, "video/mp4", "video/mp4"),
        (RenderMode.TEXT, "text/markdown", "text/plain; charset=utf-8"),
    ],
)
def test_inert_types_render_inline_in_a_sandbox(
    render: RenderMode, mime: str, content_type: str
) -> None:
    response = snapshot_response(b"data", _snapshot(render, mime), "document", LINK)
    headers = dict(response.headers)
    _assert_shared(headers)
    assert headers["content-type"] == content_type
    assert headers["content-disposition"] == "inline"
    assert headers["content-security-policy"] == "default-src 'none'; sandbox"


def test_a_download_is_opaque_bytes_with_an_encoded_name() -> None:
    snapshot = _snapshot(RenderMode.DOWNLOAD, "application/octet-stream", 'résumé "x".zip')
    headers = dict(download_response(b"PK", snapshot).headers)
    _assert_shared(headers)
    assert headers["content-type"] == "application/octet-stream"
    assert (
        headers["content-disposition"]
        == "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9%20%22x%22.zip"
    )
    assert headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert headers["cache-control"] == "private, no-store"


def test_a_download_of_html_never_renders() -> None:
    headers = dict(
        download_response(b"<script>", _snapshot(RenderMode.FRAME_ACTIVE, "text/html")).headers
    )
    assert headers["content-type"] == "application/octet-stream"
    assert headers["content-disposition"].startswith("attachment;")


def test_a_preview_image_is_publicly_cacheable() -> None:
    headers = dict(thumbnail_response(b"jpg").headers)
    _assert_shared(headers)
    assert headers["content-type"] == "image/jpeg"
    assert headers["cache-control"] == "public, max-age=3600"
