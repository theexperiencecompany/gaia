"""loggable_request_path must keep a secret path parameter out of the logs."""

from fastapi import Depends, FastAPI, Request
from starlette.testclient import TestClient

from app.utils.loggable_path import log_route_template_as_path, loggable_request_path


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/l/{slug}/file", dependencies=[Depends(log_route_template_as_path)])
    async def secret_route(request: Request) -> dict[str, str]:
        return {"path": loggable_request_path(request)}

    @app.get("/plain/{item_id}")
    async def plain_route(request: Request) -> dict[str, str]:
        return {"path": loggable_request_path(request)}

    return app


def test_a_route_marked_secret_logs_its_template_not_the_slug() -> None:
    resp = TestClient(_app()).get("/l/abc123/file")

    assert resp.json() == {"path": "/l/{slug}/file"}


def test_an_unmarked_route_logs_its_url_path() -> None:
    resp = TestClient(_app()).get("/plain/42")

    assert resp.json() == {"path": "/plain/42"}
