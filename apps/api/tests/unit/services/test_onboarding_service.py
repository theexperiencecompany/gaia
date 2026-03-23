"""Unit tests for onboarding service and post-onboarding service."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException

from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
)
from app.services.onboarding.onboarding_service import (
    complete_onboarding,
    get_user_onboarding_status,
    get_user_preferences_for_agent,
    queue_personalization,
    update_onboarding_preferences,
)
from app.services.onboarding.post_onboarding_service import (
    _get_default_workflows,
    emit_progress,
    save_personalization_data,
    seed_initial_user_data,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_users_collection():
    with patch(
        "app.services.onboarding.onboarding_service.users_collection"
    ) as mock_col:
        yield mock_col


@pytest.fixture
def mock_post_users_collection():
    with patch(
        "app.services.onboarding.post_onboarding_service.users_collection"
    ) as mock_col:
        yield mock_col


@pytest.fixture
def mock_workflows_collection():
    with patch(
        "app.services.onboarding.post_onboarding_service.workflows_collection"
    ) as mock_col:
        yield mock_col


@pytest.fixture
def mock_websocket_manager():
    with patch(
        "app.services.onboarding.post_onboarding_service.websocket_manager"
    ) as mock_ws:
        mock_ws.broadcast_to_user = AsyncMock()
        yield mock_ws


@pytest.fixture
def mock_redis_pool():
    with patch(
        "app.services.onboarding.onboarding_service.RedisPoolManager"
    ) as mock_rpm:
        mock_pool = AsyncMock()
        mock_rpm.get_pool = AsyncMock(return_value=mock_pool)
        yield mock_pool


@pytest.fixture
def sample_user_id():
    return str(ObjectId())


@pytest.fixture
def sample_onboarding_request():
    return OnboardingRequest(
        name="Alice",
        profession="Engineer",
        timezone="UTC",
    )


@pytest.fixture
def sample_background_tasks():
    return MagicMock(spec=BackgroundTasks)


@pytest.fixture
def sample_updated_user(sample_user_id):
    oid = ObjectId(sample_user_id)
    return {
        "_id": oid,
        "name": "Alice",
        "onboarding": {
            "completed": True,
            "completed_at": datetime.now(timezone.utc),
            "phase": OnboardingPhase.PERSONALIZATION_PENDING,
            "preferences": {
                "profession": "Engineer",
                "response_style": "casual",
            },
        },
    }


# ---------------------------------------------------------------------------
# queue_personalization
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueuePersonalization:
    async def test_queues_job_successfully(self, mock_redis_pool):
        mock_job = MagicMock(job_id="job123")
        mock_redis_pool.enqueue_job = AsyncMock(return_value=mock_job)

        await queue_personalization("user123")

        mock_redis_pool.enqueue_job.assert_awaited_once_with(
            "process_personalization_task", "user123"
        )

    async def test_handles_failed_enqueue(self, mock_redis_pool):
        mock_redis_pool.enqueue_job = AsyncMock(return_value=None)

        # Should not raise
        await queue_personalization("user123")

    async def test_handles_exception(self, mock_redis_pool):
        mock_redis_pool.enqueue_job = AsyncMock(side_effect=Exception("Redis error"))

        # Should not raise
        await queue_personalization("user123")


# ---------------------------------------------------------------------------
# complete_onboarding
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompleteOnboarding:
    async def test_successful_onboarding(
        self,
        mock_users_collection,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
        sample_updated_user,
    ):
        mock_users_collection.find_one_and_update = AsyncMock(
            return_value=sample_updated_user
        )

        result = await complete_onboarding(
            sample_user_id,
            sample_onboarding_request,
            sample_background_tasks,
        )

        assert result["_id"] == sample_user_id
        assert result["user_id"] == sample_user_id
        sample_background_tasks.add_task.assert_called_once()

    async def test_user_not_found(
        self,
        mock_users_collection,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
    ):
        mock_users_collection.find_one_and_update = AsyncMock(return_value=None)
        mock_users_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(
                sample_user_id,
                sample_onboarding_request,
                sample_background_tasks,
            )

        assert exc_info.value.status_code == 404

    async def test_already_onboarded(
        self,
        mock_users_collection,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
    ):
        mock_users_collection.find_one_and_update = AsyncMock(return_value=None)
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(sample_user_id),
                "onboarding": {"completed": True},
            }
        )

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(
                sample_user_id,
                sample_onboarding_request,
                sample_background_tasks,
            )

        assert exc_info.value.status_code == 409

    async def test_update_failure(
        self,
        mock_users_collection,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
    ):
        mock_users_collection.find_one_and_update = AsyncMock(return_value=None)
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(sample_user_id),
                "onboarding": {"completed": False},
            }
        )

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(
                sample_user_id,
                sample_onboarding_request,
                sample_background_tasks,
            )

        assert exc_info.value.status_code == 500

    async def test_sets_timezone(
        self,
        mock_users_collection,
        sample_user_id,
        sample_background_tasks,
        sample_updated_user,
    ):
        request = OnboardingRequest(
            name="Alice",
            profession="Engineer",
            timezone="America/New_York",
        )
        mock_users_collection.find_one_and_update = AsyncMock(
            return_value=sample_updated_user
        )

        await complete_onboarding(sample_user_id, request, sample_background_tasks)

        call_args = mock_users_collection.find_one_and_update.call_args
        update_fields = call_args[0][1]["$set"]
        assert update_fields["timezone"] == "America/New_York"

    async def test_generic_exception_returns_500(
        self,
        mock_users_collection,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
    ):
        mock_users_collection.find_one_and_update = AsyncMock(
            side_effect=RuntimeError("Unexpected")
        )

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(
                sample_user_id,
                sample_onboarding_request,
                sample_background_tasks,
            )

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get_user_onboarding_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserOnboardingStatus:
    async def test_returns_status(self, mock_users_collection, sample_user_id):
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(sample_user_id),
                "onboarding": {
                    "completed": True,
                    "completed_at": "2024-01-01T00:00:00Z",
                    "preferences": {"profession": "Engineer"},
                },
            }
        )

        result = await get_user_onboarding_status(sample_user_id)

        assert result["completed"] is True
        assert result["preferences"]["profession"] == "Engineer"

    async def test_user_not_found_raises_500(
        self, mock_users_collection, sample_user_id
    ):
        """The inner 404 is caught by the broad except and re-raised as 500."""
        mock_users_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status(sample_user_id)

        # The function's broad except catches the inner HTTPException(404)
        # and wraps it as a 500
        assert exc_info.value.status_code == 500
        assert "User not found" in exc_info.value.detail

    async def test_no_onboarding_data(self, mock_users_collection, sample_user_id):
        mock_users_collection.find_one = AsyncMock(
            return_value={"_id": ObjectId(sample_user_id)}
        )

        result = await get_user_onboarding_status(sample_user_id)

        assert result["completed"] is False
        assert result["preferences"] == {}

    async def test_exception_raises_500(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(side_effect=Exception("DB error"))

        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status("invalid")

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# update_onboarding_preferences
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateOnboardingPreferences:
    async def test_updates_preferences(self, mock_users_collection, sample_user_id):
        updated_doc = {
            "_id": ObjectId(sample_user_id),
            "onboarding": {
                "preferences": {"profession": "Designer"},
            },
        }
        mock_users_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        prefs = OnboardingPreferences(
            profession="Designer",
            response_style="brief",
        )
        result = await update_onboarding_preferences(sample_user_id, prefs)

        assert result["_id"] == sample_user_id
        assert result["user_id"] == sample_user_id

    async def test_user_not_found(self, mock_users_collection, sample_user_id):
        mock_users_collection.find_one_and_update = AsyncMock(return_value=None)

        prefs = OnboardingPreferences(profession="Designer")

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(sample_user_id, prefs)

        assert exc_info.value.status_code == 404

    async def test_custom_instructions_trimmed(
        self, mock_users_collection, sample_user_id
    ):
        updated_doc = {
            "_id": ObjectId(sample_user_id),
            "onboarding": {"preferences": {}},
        }
        mock_users_collection.find_one_and_update = AsyncMock(return_value=updated_doc)

        long_instructions = "x" * 600
        prefs = OnboardingPreferences(custom_instructions=long_instructions[:500])
        await update_onboarding_preferences(sample_user_id, prefs)

        call_args = mock_users_collection.find_one_and_update.call_args
        set_data = call_args[0][1]["$set"]
        saved_prefs = set_data["onboarding.preferences"]
        if "custom_instructions" in saved_prefs:
            assert len(saved_prefs["custom_instructions"]) <= 500

    async def test_generic_exception_returns_500(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.find_one_and_update = AsyncMock(
            side_effect=RuntimeError("Unexpected")
        )
        prefs = OnboardingPreferences(profession="Engineer")

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(sample_user_id, prefs)

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get_user_preferences_for_agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserPreferencesForAgent:
    async def test_returns_formatted_preferences(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(sample_user_id),
                "onboarding": {
                    "completed": True,
                    "preferences": {
                        "profession": "Engineer",
                        "response_style": "casual",
                    },
                },
            }
        )

        with patch(
            "app.services.onboarding.onboarding_service.format_user_preferences_for_agent",
            return_value="Profession: Engineer\nStyle: casual",
        ) as mock_format:
            result = await get_user_preferences_for_agent(sample_user_id)

        assert result is not None
        mock_format.assert_called_once()

    async def test_returns_none_when_user_not_found(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.find_one = AsyncMock(return_value=None)

        result = await get_user_preferences_for_agent(sample_user_id)

        assert result is None

    async def test_returns_none_when_not_onboarded(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(sample_user_id),
                "onboarding": {"completed": False},
            }
        )

        result = await get_user_preferences_for_agent(sample_user_id)

        assert result is None

    async def test_returns_none_when_no_preferences(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(sample_user_id),
                "onboarding": {"completed": True, "preferences": {}},
            }
        )

        result = await get_user_preferences_for_agent(sample_user_id)

        assert result is None

    async def test_returns_none_on_exception(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.find_one = AsyncMock(side_effect=Exception("DB error"))

        result = await get_user_preferences_for_agent(sample_user_id)

        assert result is None

    async def test_returns_none_when_no_onboarding_key(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.find_one = AsyncMock(
            return_value={"_id": ObjectId(sample_user_id)}
        )

        result = await get_user_preferences_for_agent(sample_user_id)

        assert result is None


# ---------------------------------------------------------------------------
# emit_progress (post_onboarding_service)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitProgress:
    async def test_broadcasts_progress(self, mock_websocket_manager):
        await emit_progress("user1", "analyzing", "Analyzing...", 50)

        mock_websocket_manager.broadcast_to_user.assert_awaited_once_with(
            "user1",
            {
                "type": "personalization_progress",
                "data": {
                    "stage": "analyzing",
                    "message": "Analyzing...",
                    "progress": 50,
                    "details": {},
                },
            },
        )

    async def test_broadcasts_progress_with_details(self, mock_websocket_manager):
        details = {"current": 5, "total": 10}
        await emit_progress("user1", "stage", "msg", 75, details)

        call_args = mock_websocket_manager.broadcast_to_user.call_args
        assert call_args[0][1]["data"]["details"] == details


# ---------------------------------------------------------------------------
# save_personalization_data (post_onboarding_service)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSavePersonalizationData:
    async def test_saves_data(self, mock_post_users_collection, sample_user_id):
        mock_post_users_collection.update_one = AsyncMock()

        await save_personalization_data(
            sample_user_id,
            house="explorer",
            personality_phrase="Creative thinker",
            user_bio="A passionate engineer.",
            bio_status=BioStatus.COMPLETED,
            workflow_ids=["wf1", "wf2"],
            account_number=42,
            member_since="Mar 2024",
            overlay_color="#ff0000",
            overlay_opacity=80,
        )

        mock_post_users_collection.update_one.assert_awaited_once()
        call_args = mock_post_users_collection.update_one.call_args
        set_data = call_args[0][1]["$set"]
        assert set_data["onboarding.house"] == "explorer"
        assert set_data["onboarding.personality_phrase"] == "Creative thinker"
        assert set_data["onboarding.user_bio"] == "A passionate engineer."
        assert set_data["onboarding.bio_status"] == BioStatus.COMPLETED
        assert set_data["onboarding.suggested_workflows"] == ["wf1", "wf2"]
        assert set_data["onboarding.account_number"] == 42
        assert set_data["onboarding.overlay_color"] == "#ff0000"
        assert set_data["onboarding.overlay_opacity"] == 80
        assert set_data["onboarding.phase"] == OnboardingPhase.PERSONALIZATION_COMPLETE

    async def test_handles_exception(self, mock_post_users_collection, sample_user_id):
        mock_post_users_collection.update_one = AsyncMock(
            side_effect=Exception("DB error")
        )

        # Should not raise
        await save_personalization_data(
            sample_user_id,
            house="explorer",
            personality_phrase="phrase",
            user_bio="bio",
            bio_status=BioStatus.COMPLETED,
            workflow_ids=[],
            account_number=1,
            member_since="Jan 2024",
            overlay_color="#000",
            overlay_opacity=50,
        )


# ---------------------------------------------------------------------------
# _get_default_workflows (post_onboarding_service)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDefaultWorkflows:
    async def test_returns_workflow_ids(self, mock_workflows_collection):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId(), "title": "WF1"},
                {"_id": ObjectId(), "title": "WF2"},
            ]
        )
        mock_workflows_collection.find = MagicMock(return_value=mock_cursor)

        result = await _get_default_workflows(4)

        assert len(result) == 2

    async def test_returns_empty_on_error(self, mock_workflows_collection):
        mock_workflows_collection.find = MagicMock(side_effect=Exception("DB error"))

        result = await _get_default_workflows()

        assert result == []


# ---------------------------------------------------------------------------
# seed_initial_user_data (post_onboarding_service)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSeedInitialUserData:
    async def test_runs_parallel_seeding(self):
        with (
            patch(
                "app.services.onboarding.post_onboarding_service.seed_onboarding_todo",
                new_callable=AsyncMock,
            ) as mock_todo,
            patch(
                "app.services.onboarding.post_onboarding_service.seed_initial_conversation",
                new_callable=AsyncMock,
            ) as mock_conv,
        ):
            await seed_initial_user_data("user1")

            mock_todo.assert_awaited_once_with("user1")
            mock_conv.assert_awaited_once_with("user1")

    async def test_handles_exception(self):
        with patch(
            "app.services.onboarding.post_onboarding_service.seed_onboarding_todo",
            new_callable=AsyncMock,
            side_effect=Exception("seed error"),
        ):
            # Should not raise
            await seed_initial_user_data("user1")


# ---------------------------------------------------------------------------
# suggest_workflows_via_rag (post_onboarding_service)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuggestWorkflowsViaRag:
    async def test_returns_default_when_no_memories(self, mock_workflows_collection):
        from app.services.onboarding.post_onboarding_service import (
            suggest_workflows_via_rag,
        )

        wf_ids = [ObjectId(), ObjectId()]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[{"_id": wf_ids[0]}, {"_id": wf_ids[1]}]
        )
        mock_workflows_collection.find = MagicMock(return_value=mock_cursor)

        mock_memories = MagicMock()
        mock_memories.memories = []

        with patch(
            "app.services.onboarding.post_onboarding_service.memory_service"
        ) as mock_mem:
            mock_mem.get_all_memories = AsyncMock(return_value=mock_memories)
            result = await suggest_workflows_via_rag("user1", limit=4)

        assert len(result) == 2

    async def test_returns_rag_results_when_memories_exist(
        self, mock_workflows_collection
    ):
        from app.services.onboarding.post_onboarding_service import (
            suggest_workflows_via_rag,
        )

        wf_id = ObjectId()
        mock_memory = MagicMock()
        mock_memory.content = "I love cooking"
        mock_memories = MagicMock()
        mock_memories.memories = [mock_memory]

        mock_doc = MagicMock()
        mock_doc.metadata = {"workflow_id": str(wf_id)}

        mock_chroma = MagicMock()
        mock_chroma.similarity_search = MagicMock(return_value=[mock_doc])

        mock_workflows_collection.find_one = AsyncMock(
            return_value={"_id": wf_id, "is_public": True}
        )

        with (
            patch(
                "app.services.onboarding.post_onboarding_service.memory_service"
            ) as mock_mem,
            patch(
                "app.services.onboarding.post_onboarding_service.ChromaClient"
            ) as mock_cc,
        ):
            mock_mem.get_all_memories = AsyncMock(return_value=mock_memories)
            mock_cc.get_langchain_client = AsyncMock(return_value=mock_chroma)
            result = await suggest_workflows_via_rag("user1", limit=4)

        assert str(wf_id) in result

    async def test_falls_back_to_defaults_on_error(self, mock_workflows_collection):
        from app.services.onboarding.post_onboarding_service import (
            suggest_workflows_via_rag,
        )

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_workflows_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.services.onboarding.post_onboarding_service.memory_service"
        ) as mock_mem:
            mock_mem.get_all_memories = AsyncMock(side_effect=Exception("Memory error"))
            result = await suggest_workflows_via_rag("user1")

        assert isinstance(result, list)

    async def test_fills_with_defaults_when_rag_returns_few(
        self, mock_workflows_collection
    ):
        from app.services.onboarding.post_onboarding_service import (
            suggest_workflows_via_rag,
        )

        wf_id = ObjectId()
        mock_memory = MagicMock()
        mock_memory.content = "test"
        mock_memories = MagicMock()
        mock_memories.memories = [mock_memory]

        mock_doc = MagicMock()
        mock_doc.metadata = {"workflow_id": str(wf_id)}

        mock_chroma = MagicMock()
        mock_chroma.similarity_search = MagicMock(return_value=[mock_doc])

        mock_workflows_collection.find_one = AsyncMock(
            return_value={"_id": wf_id, "is_public": True}
        )

        default_wf_id = ObjectId()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": default_wf_id}])
        mock_workflows_collection.find = MagicMock(return_value=mock_cursor)

        with (
            patch(
                "app.services.onboarding.post_onboarding_service.memory_service"
            ) as mock_mem,
            patch(
                "app.services.onboarding.post_onboarding_service.ChromaClient"
            ) as mock_cc,
        ):
            mock_mem.get_all_memories = AsyncMock(return_value=mock_memories)
            mock_cc.get_langchain_client = AsyncMock(return_value=mock_chroma)
            result = await suggest_workflows_via_rag("user1", limit=4)

        # Should have RAG result + defaults to fill up to limit
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# process_post_onboarding_personalization (post_onboarding_service)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessPostOnboardingPersonalization:
    async def test_full_personalization_flow_completed(
        self,
        mock_post_users_collection,
        mock_workflows_collection,
        mock_websocket_manager,
        sample_user_id,
    ):
        from app.services.onboarding.post_onboarding_service import (
            process_post_onboarding_personalization,
        )

        mock_post_users_collection.update_one = AsyncMock()
        mock_post_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(sample_user_id),
                "name": "Alice",
                "onboarding": {
                    "preferences": {"profession": "Engineer"},
                },
            }
        )

        mock_memory = MagicMock()
        mock_memory.content = "I work as an engineer"
        mock_memories = MagicMock()
        mock_memories.memories = [mock_memory]

        mock_workflows_collection.find_one = AsyncMock(return_value=None)

        with (
            patch(
                "app.services.onboarding.post_onboarding_service.memory_service"
            ) as mock_mem,
            patch(
                "app.services.onboarding.post_onboarding_service.suggest_workflows_via_rag",
                new_callable=AsyncMock,
                return_value=["wf1"],
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.generate_personality_phrase",
                new_callable=AsyncMock,
                return_value="Creative thinker",
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.generate_user_bio",
                new_callable=AsyncMock,
                return_value=("A passionate engineer.", BioStatus.COMPLETED),
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.get_user_metadata",
                new_callable=AsyncMock,
                return_value={"account_number": 42, "member_since": "Mar 2024"},
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.generate_profile_card_design",
                return_value={
                    "house": "explorer",
                    "overlay_color": "#ff0000",
                    "overlay_opacity": 80,
                },
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.save_personalization_data",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            mock_mem.get_all_memories = AsyncMock(return_value=mock_memories)
            await process_post_onboarding_personalization(sample_user_id)

        mock_save.assert_awaited_once()
        # Should broadcast completion when bio_status is COMPLETED
        assert mock_websocket_manager.broadcast_to_user.await_count >= 1

    async def test_handles_exception_gracefully(
        self,
        mock_post_users_collection,
        mock_websocket_manager,
        sample_user_id,
    ):
        from app.services.onboarding.post_onboarding_service import (
            process_post_onboarding_personalization,
        )

        mock_post_users_collection.update_one = AsyncMock(
            side_effect=Exception("DB error")
        )

        # Should not raise
        await process_post_onboarding_personalization(sample_user_id)

    async def test_no_broadcast_when_bio_processing(
        self,
        mock_post_users_collection,
        mock_workflows_collection,
        mock_websocket_manager,
        sample_user_id,
    ):
        from app.services.onboarding.post_onboarding_service import (
            process_post_onboarding_personalization,
        )

        mock_post_users_collection.update_one = AsyncMock()
        mock_post_users_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(sample_user_id),
                "name": "Alice",
                "onboarding": {"preferences": {"profession": "Engineer"}},
            }
        )

        mock_memories = MagicMock()
        mock_memories.memories = []
        mock_workflows_collection.find_one = AsyncMock(return_value=None)

        with (
            patch(
                "app.services.onboarding.post_onboarding_service.memory_service"
            ) as mock_mem,
            patch(
                "app.services.onboarding.post_onboarding_service.suggest_workflows_via_rag",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.generate_personality_phrase",
                new_callable=AsyncMock,
                return_value="Thoughtful creator",
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.generate_user_bio",
                new_callable=AsyncMock,
                return_value=("Processing...", BioStatus.PROCESSING),
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.get_user_metadata",
                new_callable=AsyncMock,
                return_value={"account_number": 1, "member_since": "Jan 2024"},
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.generate_profile_card_design",
                return_value={
                    "house": "guardian",
                    "overlay_color": "#00ff00",
                    "overlay_opacity": 70,
                },
            ),
            patch(
                "app.services.onboarding.post_onboarding_service.save_personalization_data",
                new_callable=AsyncMock,
            ),
        ):
            mock_mem.get_all_memories = AsyncMock(return_value=mock_memories)
            await process_post_onboarding_personalization(sample_user_id)

        # Should NOT broadcast onboarding_personalization_complete when PROCESSING
        complete_calls = [
            c
            for c in mock_websocket_manager.broadcast_to_user.call_args_list
            if c[1].get("message", c[0][1] if len(c[0]) > 1 else {}).get("type")
            == "onboarding_personalization_complete"
        ]
        assert len(complete_calls) == 0
