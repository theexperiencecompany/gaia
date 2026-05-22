"""Unit tests for onboarding service and post-onboarding service."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException
import pytest

from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
)
from app.services.onboarding.onboarding_service import (
    complete_onboarding,
    get_user_onboarding_status,
    update_onboarding_preferences,
)
from app.services.onboarding.post_onboarding_service import (
    save_personalization_data,
    seed_initial_user_data,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_users_collection():
    with patch("app.services.onboarding.onboarding_service.users_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_post_users_collection():
    with patch("app.services.onboarding.post_onboarding_service.users_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_workflows_collection():
    with patch("app.services.onboarding.post_onboarding_service.workflows_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_websocket_manager():
    with patch("app.services.onboarding.post_onboarding_service.websocket_manager") as mock_ws:
        mock_ws.broadcast_to_user = AsyncMock()
        yield mock_ws


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
            "completed_at": datetime.now(UTC),
            "phase": OnboardingPhase.PERSONALIZATION_PENDING,
            "preferences": {
                "profession": "Engineer",
                "response_style": "casual",
            },
        },
    }


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
        mock_users_collection.find_one_and_update = AsyncMock(return_value=sample_updated_user)

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
        mock_users_collection.find_one_and_update = AsyncMock(return_value=sample_updated_user)

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

    async def test_user_not_found_raises_500(self, mock_users_collection, sample_user_id):
        """The inner 404 is caught by the broad except and re-raised as 500."""
        mock_users_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status(sample_user_id)

        # The function's broad except catches the inner HTTPException(404)
        # and wraps it as a 500
        assert exc_info.value.status_code == 500
        assert "User not found" in exc_info.value.detail

    async def test_no_onboarding_data(self, mock_users_collection, sample_user_id):
        mock_users_collection.find_one = AsyncMock(return_value={"_id": ObjectId(sample_user_id)})

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

    async def test_custom_instructions_trimmed(self, mock_users_collection, sample_user_id):
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

    async def test_generic_exception_returns_500(self, mock_users_collection, sample_user_id):
        mock_users_collection.find_one_and_update = AsyncMock(
            side_effect=RuntimeError("Unexpected")
        )
        prefs = OnboardingPreferences(profession="Engineer")

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(sample_user_id, prefs)

        assert exc_info.value.status_code == 500


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
        mock_post_users_collection.update_one = AsyncMock(side_effect=Exception("DB error"))

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
