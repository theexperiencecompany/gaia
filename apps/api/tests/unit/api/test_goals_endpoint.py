"""Unit tests for the goals API endpoints.

Tests cover CRUD operations on goals and node status updates. The goals service
functions are mocked; only HTTP status codes, response shapes, and error
handling are verified.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from tests.conftest import FAKE_USER

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API = "/api/v1"
USER_ID = FAKE_USER["user_id"]
NOW = datetime.now(timezone.utc).isoformat()


def _goal_response(
    goal_id: str = "goal_1",
    title: str = "Learn Rust",
    progress: int = 0,
) -> dict:
    """Return a dict matching GoalResponse shape."""
    return {
        "id": goal_id,
        "title": title,
        "progress": progress,
        "description": "",
        "roadmap": {"nodes": [], "edges": []},
        "user_id": USER_ID,
        "created_at": NOW,
        "todo_project_id": None,
        "todo_id": None,
    }


# ===========================================================================
# POST /api/v1/goals  -- create goal
# ===========================================================================


@pytest.mark.unit
class TestCreateGoal:
    """POST /api/v1/goals"""

    async def test_create_goal_success(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.create_goal_service",
            new_callable=AsyncMock,
            return_value=_goal_response("new_goal"),
        ):
            resp = await client.post(f"{API}/goals", json={"title": "Learn Rust"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "new_goal"
        assert data["title"] == "Learn Rust"

    async def test_create_goal_with_description(self, client: AsyncClient) -> None:
        goal = _goal_response()
        goal["description"] = "Become proficient in Rust"
        with patch(
            "app.api.v1.endpoints.goals.create_goal_service",
            new_callable=AsyncMock,
            return_value=goal,
        ):
            resp = await client.post(
                f"{API}/goals",
                json={
                    "title": "Learn Rust",
                    "description": "Become proficient in Rust",
                },
            )
        assert resp.status_code == 200

    async def test_create_goal_validation_error_missing_title(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(f"{API}/goals", json={})
        assert resp.status_code == 422

    async def test_create_goal_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.create_goal_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=500, detail="Failed to create goal"),
        ):
            resp = await client.post(f"{API}/goals", json={"title": "Learn Rust"})
        assert resp.status_code == 500

    async def test_create_goal_requires_auth(
        self, unauthed_client: AsyncClient
    ) -> None:
        resp = await unauthed_client.post(f"{API}/goals", json={"title": "Learn Rust"})
        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/goals/{goal_id}  -- get goal
# ===========================================================================


@pytest.mark.unit
class TestGetGoal:
    """GET /api/v1/goals/{goal_id}"""

    async def test_get_goal_success(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.get_goal_service",
            new_callable=AsyncMock,
            return_value=_goal_response("g1"),
        ):
            resp = await client.get(f"{API}/goals/g1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "g1"

    async def test_get_goal_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.get_goal_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Goal not found"),
        ):
            resp = await client.get(f"{API}/goals/nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_get_goal_roadmap_unavailable(self, client: AsyncClient) -> None:
        """When roadmap is not generated yet the service returns a special dict."""
        with patch(
            "app.api.v1.endpoints.goals.get_goal_service",
            new_callable=AsyncMock,
            return_value={
                "message": "Roadmap not available. Please generate it using the WebSocket.",
                "id": "g1",
                "title": "Learn Rust",
            },
        ):
            resp = await client.get(f"{API}/goals/g1")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    async def test_get_goal_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.get_goal_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=500, detail="Failed to fetch goal"),
        ):
            resp = await client.get(f"{API}/goals/g1")
        assert resp.status_code == 500

    async def test_get_goal_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/goals/g1")
        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/goals  -- list goals
# ===========================================================================


@pytest.mark.unit
class TestListGoals:
    """GET /api/v1/goals"""

    async def test_list_goals_success(self, client: AsyncClient) -> None:
        goals = [_goal_response("g1"), _goal_response("g2", title="Ship MVP")]
        with patch(
            "app.api.v1.endpoints.goals.get_user_goals_service",
            new_callable=AsyncMock,
            return_value=goals,
        ):
            resp = await client.get(f"{API}/goals")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_list_goals_empty(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.get_user_goals_service",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(f"{API}/goals")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_goals_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.get_user_goals_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=500, detail="Failed to list goals"),
        ):
            resp = await client.get(f"{API}/goals")
        assert resp.status_code == 500

    async def test_list_goals_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/goals")
        assert resp.status_code == 401


# ===========================================================================
# DELETE /api/v1/goals/{goal_id}  -- delete goal
# ===========================================================================


@pytest.mark.unit
class TestDeleteGoal:
    """DELETE /api/v1/goals/{goal_id}"""

    async def test_delete_goal_success(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.delete_goal_service",
            new_callable=AsyncMock,
            return_value=_goal_response("g1"),
        ):
            resp = await client.delete(f"{API}/goals/g1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "g1"

    async def test_delete_goal_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.delete_goal_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Goal not found"),
        ):
            resp = await client.delete(f"{API}/goals/nonexistent")
        assert resp.status_code == 404

    async def test_delete_goal_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.delete_goal_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(
                status_code=500, detail="Failed to delete the goal"
            ),
        ):
            resp = await client.delete(f"{API}/goals/g1")
        assert resp.status_code == 500

    async def test_delete_goal_requires_auth(
        self, unauthed_client: AsyncClient
    ) -> None:
        resp = await unauthed_client.delete(f"{API}/goals/g1")
        assert resp.status_code == 401


# ===========================================================================
# PATCH /api/v1/goals/{goal_id}/roadmap/nodes/{node_id}  -- update node
# ===========================================================================


@pytest.mark.unit
class TestUpdateNodeStatus:
    """PATCH /api/v1/goals/{goal_id}/roadmap/nodes/{node_id}"""

    async def test_update_node_success(self, client: AsyncClient) -> None:
        goal = _goal_response("g1")
        goal["progress"] = 50
        with patch(
            "app.api.v1.endpoints.goals.update_node_status_service",
            new_callable=AsyncMock,
            return_value=goal,
        ):
            resp = await client.patch(
                f"{API}/goals/g1/roadmap/nodes/n1",
                json={"is_complete": True},
            )
        assert resp.status_code == 200
        assert resp.json()["progress"] == 50

    async def test_update_node_goal_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.update_node_status_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Goal not found"),
        ):
            resp = await client.patch(
                f"{API}/goals/bad/roadmap/nodes/n1",
                json={"is_complete": True},
            )
        assert resp.status_code == 404

    async def test_update_node_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.update_node_status_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(
                status_code=404, detail="Node not found in roadmap"
            ),
        ):
            resp = await client.patch(
                f"{API}/goals/g1/roadmap/nodes/bad_node",
                json={"is_complete": True},
            )
        assert resp.status_code == 404

    async def test_update_node_validation_error_missing_is_complete(
        self, client: AsyncClient
    ) -> None:
        resp = await client.patch(f"{API}/goals/g1/roadmap/nodes/n1", json={})
        assert resp.status_code == 422

    async def test_update_node_validation_error_bad_type(
        self, client: AsyncClient
    ) -> None:
        resp = await client.patch(
            f"{API}/goals/g1/roadmap/nodes/n1",
            json={"is_complete": "not_a_bool"},
        )
        assert resp.status_code == 422

    async def test_update_node_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.goals.update_node_status_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=500, detail="Failed to update node"),
        ):
            resp = await client.patch(
                f"{API}/goals/g1/roadmap/nodes/n1",
                json={"is_complete": True},
            )
        assert resp.status_code == 500

    async def test_update_node_requires_auth(
        self, unauthed_client: AsyncClient
    ) -> None:
        resp = await unauthed_client.patch(
            f"{API}/goals/g1/roadmap/nodes/n1",
            json={"is_complete": True},
        )
        assert resp.status_code == 401
