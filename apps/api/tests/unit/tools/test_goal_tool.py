"""Unit tests for app.agents.tools.goal_tool."""

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level patch: ensure tiered_limiter.check_and_increment returns a
# plain dict so the @with_rate_limiting decorator doesn't crash.
# ---------------------------------------------------------------------------
_rl_patch = patch(
    "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
    new_callable=AsyncMock,
    return_value={},
)
_rl_patch.start()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
FAKE_GOAL_ID = "60d5ec49f1a2c8b1e8a7b123"  # Valid 24-char hex ObjectId
MODULE = "app.agents.tools.goal_tool"


def _cfg(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    return {"metadata": {"user_id": user_id}}


def _cfg_no_user() -> Dict[str, Any]:
    return {"metadata": {}}


def _writer() -> MagicMock:
    return MagicMock()


def _goal_dict(**overrides: Any) -> dict:
    defaults = {
        "id": "goal-1",
        "title": "Learn Rust",
        "description": "Master the Rust programming language",
        "user_id": FAKE_USER_ID,
        "roadmap": {},
    }
    defaults.update(overrides)
    return defaults


def _goal_mock(**overrides: Any) -> MagicMock:
    d = _goal_dict(**overrides)
    mock = MagicMock()
    mock.model_dump.return_value = d
    for k, v in d.items():
        setattr(mock, k, v)
    return mock


# ---------------------------------------------------------------------------
# Tests: create_goal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateGoal:
    @patch(f"{MODULE}.invalidate_goal_caches", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_stream_writer")
    @patch("app.services.goals_service.create_goal_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_uid: MagicMock,
        mock_svc: AsyncMock,
        mock_gsw: MagicMock,
        mock_inv: AsyncMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_svc.return_value = _goal_mock(title="Learn Rust")

        from app.agents.tools.goal_tool import create_goal

        result = await create_goal.coroutine(config=_cfg(), title="Learn Rust")

        assert result["error"] is None
        assert result["goal"]["title"] == "Learn Rust"
        mock_svc.assert_awaited_once()
        mock_inv.assert_awaited_once()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user_id(self, mock_uid: MagicMock, mock_gsw: MagicMock) -> None:
        from app.agents.tools.goal_tool import create_goal

        result = await create_goal.coroutine(config=_cfg_no_user(), title="X")
        assert result["error"] == "User authentication required"
        assert result["goal"] is None

    @patch(f"{MODULE}.invalidate_goal_caches", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        "app.services.goals_service.create_goal_service",
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB down"),
    )
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self,
        mock_uid: MagicMock,
        mock_svc: AsyncMock,
        mock_gsw: MagicMock,
        mock_inv: AsyncMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        from app.agents.tools.goal_tool import create_goal

        result = await create_goal.coroutine(config=_cfg(), title="X")
        assert "Error creating goal" in result["error"]
        assert result["goal"] is None

    @patch(f"{MODULE}.invalidate_goal_caches", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_stream_writer")
    @patch("app.services.goals_service.create_goal_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_streams_progress(
        self,
        mock_uid: MagicMock,
        mock_svc: AsyncMock,
        mock_gsw: MagicMock,
        mock_inv: AsyncMock,
    ) -> None:
        w = _writer()
        mock_gsw.return_value = w
        mock_svc.return_value = _goal_mock()

        from app.agents.tools.goal_tool import create_goal

        await create_goal.coroutine(config=_cfg(), title="Learn Rust")

        # Should have called writer at least twice (creating + create)
        assert w.call_count >= 2
        first_call = w.call_args_list[0][0][0]
        assert first_call["goal_data"]["action"] == "creating"


# ---------------------------------------------------------------------------
# Tests: list_goals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListGoals:
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_goals_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self, mock_uid: MagicMock, mock_svc: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_svc.return_value = [_goal_dict(), _goal_dict(id="goal-2")]

        from app.agents.tools.goal_tool import list_goals

        result = await list_goals.coroutine(config=_cfg())
        assert result["error"] is None
        assert result["count"] == 2
        assert len(result["goals"]) == 2

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user(self, mock_uid: MagicMock, mock_gsw: MagicMock) -> None:
        from app.agents.tools.goal_tool import list_goals

        result = await list_goals.coroutine(config=_cfg_no_user())
        assert result["error"] == "User authentication required"
        assert result["goals"] == []

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_goals_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_empty_list(
        self, mock_uid: MagicMock, mock_svc: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_svc.return_value = []

        from app.agents.tools.goal_tool import list_goals

        result = await list_goals.coroutine(config=_cfg())
        assert result["count"] == 0
        assert result["goals"] == []

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.get_user_goals_service",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self, mock_uid: MagicMock, mock_svc: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        from app.agents.tools.goal_tool import list_goals

        result = await list_goals.coroutine(config=_cfg())
        assert "Error listing goals" in result["error"]


# ---------------------------------------------------------------------------
# Tests: get_goal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetGoal:
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_goal_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self, mock_uid: MagicMock, mock_svc: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_svc.return_value = _goal_dict()

        from app.agents.tools.goal_tool import get_goal

        result = await get_goal.coroutine(config=_cfg(), goal_id="goal-1")
        assert result["error"] is None
        assert result["goal"]["id"] == "goal-1"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_goal_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_roadmap_needed(
        self, mock_uid: MagicMock, mock_svc: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        w = _writer()
        mock_gsw.return_value = w
        mock_svc.return_value = {"message": "Roadmap not generated yet"}

        from app.agents.tools.goal_tool import get_goal

        result = await get_goal.coroutine(config=_cfg(), goal_id="goal-1")
        assert result["error"] is None
        # Writer should have been called with roadmap_needed action
        actions = [c[0][0]["goal_data"]["action"] for c in w.call_args_list]
        assert "roadmap_needed" in actions

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user(self, mock_uid: MagicMock, mock_gsw: MagicMock) -> None:
        from app.agents.tools.goal_tool import get_goal

        result = await get_goal.coroutine(config=_cfg_no_user(), goal_id="goal-1")
        assert result["goal"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.get_goal_service",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self, mock_uid: MagicMock, mock_svc: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        from app.agents.tools.goal_tool import get_goal

        result = await get_goal.coroutine(config=_cfg(), goal_id="goal-1")
        assert "Error getting goal" in result["error"]


# ---------------------------------------------------------------------------
# Tests: delete_goal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteGoal:
    @patch(f"{MODULE}.invalidate_goal_caches", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.delete_goal_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_uid: MagicMock,
        mock_svc: AsyncMock,
        mock_gsw: MagicMock,
        mock_inv: AsyncMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_svc.return_value = {"title": "Learn Rust", "id": "goal-1"}

        from app.agents.tools.goal_tool import delete_goal

        result = await delete_goal.coroutine(config=_cfg(), goal_id="goal-1")
        assert result["success"] is True
        assert result["error"] is None
        mock_inv.assert_awaited_once()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user(self, mock_uid: MagicMock, mock_gsw: MagicMock) -> None:
        from app.agents.tools.goal_tool import delete_goal

        result = await delete_goal.coroutine(config=_cfg_no_user(), goal_id="goal-1")
        assert result["success"] is False

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.delete_goal_service",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self, mock_uid: MagicMock, mock_svc: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        from app.agents.tools.goal_tool import delete_goal

        result = await delete_goal.coroutine(config=_cfg(), goal_id="goal-1")
        assert "Error deleting goal" in result["error"]
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Tests: generate_roadmap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateRoadmap:
    @patch(f"{MODULE}.invalidate_goal_caches", new_callable=AsyncMock)
    @patch("app.utils.goals_utils.goal_helper")
    @patch(f"{MODULE}.goals_collection")
    @patch(f"{MODULE}.update_goal_with_roadmap_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.generate_roadmap_with_llm_stream")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_uid: MagicMock,
        mock_gsw: MagicMock,
        mock_stream: MagicMock,
        mock_update: AsyncMock,
        mock_coll: MagicMock,
        mock_helper: MagicMock,
        mock_inv: AsyncMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        roadmap = {"nodes": [{"id": "n1"}], "edges": []}

        # goals_collection.find_one returns a goal doc
        goal_doc = {"_id": "obj-id", "title": "Learn Rust", "roadmap": {}}
        updated_doc = {"_id": "obj-id", "title": "Learn Rust", "roadmap": roadmap}
        mock_coll.find_one = AsyncMock(side_effect=[goal_doc, updated_doc])

        # Stream yields progress then roadmap
        async def _gen(title):
            yield {"progress": "Thinking..."}
            yield {"roadmap": roadmap}

        mock_stream.side_effect = _gen
        mock_update.return_value = True
        mock_helper.return_value = _goal_dict(roadmap=roadmap)

        from app.agents.tools.goal_tool import generate_roadmap

        result = await generate_roadmap.coroutine(config=_cfg(), goal_id=FAKE_GOAL_ID)
        assert result["error"] is None
        assert result["roadmap"] == roadmap
        mock_inv.assert_awaited_once()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user(self, mock_uid: MagicMock, mock_gsw: MagicMock) -> None:
        from app.agents.tools.goal_tool import generate_roadmap

        result = await generate_roadmap.coroutine(
            config=_cfg_no_user(), goal_id=FAKE_GOAL_ID
        )
        assert result["roadmap"] is None

    @patch(f"{MODULE}.goals_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_goal_not_found(
        self, mock_uid: MagicMock, mock_gsw: MagicMock, mock_coll: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_coll.find_one = AsyncMock(return_value=None)

        from app.agents.tools.goal_tool import generate_roadmap

        result = await generate_roadmap.coroutine(config=_cfg(), goal_id=FAKE_GOAL_ID)
        assert result["error"] == "Goal not found"

    @patch(f"{MODULE}.goals_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_roadmap_already_exists(
        self, mock_uid: MagicMock, mock_gsw: MagicMock, mock_coll: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        existing = {"nodes": [{"id": "n1"}], "edges": []}
        mock_coll.find_one = AsyncMock(
            return_value={"_id": "obj-id", "title": "X", "roadmap": existing}
        )

        from app.agents.tools.goal_tool import generate_roadmap

        result = await generate_roadmap.coroutine(
            config=_cfg(), goal_id=FAKE_GOAL_ID, regenerate=False
        )
        assert "already exists" in result["error"]

    @patch(f"{MODULE}.generate_roadmap_with_llm_stream")
    @patch(f"{MODULE}.goals_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_stream_error(
        self,
        mock_uid: MagicMock,
        mock_gsw: MagicMock,
        mock_coll: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        w = _writer()
        mock_gsw.return_value = w
        mock_coll.find_one = AsyncMock(
            return_value={"_id": "obj-id", "title": "X", "roadmap": {}}
        )

        async def _gen(title):
            yield {"error": "LLM failed"}

        mock_stream.side_effect = _gen

        from app.agents.tools.goal_tool import generate_roadmap

        result = await generate_roadmap.coroutine(config=_cfg(), goal_id=FAKE_GOAL_ID)
        assert result["error"] == "LLM failed"

    @patch(f"{MODULE}.generate_roadmap_with_llm_stream")
    @patch(f"{MODULE}.goals_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_no_roadmap_generated(
        self,
        mock_uid: MagicMock,
        mock_gsw: MagicMock,
        mock_coll: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_coll.find_one = AsyncMock(
            return_value={"_id": "obj-id", "title": "X", "roadmap": {}}
        )

        async def _gen(title):
            yield {"progress": "Working..."}
            # No roadmap yielded

        mock_stream.side_effect = _gen

        from app.agents.tools.goal_tool import generate_roadmap

        result = await generate_roadmap.coroutine(config=_cfg(), goal_id=FAKE_GOAL_ID)
        assert result["error"] == "Failed to generate roadmap"


# ---------------------------------------------------------------------------
# Tests: update_goal_node
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateGoalNode:
    @patch(f"{MODULE}.invalidate_goal_caches", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.update_node_status_service", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_uid: MagicMock,
        mock_svc: AsyncMock,
        mock_gsw: MagicMock,
        mock_inv: AsyncMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_svc.return_value = _goal_dict(title="Learn Rust")

        from app.agents.tools.goal_tool import update_goal_node

        result = await update_goal_node.coroutine(
            config=_cfg(), goal_id=FAKE_GOAL_ID, node_id="n1", is_complete=True
        )
        assert result["error"] is None
        assert result["goal"]["title"] == "Learn Rust"
        mock_inv.assert_awaited_once()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user(self, mock_uid: MagicMock, mock_gsw: MagicMock) -> None:
        from app.agents.tools.goal_tool import update_goal_node

        result = await update_goal_node.coroutine(
            config=_cfg_no_user(), goal_id=FAKE_GOAL_ID, node_id="n1", is_complete=True
        )
        assert result["goal"] is None

    @patch(f"{MODULE}.get_stream_writer")
    @patch(
        f"{MODULE}.update_node_status_service",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self, mock_uid: MagicMock, mock_svc: AsyncMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        from app.agents.tools.goal_tool import update_goal_node

        result = await update_goal_node.coroutine(
            config=_cfg(), goal_id=FAKE_GOAL_ID, node_id="n1", is_complete=False
        )
        assert "Error updating goal node" in result["error"]


# ---------------------------------------------------------------------------
# Tests: search_goals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchGoals:
    @patch("app.utils.goals_utils.goal_helper")
    @patch(f"{MODULE}.goals_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_happy_path(
        self,
        mock_uid: MagicMock,
        mock_gsw: MagicMock,
        mock_coll: MagicMock,
        mock_helper: MagicMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[{"_id": "obj1", "title": "Rust"}])
        mock_coll.find.return_value.limit.return_value = cursor
        mock_helper.return_value = _goal_dict(title="Rust")

        from app.agents.tools.goal_tool import search_goals

        result = await search_goals.coroutine(config=_cfg(), query="Rust")
        assert result["error"] is None
        assert result["count"] == 1

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user(self, mock_uid: MagicMock, mock_gsw: MagicMock) -> None:
        from app.agents.tools.goal_tool import search_goals

        result = await search_goals.coroutine(config=_cfg_no_user(), query="X")
        assert result["goals"] == []

    @patch(f"{MODULE}.goals_collection")
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_service_error(
        self, mock_uid: MagicMock, mock_gsw: MagicMock, mock_coll: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_coll.find.side_effect = RuntimeError("DB error")

        from app.agents.tools.goal_tool import search_goals

        result = await search_goals.coroutine(config=_cfg(), query="X")
        assert "Error searching goals" in result["error"]


# ---------------------------------------------------------------------------
# Tests: get_goal_statistics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetGoalStatistics:
    @patch(f"{MODULE}.set_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.goals_collection")
    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_computes_stats(
        self,
        mock_uid: MagicMock,
        mock_gsw: MagicMock,
        mock_get_cache: AsyncMock,
        mock_coll: MagicMock,
        mock_set_cache: AsyncMock,
    ) -> None:
        mock_gsw.return_value = _writer()
        goals = [
            {
                "_id": "obj1",
                "user_id": FAKE_USER_ID,
                "title": "G1",
                "roadmap": {
                    "nodes": [
                        {"data": {"type": "start"}},
                        {"data": {"type": "task", "isComplete": True}},
                        {"data": {"type": "task", "isComplete": False}},
                        {"data": {"type": "end"}},
                    ]
                },
            }
        ]
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=goals)
        mock_coll.find.return_value = cursor

        from app.agents.tools.goal_tool import get_goal_statistics

        # Patch goal_helper since it's imported inside the function
        with patch(
            "app.utils.goals_utils.goal_helper", return_value=_goal_dict(title="G1")
        ):
            result = await get_goal_statistics.coroutine(config=_cfg())

        assert result["error"] is None
        stats = result["stats"]
        assert stats["total_goals"] == 1
        assert stats["total_tasks"] == 2
        assert stats["completed_tasks"] == 1
        assert stats["overall_completion_rate"] == 50
        mock_set_cache.assert_awaited_once()

    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_cached_stats_string(
        self, mock_uid: MagicMock, mock_gsw: MagicMock, mock_get_cache: AsyncMock
    ) -> None:
        mock_gsw.return_value = _writer()
        cached = json.dumps({"total_goals": 5, "completed_tasks": 3})
        mock_get_cache.return_value = cached

        from app.agents.tools.goal_tool import get_goal_statistics

        result = await get_goal_statistics.coroutine(config=_cfg())
        assert result["error"] is None
        assert result["stats"]["total_goals"] == 5

    @patch(f"{MODULE}.get_cache", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value=FAKE_USER_ID)
    async def test_cached_stats_dict(
        self, mock_uid: MagicMock, mock_gsw: MagicMock, mock_get_cache: AsyncMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_get_cache.return_value = {"total_goals": 5}

        from app.agents.tools.goal_tool import get_goal_statistics

        result = await get_goal_statistics.coroutine(config=_cfg())
        assert result["stats"]["total_goals"] == 5

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.get_user_id_from_config", return_value="")
    async def test_no_user(self, mock_uid: MagicMock, mock_gsw: MagicMock) -> None:
        from app.agents.tools.goal_tool import get_goal_statistics

        result = await get_goal_statistics.coroutine(config=_cfg_no_user())
        assert result["stats"] is None


# ---------------------------------------------------------------------------
# Tests: invalidate_goal_caches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvalidateGoalCaches:
    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    async def test_invalidates_list_and_stats(self, mock_del: AsyncMock) -> None:
        from app.agents.tools.goal_tool import invalidate_goal_caches

        await invalidate_goal_caches(FAKE_USER_ID)
        assert mock_del.await_count == 2  # goals list + stats

    @patch(f"{MODULE}.delete_cache", new_callable=AsyncMock)
    async def test_invalidates_specific_goal(self, mock_del: AsyncMock) -> None:
        from app.agents.tools.goal_tool import invalidate_goal_caches

        await invalidate_goal_caches(FAKE_USER_ID, "goal-1")
        assert mock_del.await_count == 3  # list + stats + specific

    @patch(
        f"{MODULE}.delete_cache",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Redis down"),
    )
    async def test_swallows_errors(self, mock_del: AsyncMock) -> None:
        from app.agents.tools.goal_tool import invalidate_goal_caches

        # Should not raise
        await invalidate_goal_caches(FAKE_USER_ID)
