"""Share-download flow: real app on a real socket, Composio's real fetcher.

Proves the composition no mock can: mint a grant against a seeded workspace,
serve the app with uvicorn, and fetch with Composio's actual
``_fetch_file_from_url`` over real HTTP — filename, bytes, and mimetype must
all survive. Hermetic (localhost socket, fake mount, stubbed secret).
"""

from pathlib import Path
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request as FastAPIRequest, Response
import pytest
import uvicorn


def _serve(app: FastAPI) -> tuple[uvicorn.Server, threading.Thread, int]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start in time"
    return server, thread, port


@pytest.fixture
def _workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Fake JuiceFS mount with one seeded file (the `mount` lie, hermetic)."""
    from app.config.settings import settings

    user_dir = tmp_path / "users" / "u1"
    user_dir.mkdir(parents=True)
    (user_dir / "report.pdf").write_bytes(b"%PDF-1.4 composition")
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(tmp_path))
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
    # Long enough for the 32-char floor, but plain words: a high-entropy literal
    # here reads as a real credential to the secret scanner.
    monkeypatch.setattr(settings, "SHARE_GRANT_SECRET", "not-a-real-secret-only-for-this-test")
    return tmp_path


def test_share_url_survives_real_fetch(
    test_app: FastAPI, _workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from composio.core.models._files import _fetch_file_from_url

    from app.services.share_service import mint_share_url

    url = mint_share_url(
        user_id="u1",
        workspace_path="/workspace/report.pdf",
        tool="OUTLOOK_SEND_EMAIL",
        toolkit="outlook",
    )
    token = parse_qs(urlsplit(url).query)["token"][0]

    server, thread, port = _serve(test_app)
    try:
        local = f"http://127.0.0.1:{port}/api/v1/files/s/report.pdf?token={token}"
        filename, content, mimetype = asyncio.run(asyncio.to_thread(_fetch_file_from_url, local))
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert filename == "report.pdf"
    assert content == b"%PDF-1.4 composition"
    assert mimetype == "application/pdf"


async def test_auth_middleware_excludes_share_downloads() -> None:
    """The token IS the credential: excluded paths reach the handler sessionless.

    The middleware itself never 401s (route dependencies enforce); what the
    exclusion buys is skipping session parsing/dev-bypass entirely, so an
    unauthenticated Composio fetch is never mistaken for a user request.
    """
    from app.api.v1.middleware.auth import WorkOSAuthMiddleware

    async def _handler(request: FastAPIRequest) -> Response:
        return Response("served")

    middleware = WorkOSAuthMiddleware(app=None)  # type: ignore[arg-type]  # only the path-exclusion check runs; no downstream app is dispatched to

    def _request(path: str) -> FastAPIRequest:
        return FastAPIRequest({"type": "http", "method": "GET", "path": path, "headers": []})

    response = await middleware.dispatch(_request("/api/v1/files/s/report.pdf"), _handler)
    assert response.status_code == 200

    # Only the share subtree is open — nothing else under /files rides along.
    assert not any("/api/v1/files/top-secret".startswith(path) for path in middleware.exclude_paths)
