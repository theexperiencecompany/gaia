"""Smoke tests for the FastAPI entry point (app.main).

app.main constructs the real app at import time; under the root conftest's
hermetic mocks that is safe (the same path the `client` fixture uses). Route
registration resolves lazily at request time in FastAPI 0.139, so the
registration assertion dispatches a real request instead of inspecting
app.routes. app.main.py was at 0% coverage.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def test_app_main_constructs_the_app() -> None:
    from app.main import app

    assert isinstance(app, FastAPI)


async def test_health_route_serves_requests() -> None:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
