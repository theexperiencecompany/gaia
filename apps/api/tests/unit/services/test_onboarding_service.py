"""Unit tests for onboarding service and post-onboarding service."""

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException
import pytest

from app.constants.log_tags import LogTag
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    UserDocument,
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


@pytest.fixture
def mock_repo():
    with patch("app.services.onboarding.onboarding_service.user_repository") as repo:
        repo.complete_onboarding = AsyncMock()
        repo.get = AsyncMock()
        repo.clear_onboarding = AsyncMock()
        repo.update_onboarding_preferences = AsyncMock()
        yield repo


@pytest.fixture
def mock_save_personalization():
    with patch(
        "app.services.onboarding.post_onboarding_service.user_repository.save_personalization",
        new_callable=AsyncMock,
    ) as mock_save:
        yield mock_save


@pytest.fixture
def sample_user_id():
    return str(ObjectId())


@pytest.fixture
def sample_onboarding_request():
    return OnboardingRequest(name="Alice", profession="Engineer", timezone="UTC")


@pytest.fixture
def sample_background_tasks():
    return MagicMock(spec=BackgroundTasks)


@pytest.fixture
def mock_enqueue_intelligence_job():
    with patch(
        "app.services.onboarding.onboarding_service.enqueue_intelligence_job",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        yield mock_enqueue


@pytest.fixture
def sample_user(sample_user_id):
    return UserDocument.model_validate(
        {
            "id": sample_user_id,
            "name": "Alice",
            "onboarding": {
                "completed": True,
                "phase": OnboardingPhase.PERSONALIZATION_PENDING,
                "preferences": {"profession": "Engineer", "response_style": "casual"},
            },
        }
    )


class TestCompleteOnboarding:
    async def test_successful_onboarding(
        self,
        mock_repo,
        mock_enqueue_intelligence_job,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
        sample_user,
    ):
        mock_repo.complete_onboarding.return_value = sample_user

        result = await complete_onboarding(
            sample_user_id, sample_onboarding_request, sample_background_tasks
        )

        assert result["_id"] == sample_user_id
        assert result["user_id"] == sample_user_id
        mock_enqueue_intelligence_job.assert_awaited_once_with(sample_user_id)
        sample_background_tasks.add_task.assert_called_once()

    async def test_user_not_found(
        self, mock_repo, sample_user_id, sample_onboarding_request, sample_background_tasks
    ):
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )
        assert exc_info.value.status_code == 404

    async def test_already_onboarded_replays_idempotently(
        self,
        mock_repo,
        sample_user,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
    ):
        # The atomic gate makes a repeat submission a no-op: complete_onboarding
        # returns None and the existing user is returned unchanged.
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = sample_user

        result = await complete_onboarding(
            sample_user_id, sample_onboarding_request, sample_background_tasks
        )

        assert result["_id"] == sample_user_id
        sample_background_tasks.add_task.assert_not_called()

    async def test_enqueue_failure_rolls_back_and_raises_503(
        self,
        mock_repo,
        sample_user,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
    ):
        mock_repo.complete_onboarding.return_value = sample_user

        with patch(
            "app.services.onboarding.onboarding_service.enqueue_intelligence_job",
            new_callable=AsyncMock,
            side_effect=RuntimeError("queue down"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await complete_onboarding(
                    sample_user_id, sample_onboarding_request, sample_background_tasks
                )

        assert exc_info.value.status_code == 503
        mock_repo.clear_onboarding.assert_awaited_once_with(sample_user_id)
        sample_background_tasks.add_task.assert_not_called()

    async def test_sets_timezone(
        self,
        mock_repo,
        mock_enqueue_intelligence_job,
        sample_user_id,
        sample_background_tasks,
        sample_user,
    ):
        request = OnboardingRequest(
            name="Alice", profession="Engineer", timezone="America/New_York"
        )
        mock_repo.complete_onboarding.return_value = sample_user

        await complete_onboarding(sample_user_id, request, sample_background_tasks)

        assert mock_repo.complete_onboarding.call_args.kwargs["timezone"] == "America/New_York"

    async def test_generic_exception_returns_500(
        self, mock_repo, sample_user_id, sample_onboarding_request, sample_background_tasks
    ):
        mock_repo.complete_onboarding.side_effect = RuntimeError("Unexpected")

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )
        assert exc_info.value.status_code == 500


class TestGetUserOnboardingStatus:
    async def test_returns_status(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = UserDocument.model_validate(
            {
                "id": sample_user_id,
                "onboarding": {
                    "completed": True,
                    "completed_at": "2024-01-01T00:00:00Z",
                    "preferences": {"profession": "Engineer"},
                },
            }
        )

        result = await get_user_onboarding_status(sample_user_id)

        assert result.completed is True
        assert result.preferences.profession == "Engineer"

    async def test_user_not_found_raises_404(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status(sample_user_id)
        assert exc_info.value.status_code == 404
        assert "User not found" in exc_info.value.detail

    async def test_no_onboarding_data(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = UserDocument.model_validate({"id": sample_user_id})

        result = await get_user_onboarding_status(sample_user_id)

        assert result.completed is False
        assert result.preferences.profession is None

    async def test_exception_raises_500(self, mock_repo):
        mock_repo.get.side_effect = Exception("DB error")

        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status("invalid")
        assert exc_info.value.status_code == 500


class TestUpdateOnboardingPreferences:
    async def test_updates_preferences(self, mock_repo, sample_user_id):
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id, "onboarding": {"preferences": {"profession": "Designer"}}}
        )

        prefs = OnboardingPreferences(profession="Designer", response_style="brief")
        result = await update_onboarding_preferences(sample_user_id, prefs)

        assert result["_id"] == sample_user_id
        assert result["user_id"] == sample_user_id

    async def test_user_not_found(self, mock_repo, sample_user_id):
        mock_repo.update_onboarding_preferences.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(
                sample_user_id, OnboardingPreferences(profession="Designer")
            )
        assert exc_info.value.status_code == 404

    async def test_partial_patch_merges_only_sent_fields(self, mock_repo, sample_user_id):
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id, "onboarding": {"preferences": {}}}
        )

        # Only custom_instructions is provided — the patch must carry only that key.
        prefs = OnboardingPreferences(custom_instructions="Focus on email")
        await update_onboarding_preferences(sample_user_id, prefs)

        # The repository writes model_dump(exclude_unset=True) as the $set, so the
        # unsent fields must be absent from the model's set-fields, not merely None.
        patch_arg = mock_repo.update_onboarding_preferences.call_args[0][1]
        assert patch_arg.model_dump(exclude_unset=True) == {"custom_instructions": "Focus on email"}

    async def test_generic_exception_returns_500(self, mock_repo, sample_user_id):
        mock_repo.update_onboarding_preferences.side_effect = RuntimeError("Unexpected")

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(
                sample_user_id, OnboardingPreferences(profession="Engineer")
            )
        assert exc_info.value.status_code == 500


class TestSavePersonalizationData:
    async def test_saves_data(self, mock_save_personalization, sample_user_id):
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

        mock_save_personalization.assert_awaited_once()
        kwargs = mock_save_personalization.call_args.kwargs
        assert kwargs["house"] == "explorer"
        assert kwargs["personality_phrase"] == "Creative thinker"
        assert kwargs["user_bio"] == "A passionate engineer."
        assert kwargs["bio_status"] == BioStatus.COMPLETED
        assert kwargs["workflow_ids"] == ["wf1", "wf2"]
        assert kwargs["account_number"] == 42
        assert kwargs["overlay_color"] == "#ff0000"
        assert kwargs["overlay_opacity"] == 80

    async def test_handles_exception(self, mock_save_personalization, sample_user_id):
        mock_save_personalization.side_effect = Exception("DB error")

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


class TestSeedInitialUserData:
    async def test_seeds_onboarding_todo(self):
        with patch(
            "app.services.onboarding.post_onboarding_service.seed_onboarding_todo",
            new_callable=AsyncMock,
        ) as mock_todo:
            await seed_initial_user_data("user1")
            mock_todo.assert_awaited_once_with("user1")

    async def test_handles_exception(self):
        with patch(
            "app.services.onboarding.post_onboarding_service.seed_onboarding_todo",
            new_callable=AsyncMock,
            side_effect=Exception("seed error"),
        ):
            await seed_initial_user_data("user1")


class TestOnboardingServiceLogPins:
    """Exact pins for log calls and error paths the flow tests don't assert."""

    async def test_complete_onboarding_success_log_is_exact(
        self,
        mock_repo,
        mock_enqueue_intelligence_job,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
        sample_user,
    ):
        mock_repo.complete_onboarding.return_value = sample_user
        with patch("app.services.onboarding.onboarding_service.log") as log:
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )

        log.set.assert_called_once_with(auth={"user_id": sample_user_id})
        log.info.assert_any_call(
            f"{LogTag.ONBOARDING} Onboarding completed successfully for user",
            user_id=sample_user_id,
        )

    async def test_complete_onboarding_replay_log_is_exact(
        self,
        mock_repo,
        mock_enqueue_intelligence_job,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
        sample_user,
    ):
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = sample_user
        with patch("app.services.onboarding.onboarding_service.log") as log:
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )

        replay_logs = [
            c
            for c in log.info.call_args_list
            if "replay — onboarding already submitted" in str(c.args[0])
        ]
        assert len(replay_logs) == 1
        assert replay_logs[0].kwargs["user_id"] == sample_user_id

    async def test_enqueue_failure_rolls_back_with_exact_error_log(
        self,
        mock_repo,
        sample_user_id,
        sample_onboarding_request,
        sample_background_tasks,
        sample_user,
    ):
        mock_repo.complete_onboarding.return_value = sample_user
        with (
            patch(
                "app.services.onboarding.onboarding_service.enqueue_intelligence_job",
                new_callable=AsyncMock,
                side_effect=RuntimeError("queue down"),
            ),
            patch("app.services.onboarding.onboarding_service.log") as log,
            pytest.raises(HTTPException) as exc_info,
        ):
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Could not start onboarding. Please retry."
        mock_repo.clear_onboarding.assert_awaited_once_with(sample_user_id)
        enqueue_errors = [c for c in log.error.call_args_list if "Enqueue failed" in str(c.args[0])]
        assert len(enqueue_errors) == 1
        assert enqueue_errors[0].kwargs["error"] == "queue down"
        assert enqueue_errors[0].kwargs["error_type"] == "RuntimeError"

    async def test_get_status_returns_every_field_from_the_document(
        self, mock_repo, sample_user_id
    ):
        user = UserDocument.model_validate(
            {
                "id": sample_user_id,
                "name": "Alice",
                "onboarding": {
                    "completed": True,
                    "completed_at": "2025-01-01T00:00:00Z",
                    "phase": OnboardingPhase.PERSONALIZATION_PENDING.value,
                    "preferences": {"profession": "Engineer", "response_style": "casual"},
                    "first_message_conversation_id": "conv-9",
                },
            }
        )
        mock_repo.get.return_value = user

        status = await get_user_onboarding_status(sample_user_id)

        assert status.completed is True
        assert status.phase == OnboardingPhase.PERSONALIZATION_PENDING
        assert status.preferences.profession == "Engineer"
        assert status.first_message_conversation_id == "conv-9"

    async def test_get_status_generic_error_raises_500_with_exact_detail(
        self, mock_repo, sample_user_id
    ):
        mock_repo.get.side_effect = RuntimeError("mongo down")
        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status(sample_user_id)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "An internal error occurred"

    async def test_update_preferences_success_log_is_exact(self, mock_repo, sample_user_id):
        updated = UserDocument(id=sample_user_id, name="Alice")
        mock_repo.update_onboarding_preferences.return_value = updated
        prefs = OnboardingPreferences(profession="Writer", response_style="formal")

        with patch("app.services.onboarding.onboarding_service.log") as log:
            await update_onboarding_preferences(sample_user_id, prefs)

        log.info.assert_called_once_with(
            f"{LogTag.ONBOARDING} Onboarding preferences updated successfully for user",
            user_id=sample_user_id,
        )
        mock_repo.update_onboarding_preferences.assert_awaited_once_with(sample_user_id, prefs)

    async def test_update_preferences_generic_error_raises_500_with_exact_detail(
        self, mock_repo, sample_user_id
    ):
        mock_repo.update_onboarding_preferences.side_effect = RuntimeError("db down")
        prefs = OnboardingPreferences(profession="Writer", response_style="formal")

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(sample_user_id, prefs)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to update preferences"
