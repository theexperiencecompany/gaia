"""Canonical endpoint test — copy into tests/unit/api/, rename, adapt.

The root client fixture (ASGITransport against the test app, auth dependency
overridden), the service mocked at the module the endpoint calls, and asserts on
status code + response body only. The 401 path uses unauthed_client (auth dependency popped).
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.services.tasks.errors import TaskNotFoundError

API = "/api/v1"
SERVICE = "app.services.tasks.task_service"


@pytest.mark.unit
class TestDeleteTask:
    async def test_returns_no_content(self, client: AsyncClient) -> None:
        with patch(f"{SERVICE}.delete_task", new_callable=AsyncMock) as delete:
            resp = await client.delete(f"{API}/tasks/task_1")
        assert resp.status_code == 204
        delete.assert_awaited_once()

    async def test_returns_404_when_the_task_is_not_there(self, client: AsyncClient) -> None:
        with patch(
            f"{SERVICE}.delete_task",
            new_callable=AsyncMock,
            side_effect=TaskNotFoundError("missing"),
        ):
            resp = await client.delete(f"{API}/tasks/missing")
        assert resp.status_code == 404
        assert resp.json()["code"] == "task_not_found"

    async def test_returns_401_without_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{API}/tasks/task_1")
        assert resp.status_code == 401
