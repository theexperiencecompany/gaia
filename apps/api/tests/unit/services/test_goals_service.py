"""Unit tests for goals service operations."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.models.goals_models import GoalCreate, GoalResponse, UpdateNodeRequest
from app.services.goals_service import (
    create_goal_service,
    delete_goal_service,
    generate_roadmap_with_llm_stream,
    get_goal_service,
    get_user_goals_service,
    update_goal_with_roadmap_service,
    update_node_status_service,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FAKE_USER_ID = "user_abc123"
FAKE_GOAL_ID = str(ObjectId())
FAKE_OBJECT_ID = ObjectId(FAKE_GOAL_ID)


@pytest.fixture
def authenticated_user() -> dict:
    return {"user_id": FAKE_USER_ID, "email": "test@example.com"}


@pytest.fixture
def unauthenticated_user() -> dict:
    return {"email": "anon@example.com"}


@pytest.fixture
def sample_goal_doc() -> dict:
    return {
        "_id": FAKE_OBJECT_ID,
        "title": "Learn Python",
        "description": "Master Python programming",
        "created_at": "2026-01-01T00:00:00",
        "user_id": FAKE_USER_ID,
        "roadmap": {
            "title": "Python Roadmap",
            "description": "Step by step",
            "nodes": [
                {
                    "id": "node1",
                    "data": {
                        "label": "Basics",
                        "details": ["variables"],
                        "isComplete": False,
                    },
                },
                {
                    "id": "node2",
                    "data": {
                        "label": "Advanced",
                        "details": ["decorators"],
                        "isComplete": True,
                    },
                },
            ],
            "edges": [{"id": "e1-2", "source": "node1", "target": "node2"}],
        },
    }


@pytest.fixture
def sample_goal_doc_no_roadmap() -> dict:
    return {
        "_id": FAKE_OBJECT_ID,
        "title": "Learn Python",
        "description": "Master Python programming",
        "created_at": "2026-01-01T00:00:00",
        "user_id": FAKE_USER_ID,
        "roadmap": {"nodes": [], "edges": []},
    }


@pytest.fixture
def mock_goals_collection():
    with patch("app.services.goals_service.goals_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_cache():
    with (
        patch("app.services.goals_service.get_cache", new_callable=AsyncMock) as m_get,
        patch("app.services.goals_service.set_cache", new_callable=AsyncMock) as m_set,
    ):
        yield m_get, m_set


@pytest.fixture
def mock_invalidate_caches():
    with patch(
        "app.services.goals_service._invalidate_goal_caches",
        new_callable=AsyncMock,
    ) as m:
        yield m


@pytest.fixture
def mock_sync_node():
    with patch(
        "app.services.goals_service.sync_goal_node_completion",
        new_callable=AsyncMock,
    ) as m:
        yield m


@pytest.fixture
def mock_create_project_todo():
    with patch(
        "app.services.goals_service.create_goal_project_and_todo",
        new_callable=AsyncMock,
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# create_goal_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateGoalService:
    async def test_success(
        self,
        mock_goals_collection,
        mock_invalidate_caches,
        authenticated_user,
    ):
        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_goals_collection.insert_one = AsyncMock(return_value=mock_result)

        goal_input = GoalCreate(title="Learn Rust", description="Systems programming")
        result = await create_goal_service(goal_input, authenticated_user)

        assert isinstance(result, GoalResponse)
        assert result.title == "Learn Rust"
        assert result.user_id == FAKE_USER_ID
        assert result.id == str(inserted_id)
        mock_goals_collection.insert_one.assert_awaited_once()
        mock_invalidate_caches.assert_awaited_once_with(FAKE_USER_ID)

    async def test_missing_user_id_raises_403(self, unauthenticated_user):
        goal_input = GoalCreate(title="No Auth")

        with pytest.raises(HTTPException) as exc_info:
            await create_goal_service(goal_input, unauthenticated_user)

        assert exc_info.value.status_code == 403
        assert "Not authenticated" in exc_info.value.detail

    async def test_insertion_failure_raises_500(
        self, mock_goals_collection, authenticated_user
    ):
        mock_goals_collection.insert_one = AsyncMock(
            side_effect=Exception("DB connection lost")
        )
        goal_input = GoalCreate(title="Broken Insert")

        with pytest.raises(HTTPException) as exc_info:
            await create_goal_service(goal_input, authenticated_user)

        assert exc_info.value.status_code == 500
        assert "Failed to create goal" in exc_info.value.detail

    async def test_default_description_is_empty_string(
        self, mock_goals_collection, mock_invalidate_caches, authenticated_user
    ):
        inserted_id = ObjectId()
        mock_result = MagicMock()
        mock_result.inserted_id = inserted_id
        mock_goals_collection.insert_one = AsyncMock(return_value=mock_result)

        goal_input = GoalCreate(title="No description")
        result = await create_goal_service(goal_input, authenticated_user)

        assert result.description == ""


# ---------------------------------------------------------------------------
# get_goal_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetGoalService:
    async def test_cache_hit_returns_cached_dict(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
        sample_goal_doc,
    ):
        mock_get, _ = mock_cache
        cached_data = {
            "id": FAKE_GOAL_ID,
            "title": "Learn Python",
            "description": "Master Python programming",
            "progress": 50,
            "user_id": FAKE_USER_ID,
            "created_at": "2026-01-01T00:00:00",
            "roadmap": {},
        }
        # Return dict directly (non-string cache hit)
        mock_get.return_value = cached_data

        result = await get_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert result == cached_data
        mock_goals_collection.find_one.assert_not_called()

    async def test_cache_hit_returns_cached_string(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        mock_get, _ = mock_cache
        cached_data = {"id": FAKE_GOAL_ID, "title": "Cached Goal"}
        mock_get.return_value = json.dumps(cached_data)

        result = await get_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert result == cached_data
        mock_goals_collection.find_one.assert_not_called()

    async def test_cache_miss_fetches_from_db(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
        sample_goal_doc,
    ):
        mock_get, mock_set = mock_cache
        mock_get.return_value = None
        mock_goals_collection.find_one = AsyncMock(return_value=sample_goal_doc)

        result = await get_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert result["id"] == FAKE_GOAL_ID
        assert result["title"] == "Learn Python"
        mock_goals_collection.find_one.assert_awaited_once()
        mock_set.assert_awaited_once()

    async def test_goal_not_found_raises_404(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        mock_get, _ = mock_cache
        mock_get.return_value = None
        mock_goals_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert exc_info.value.status_code == 404
        assert "Goal not found" in exc_info.value.detail

    async def test_missing_roadmap_returns_message(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
        sample_goal_doc_no_roadmap,
    ):
        mock_get, mock_set = mock_cache
        mock_get.return_value = None
        mock_goals_collection.find_one = AsyncMock(
            return_value=sample_goal_doc_no_roadmap
        )

        result = await get_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert "message" in result
        assert "Roadmap not available" in result["message"]
        assert result["id"] == FAKE_GOAL_ID
        assert result["title"] == "Learn Python"
        # Should NOT cache an incomplete goal
        mock_set.assert_not_awaited()

    async def test_missing_user_id_raises_403(self, unauthenticated_user):
        with pytest.raises(HTTPException) as exc_info:
            await get_goal_service(FAKE_GOAL_ID, unauthenticated_user)

        assert exc_info.value.status_code == 403

    async def test_roadmap_with_empty_nodes_returns_message(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        """Goal with roadmap dict but empty nodes list should trigger the 'no roadmap' path."""
        mock_get, _ = mock_cache
        mock_get.return_value = None
        goal_doc = {
            "_id": FAKE_OBJECT_ID,
            "title": "Empty Roadmap",
            "description": "",
            "created_at": "2026-01-01T00:00:00",
            "user_id": FAKE_USER_ID,
            "roadmap": {"nodes": [], "edges": [{"id": "e1"}]},
        }
        mock_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        result = await get_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert "message" in result

    async def test_roadmap_with_empty_edges_returns_message(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        """Goal with nodes but no edges should trigger the 'no roadmap' path."""
        mock_get, _ = mock_cache
        mock_get.return_value = None
        goal_doc = {
            "_id": FAKE_OBJECT_ID,
            "title": "No Edges Roadmap",
            "description": "",
            "created_at": "2026-01-01T00:00:00",
            "user_id": FAKE_USER_ID,
            "roadmap": {"nodes": [{"id": "n1", "data": {}}], "edges": []},
        }
        mock_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        result = await get_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert "message" in result

    async def test_missing_roadmap_key_returns_message(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        """Goal with no roadmap key at all should trigger the 'no roadmap' path."""
        mock_get, _ = mock_cache
        mock_get.return_value = None
        goal_doc = {
            "_id": FAKE_OBJECT_ID,
            "title": "No Roadmap Key",
            "description": "",
            "created_at": "2026-01-01T00:00:00",
            "user_id": FAKE_USER_ID,
        }
        mock_goals_collection.find_one = AsyncMock(return_value=goal_doc)

        result = await get_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert "message" in result


# ---------------------------------------------------------------------------
# get_user_goals_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserGoalsService:
    def _make_cursor(self, docs: list) -> MagicMock:
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=docs)
        return cursor

    async def test_cache_hit_returns_cached_dict(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        mock_get, _ = mock_cache
        cached_goals = [{"id": "g1", "title": "Goal 1"}]
        mock_get.return_value = {"goals": cached_goals}

        result = await get_user_goals_service(authenticated_user)

        assert result == cached_goals
        mock_goals_collection.find.assert_not_called()

    async def test_cache_hit_returns_cached_string(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        mock_get, _ = mock_cache
        cached_goals = [{"id": "g1", "title": "Goal 1"}]
        mock_get.return_value = json.dumps({"goals": cached_goals})

        result = await get_user_goals_service(authenticated_user)

        assert result == cached_goals
        mock_goals_collection.find.assert_not_called()

    async def test_cache_miss_fetches_from_db(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
        sample_goal_doc,
    ):
        mock_get, mock_set = mock_cache
        mock_get.return_value = None
        mock_goals_collection.find.return_value = self._make_cursor([sample_goal_doc])

        result = await get_user_goals_service(authenticated_user)

        assert len(result) == 1
        assert result[0]["title"] == "Learn Python"
        mock_set.assert_awaited_once()
        # Verify cached data is a JSON string containing the goals
        cached_arg = mock_set.call_args[0][1]
        parsed = json.loads(cached_arg)
        assert "goals" in parsed

    async def test_empty_goals_list(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        mock_get, mock_set = mock_cache
        mock_get.return_value = None
        mock_goals_collection.find.return_value = self._make_cursor([])

        result = await get_user_goals_service(authenticated_user)

        assert result == []
        mock_set.assert_awaited_once()

    async def test_missing_user_id_raises_403(self, unauthenticated_user):
        with pytest.raises(HTTPException) as exc_info:
            await get_user_goals_service(unauthenticated_user)

        assert exc_info.value.status_code == 403

    async def test_cache_hit_string_without_goals_key(
        self,
        mock_goals_collection,
        mock_cache,
        authenticated_user,
    ):
        """If cached string JSON has no 'goals' key, returns empty list."""
        mock_get, _ = mock_cache
        mock_get.return_value = json.dumps({"other": "data"})

        result = await get_user_goals_service(authenticated_user)

        assert result == []


# ---------------------------------------------------------------------------
# delete_goal_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteGoalService:
    async def test_success(
        self,
        mock_goals_collection,
        mock_invalidate_caches,
        authenticated_user,
        sample_goal_doc,
    ):
        mock_goals_collection.find_one = AsyncMock(return_value=sample_goal_doc)
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_goals_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        result = await delete_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert result["id"] == FAKE_GOAL_ID
        assert result["title"] == "Learn Python"
        mock_invalidate_caches.assert_awaited_once_with(FAKE_USER_ID, FAKE_GOAL_ID)

    async def test_goal_not_found_raises_404(
        self,
        mock_goals_collection,
        authenticated_user,
    ):
        mock_goals_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await delete_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert exc_info.value.status_code == 404
        assert "Goal not found" in exc_info.value.detail

    async def test_deletion_fails_raises_500(
        self,
        mock_goals_collection,
        authenticated_user,
        sample_goal_doc,
    ):
        mock_goals_collection.find_one = AsyncMock(return_value=sample_goal_doc)
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 0
        mock_goals_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_goal_service(FAKE_GOAL_ID, authenticated_user)

        assert exc_info.value.status_code == 500
        assert "Failed to delete the goal" in exc_info.value.detail

    async def test_missing_user_id_raises_403(self, unauthenticated_user):
        with pytest.raises(HTTPException) as exc_info:
            await delete_goal_service(FAKE_GOAL_ID, unauthenticated_user)

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# update_node_status_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateNodeStatusService:
    async def test_success(
        self,
        mock_goals_collection,
        mock_invalidate_caches,
        mock_sync_node,
        authenticated_user,
        sample_goal_doc,
    ):
        # find_one returns the goal with matching node
        mock_goals_collection.find_one = AsyncMock(return_value=sample_goal_doc)
        # find_one_and_update returns updated doc
        updated_doc = {**sample_goal_doc}
        updated_doc["roadmap"]["nodes"][0]["data"]["isComplete"] = True
        mock_goals_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        update_data = UpdateNodeRequest(is_complete=True)
        result = await update_node_status_service(
            FAKE_GOAL_ID, "node1", update_data, authenticated_user
        )

        assert result["id"] == FAKE_GOAL_ID
        mock_goals_collection.find_one_and_update.assert_awaited_once()
        mock_sync_node.assert_awaited_once_with(
            FAKE_GOAL_ID, "node1", True, FAKE_USER_ID
        )
        mock_invalidate_caches.assert_awaited_once_with(FAKE_USER_ID, FAKE_GOAL_ID)

    async def test_goal_not_found_raises_404(
        self,
        mock_goals_collection,
        authenticated_user,
    ):
        # Both find_one calls return None — goal doesn't exist
        mock_goals_collection.find_one = AsyncMock(return_value=None)

        update_data = UpdateNodeRequest(is_complete=True)

        with pytest.raises(HTTPException) as exc_info:
            await update_node_status_service(
                FAKE_GOAL_ID, "node1", update_data, authenticated_user
            )

        assert exc_info.value.status_code == 404
        assert "Goal not found" in exc_info.value.detail

    async def test_node_not_found_raises_404(
        self,
        mock_goals_collection,
        authenticated_user,
        sample_goal_doc,
    ):
        # First find_one (with node filter) returns None — node not in goal
        # Second find_one (goal-only) returns the goal — goal exists but node doesn't
        mock_goals_collection.find_one = AsyncMock(side_effect=[None, sample_goal_doc])

        update_data = UpdateNodeRequest(is_complete=True)

        with pytest.raises(HTTPException) as exc_info:
            await update_node_status_service(
                FAKE_GOAL_ID, "nonexistent_node", update_data, authenticated_user
            )

        assert exc_info.value.status_code == 404
        assert "Node not found in roadmap" in exc_info.value.detail

    async def test_missing_user_id_raises_403(self, unauthenticated_user):
        update_data = UpdateNodeRequest(is_complete=False)

        with pytest.raises(HTTPException) as exc_info:
            await update_node_status_service(
                FAKE_GOAL_ID, "node1", update_data, unauthenticated_user
            )

        assert exc_info.value.status_code == 403

    async def test_update_sets_is_complete_false(
        self,
        mock_goals_collection,
        mock_invalidate_caches,
        mock_sync_node,
        authenticated_user,
        sample_goal_doc,
    ):
        """Verify the service correctly passes is_complete=False to the update."""
        mock_goals_collection.find_one = AsyncMock(return_value=sample_goal_doc)
        mock_goals_collection.find_one_and_update = AsyncMock(
            return_value=sample_goal_doc
        )

        update_data = UpdateNodeRequest(is_complete=False)
        await update_node_status_service(
            FAKE_GOAL_ID, "node1", update_data, authenticated_user
        )

        update_call = mock_goals_collection.find_one_and_update.call_args
        assert update_call[0][1] == {"$set": {"roadmap.nodes.$.data.isComplete": False}}
        mock_sync_node.assert_awaited_once_with(
            FAKE_GOAL_ID, "node1", False, FAKE_USER_ID
        )


# ---------------------------------------------------------------------------
# update_goal_with_roadmap_service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateGoalWithRoadmapService:
    async def test_success_returns_true(
        self,
        mock_goals_collection,
        mock_invalidate_caches,
        mock_create_project_todo,
        sample_goal_doc,
    ):
        mock_goals_collection.find_one = AsyncMock(return_value=sample_goal_doc)
        mock_create_project_todo.return_value = "project_123"

        roadmap_data = {"nodes": [{"id": "n1"}], "edges": [{"id": "e1"}]}
        result = await update_goal_with_roadmap_service(FAKE_GOAL_ID, roadmap_data)

        assert result is True
        mock_create_project_todo.assert_awaited_once_with(
            FAKE_GOAL_ID, "Learn Python", roadmap_data, FAKE_USER_ID
        )
        mock_invalidate_caches.assert_awaited_once_with(FAKE_USER_ID, FAKE_GOAL_ID)

    async def test_goal_not_found_returns_false(
        self,
        mock_goals_collection,
    ):
        mock_goals_collection.find_one = AsyncMock(return_value=None)

        result = await update_goal_with_roadmap_service(FAKE_GOAL_ID, {"nodes": []})

        assert result is False

    async def test_exception_returns_false(
        self,
        mock_goals_collection,
    ):
        mock_goals_collection.find_one = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        result = await update_goal_with_roadmap_service(FAKE_GOAL_ID, {"nodes": []})

        assert result is False

    async def test_skips_cache_invalidation_when_no_user_id(
        self,
        mock_goals_collection,
        mock_invalidate_caches,
        mock_create_project_todo,
    ):
        """If the goal document has no user_id, cache invalidation is skipped."""
        goal_no_user = {
            "_id": FAKE_OBJECT_ID,
            "title": "Orphan Goal",
            "user_id": None,
        }
        mock_goals_collection.find_one = AsyncMock(return_value=goal_no_user)
        mock_create_project_todo.return_value = "proj_456"

        result = await update_goal_with_roadmap_service(
            FAKE_GOAL_ID, {"nodes": [], "edges": []}
        )

        assert result is True
        mock_invalidate_caches.assert_not_awaited()

    async def test_uses_untitled_goal_when_title_missing(
        self,
        mock_goals_collection,
        mock_invalidate_caches,
        mock_create_project_todo,
    ):
        """If goal has no title field, falls back to 'Untitled Goal'."""
        goal_no_title = {
            "_id": FAKE_OBJECT_ID,
            "user_id": FAKE_USER_ID,
        }
        mock_goals_collection.find_one = AsyncMock(return_value=goal_no_title)
        mock_create_project_todo.return_value = "proj_789"

        await update_goal_with_roadmap_service(FAKE_GOAL_ID, {"nodes": [], "edges": []})

        call_args = mock_create_project_todo.call_args[0]
        assert call_args[1] == "Untitled Goal"

    async def test_counts_nodes_and_edges_in_roadmap_data(
        self,
        mock_goals_collection,
        mock_invalidate_caches,
        mock_create_project_todo,
        sample_goal_doc,
    ):
        """Verify the service processes node_count and edge_count from roadmap_data."""
        mock_goals_collection.find_one = AsyncMock(return_value=sample_goal_doc)
        mock_create_project_todo.return_value = "proj_count"

        roadmap = {
            "nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}],
            "edges": [{"id": "e1"}, {"id": "e2"}],
        }
        result = await update_goal_with_roadmap_service(FAKE_GOAL_ID, roadmap)

        assert result is True


# ---------------------------------------------------------------------------
# generate_roadmap_with_llm_stream
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateRoadmapWithLlmStream:
    @staticmethod
    def _make_chunk(text: str) -> MagicMock:
        chunk = MagicMock()
        chunk.text = text
        return chunk

    async def test_yields_chunks_and_final_roadmap(self):
        roadmap = {
            "title": "Test",
            "description": "Desc",
            "nodes": [{"id": "n1", "data": {"label": "Step 1"}}],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        }
        roadmap_json = json.dumps(roadmap)

        # Build mock chunks: 15 chunks so we hit the chunk_count % 10 == 0 branch
        chunks = [self._make_chunk(c) for c in list(roadmap_json)]
        # Pad to at least 10 chunks
        while len(chunks) < 10:
            chunks.append(self._make_chunk(""))

        mock_llm = MagicMock()

        async def fake_astream(messages):
            for c in chunks:
                yield c

        mock_llm.astream = fake_astream

        with patch("app.services.goals_service.init_llm", return_value=mock_llm):
            results = []
            async for item in generate_roadmap_with_llm_stream("Learn AI"):
                results.append(item)

        # First yield is the "Starting" progress
        assert results[0]["progress"].startswith("Starting roadmap generation")

        # Should have at least one progress update with character count
        progress_msgs = [
            r
            for r in results
            if "progress" in r and "characters" in r.get("progress", "")
        ]
        assert len(progress_msgs) >= 1

        # Should have "Processing" message
        processing = [
            r
            for r in results
            if "progress" in r and "Processing" in r.get("progress", "")
        ]
        assert len(processing) == 1

        # Last two items should be completion message and roadmap
        assert results[-2]["progress"] == "Roadmap generation completed successfully!"
        assert "roadmap" in results[-1]
        assert results[-1]["roadmap"]["nodes"] == roadmap["nodes"]

    async def test_json_parsing_fails_yields_error(self):
        """When LLM produces non-JSON output, the generator yields an error."""
        mock_llm = MagicMock()

        async def fake_astream(messages):
            yield self._make_chunk("This is not JSON at all, just plain text")

        mock_llm.astream = fake_astream

        with patch("app.services.goals_service.init_llm", return_value=mock_llm):
            results = []
            async for item in generate_roadmap_with_llm_stream("Bad Goal"):
                results.append(item)

        # Should have an error about no valid JSON
        error_items = [r for r in results if "error" in r]
        assert len(error_items) >= 1
        assert "Could not parse" in error_items[0]["error"]

    async def test_json_decode_error_yields_error(self):
        """When extracted JSON is malformed, yields a JSON parse error."""
        mock_llm = MagicMock()

        async def fake_astream(messages):
            yield self._make_chunk('Here is the result: {"nodes": [broken}')

        mock_llm.astream = fake_astream

        with patch("app.services.goals_service.init_llm", return_value=mock_llm):
            results = []
            async for item in generate_roadmap_with_llm_stream("Broken JSON"):
                results.append(item)

        error_items = [r for r in results if "error" in r]
        assert len(error_items) >= 1
        assert "Failed to parse roadmap JSON" in error_items[0]["error"]

    async def test_llm_failure_yields_error(self):
        """When the LLM raises an exception, the generator yields an error."""
        mock_llm = MagicMock()

        async def fake_astream(messages):
            raise RuntimeError("LLM API down")
            yield  # NOSONAR — intentionally unreachable: makes this an async generator

        mock_llm.astream = fake_astream

        with patch("app.services.goals_service.init_llm", return_value=mock_llm):
            results = []
            async for item in generate_roadmap_with_llm_stream("Fail Goal"):
                results.append(item)

        # The initial progress is yielded before the exception in astream
        error_items = [r for r in results if "error" in r]
        assert len(error_items) >= 1
        assert "Roadmap generation failed" in error_items[0]["error"]

    async def test_missing_fields_in_parsed_json_yields_error(self):
        """Parsed JSON that lacks 'nodes' or 'edges' yields a structure error."""
        mock_llm = MagicMock()
        incomplete_json = json.dumps({"title": "Incomplete", "description": "No nodes"})

        async def fake_astream(messages):
            yield self._make_chunk(incomplete_json)

        mock_llm.astream = fake_astream

        with patch("app.services.goals_service.init_llm", return_value=mock_llm):
            results = []
            async for item in generate_roadmap_with_llm_stream("Incomplete"):
                results.append(item)

        error_items = [r for r in results if "error" in r]
        assert len(error_items) >= 1
        assert "missing required structure" in error_items[0]["error"]

    async def test_string_chunks_handled(self):
        """When LLM yields plain strings instead of objects with .text, they are handled."""
        roadmap = {
            "nodes": [{"id": "n1", "data": {"label": "S1"}}],
            "edges": [{"id": "e1"}],
        }
        roadmap_json = json.dumps(roadmap)

        mock_llm = MagicMock()

        async def fake_astream(messages):
            yield roadmap_json

        mock_llm.astream = fake_astream

        with patch("app.services.goals_service.init_llm", return_value=mock_llm):
            results = []
            async for item in generate_roadmap_with_llm_stream("String Chunks"):
                results.append(item)

        roadmap_items = [r for r in results if "roadmap" in r]
        assert len(roadmap_items) == 1

    async def test_init_llm_failure_yields_error(self):
        """When init_llm itself raises, the generator catches it."""
        with patch(
            "app.services.goals_service.init_llm",
            side_effect=RuntimeError("No API key"),
        ):
            results = []
            async for item in generate_roadmap_with_llm_stream("No LLM"):
                results.append(item)

        # The initial progress is yielded before init_llm is called
        error_items = [r for r in results if "error" in r]
        assert len(error_items) >= 1
        assert "Roadmap generation failed" in error_items[0]["error"]
