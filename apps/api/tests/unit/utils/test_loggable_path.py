"""loggable_request_path must keep a heygaia.link slug out of the logs on every path."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from starlette.testclient import TestClient

from app.utils.loggable_path import loggable_request_path


def _logged_paths() -> tuple[TestClient, list[str]]:
    """Build an app that records the loggable path of every request, routed or not."""
    app = FastAPI()
    logged: list[str] = []

    @app.middleware("http")
    async def record(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        logged.append(loggable_request_path(request))
        return response

    @app.get("/api/v1/l/{slug}/file")
    async def short_link_file(slug: str) -> dict[str, str]:
        return {"slug": slug}

    return TestClient(app), logged


def test_a_short_link_request_logs_the_slug_masked() -> None:
    client, logged = _logged_paths()

    client.get("/api/v1/l/abc123/file")

    assert logged == ["/api/v1/l/{slug}/file"]


def test_a_short_link_request_refused_before_its_route_runs_still_masks_the_slug() -> None:
    client, logged = _logged_paths()

    resp = client.post("/api/v1/l/abc123/file")

    assert resp.status_code == 405
    assert logged == ["/api/v1/l/{slug}/file"]


def test_the_unshare_route_is_not_mistaken_for_a_slug() -> None:
    client, logged = _logged_paths()

    client.post("/api/v1/l/unshare")

    assert logged == ["/api/v1/l/unshare"]


def test_a_path_outside_short_links_logs_unchanged() -> None:
    client, logged = _logged_paths()

    client.get("/api/v1/plain/42")

    assert logged == ["/api/v1/plain/42"]
