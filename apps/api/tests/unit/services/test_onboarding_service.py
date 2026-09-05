"""Unit tests for onboarding service and post-onboarding service."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, call, patch

from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException
import pytest

from app.constants.log_tags import LogTag
from app.models.onboarding_models import OnboardingCompletion, PersonalizationBundle
from app.models.user_models import (
    BioStatus,
    ClarifyAnswer,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    UserDocument,
)
from app.services.onboarding.onboarding_service import (
    _seed_goal_memory,
    complete_onboarding,
    get_user_onboarding_status,
    update_onboarding_preferences,
)
from app.services.onboarding.post_onboarding_service import (
    save_personalization_data,
    seed_initial_user_data,
)
from app.services.system_workflows.provisioner import provision_briefing_workflows


@pytest.fixture
def mock_repo() -> Iterator[MagicMock]:
    with patch("app.services.onboarding.onboarding_service.user_repository") as repo:
        repo.complete_onboarding = AsyncMock()
        repo.get = AsyncMock()
        repo.clear_onboarding = AsyncMock()
        repo.update_onboarding_preferences = AsyncMock()
        yield repo


@pytest.fixture
def mock_save_personalization() -> Iterator[AsyncMock]:
    with patch(
        "app.services.onboarding.post_onboarding_service.user_repository.save_personalization",
        new_callable=AsyncMock,
    ) as mock_save:
        yield mock_save


@pytest.fixture
def sample_user_id() -> str:
    return str(ObjectId())


@pytest.fixture
def sample_onboarding_request() -> OnboardingRequest:
    return OnboardingRequest(name="Alice", profession="Engineer", timezone="UTC")


@pytest.fixture
def sample_background_tasks() -> BackgroundTasks:
    return MagicMock(spec=BackgroundTasks)


@pytest.fixture
def mock_enqueue_intelligence_job() -> Iterator[AsyncMock]:
    with patch(
        "app.services.onboarding.onboarding_service.enqueue_intelligence_job",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        yield mock_enqueue


@pytest.fixture
def sample_user(sample_user_id: str) -> UserDocument:
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
        mock_repo: MagicMock,
        mock_enqueue_intelligence_job: AsyncMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user

        result = await complete_onboarding(
            sample_user_id, sample_onboarding_request, sample_background_tasks
        )

        assert result["_id"] == sample_user_id
        assert result["user_id"] == sample_user_id
        mock_enqueue_intelligence_job.assert_awaited_once_with(sample_user_id)
        # Deferred work: seed user data + provision briefing workflows. A goal
        # memory seed is only scheduled when the request carries a focus.
        expected_calls = [
            call(seed_initial_user_data, sample_user_id),
            call(provision_briefing_workflows, sample_user_id),
        ]
        sample_background_tasks.add_task.assert_has_calls(expected_calls)
        assert sample_background_tasks.add_task.call_count == len(expected_calls)

    async def test_user_not_found(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
    ) -> None:
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"

    async def test_already_onboarded_replays_idempotently(
        self,
        mock_repo: MagicMock,
        sample_user,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
    ) -> None:
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
        mock_repo: MagicMock,
        sample_user,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
    ) -> None:
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
        mock_repo: MagicMock,
        mock_enqueue_intelligence_job: AsyncMock,
        sample_user_id: str,
        sample_background_tasks: BackgroundTasks,
        sample_user: UserDocument,
    ) -> None:
        request = OnboardingRequest(
            name="Alice", profession="Engineer", timezone="America/New_York"
        )
        mock_repo.complete_onboarding.return_value = sample_user

        await complete_onboarding(sample_user_id, request, sample_background_tasks)

        completion = mock_repo.complete_onboarding.call_args.args[1]
        assert completion.timezone == "America/New_York"

    async def test_passes_exact_normalized_kwargs_to_repository(
        self,
        mock_repo: MagicMock,
        mock_enqueue_intelligence_job: AsyncMock,
        sample_user_id: str,
        sample_background_tasks: BackgroundTasks,
        sample_user: UserDocument,
    ) -> None:
        request = OnboardingRequest(
            name="Alice",
            profession="Engineer",
            timezone="UTC",
            focus="  ship the product  ",
            clarify_answers=[
                ClarifyAnswer(
                    id="scope",
                    kind="scope",
                    question="What should GAIA take off your plate?",
                    value="  triage my inbox  ",
                ),
                # Whitespace-only and skipped answers must not survive.
                ClarifyAnswer(id="blocker", kind="blocker", question="Q2?", value="   "),
                ClarifyAnswer(id="constraint", kind="constraint", question="Q3?", value=None),
            ],
            selected_integrations=["gmail"],
        )
        mock_repo.complete_onboarding.return_value = sample_user

        await complete_onboarding(sample_user_id, request, sample_background_tasks)

        mock_repo.complete_onboarding.assert_awaited_once_with(
            sample_user_id,
            OnboardingCompletion(
                name="Alice",
                timezone="UTC",
                phase=OnboardingPhase.PERSONALIZATION_PENDING,
                bio_status=BioStatus.PENDING,
                pipeline_mode="full",
                preferences=OnboardingPreferences(
                    profession="Engineer", response_style="casual", custom_instructions=None
                ),
                focus="ship the product",
                clarify_answers=[
                    {
                        "id": "scope",
                        "kind": "scope",
                        "question": "What should GAIA take off your plate?",
                        "value": "triage my inbox",
                    }
                ],
                selected_integrations=["gmail"],
            ),
        )
        mock_enqueue_intelligence_job.assert_awaited_once_with(sample_user_id)
        # This request carries a focus, so the goal memory seed is scheduled too.
        expected_calls = [
            call(seed_initial_user_data, sample_user_id),
            call(_seed_goal_memory, sample_user_id, "ship the product"),
            call(provision_briefing_workflows, sample_user_id),
        ]
        sample_background_tasks.add_task.assert_has_calls(expected_calls)
        assert sample_background_tasks.add_task.call_count == len(expected_calls)

    async def test_blank_and_absent_optionals_normalize_to_none_and_split_mode(
        self,
        mock_repo: MagicMock,
        mock_enqueue_intelligence_job: AsyncMock,
        sample_user_id: str,
        sample_background_tasks: BackgroundTasks,
        sample_user: UserDocument,
    ) -> None:
        request = OnboardingRequest(
            name="Alice",
            profession="Engineer",
            defer_workflows=True,
            focus="   ",
        )
        mock_repo.complete_onboarding.return_value = sample_user

        await complete_onboarding(sample_user_id, request, sample_background_tasks)

        mock_repo.complete_onboarding.assert_awaited_once_with(
            sample_user_id,
            OnboardingCompletion(
                name="Alice",
                timezone=None,
                phase=OnboardingPhase.PERSONALIZATION_PENDING,
                bio_status=BioStatus.PENDING,
                pipeline_mode="split",
                preferences=OnboardingPreferences(
                    profession="Engineer", response_style="casual", custom_instructions=None
                ),
                focus=None,
                clarify_answers=None,
                selected_integrations=None,
            ),
        )

    async def test_generic_exception_returns_500(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
    ) -> None:
        mock_repo.complete_onboarding.side_effect = RuntimeError("Unexpected")

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )
        assert exc_info.value.status_code == 500


class TestGetUserOnboardingStatus:
    async def test_returns_status(self, mock_repo: MagicMock, sample_user_id: str) -> None:
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

    async def test_user_not_found_raises_404(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status(sample_user_id)
        assert exc_info.value.status_code == 404
        assert "User not found" in exc_info.value.detail

    async def test_no_onboarding_data(self, mock_repo: MagicMock, sample_user_id: str) -> None:
        mock_repo.get.return_value = UserDocument.model_validate({"id": sample_user_id})

        result = await get_user_onboarding_status(sample_user_id)

        assert result.completed is False
        assert result.preferences.profession is None

    async def test_exception_raises_500(self, mock_repo: MagicMock) -> None:
        mock_repo.get.side_effect = Exception("DB error")

        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status("invalid")
        assert exc_info.value.status_code == 500


class TestUpdateOnboardingPreferences:
    async def test_updates_preferences(self, mock_repo: MagicMock, sample_user_id: str) -> None:
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id, "onboarding": {"preferences": {"profession": "Designer"}}}
        )

        prefs = OnboardingPreferences(profession="Designer", response_style="brief")
        result = await update_onboarding_preferences(sample_user_id, prefs)

        assert result["_id"] == sample_user_id
        assert result["user_id"] == sample_user_id

    async def test_user_not_found(self, mock_repo: MagicMock, sample_user_id: str) -> None:
        mock_repo.update_onboarding_preferences.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(
                sample_user_id, OnboardingPreferences(profession="Designer")
            )
        assert exc_info.value.status_code == 404

    async def test_partial_patch_merges_only_sent_fields(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
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

    async def test_generic_exception_returns_500(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.update_onboarding_preferences.side_effect = RuntimeError("Unexpected")

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(
                sample_user_id, OnboardingPreferences(profession="Engineer")
            )
        assert exc_info.value.status_code == 500


class TestSavePersonalizationData:
    async def test_saves_data(
        self, mock_save_personalization: AsyncMock, sample_user_id: str
    ) -> None:
        bundle = PersonalizationBundle(
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

        await save_personalization_data(sample_user_id, bundle)

        mock_save_personalization.assert_awaited_once_with(sample_user_id, bundle)

    async def test_handles_exception(
        self, mock_save_personalization: AsyncMock, sample_user_id: str
    ) -> None:
        mock_save_personalization.side_effect = Exception("DB error")

        await save_personalization_data(
            sample_user_id,
            PersonalizationBundle(
                house="explorer",
                personality_phrase="phrase",
                user_bio="bio",
                bio_status=BioStatus.COMPLETED,
                workflow_ids=[],
                account_number=1,
                member_since="Jan 2024",
                overlay_color="#000",
                overlay_opacity=50,
            ),
        )


class TestSeedInitialUserData:
    async def test_seeds_onboarding_todo(self) -> None:
        with patch(
            "app.services.onboarding.post_onboarding_service.seed_onboarding_todo",
            new_callable=AsyncMock,
        ) as mock_todo:
            await seed_initial_user_data("user1")
            mock_todo.assert_awaited_once_with("user1")

    async def test_handles_exception(self) -> None:
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
        mock_repo: MagicMock,
        mock_enqueue_intelligence_job: AsyncMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        with patch("app.services.onboarding.onboarding_service.log") as log:
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )

        log.set.assert_called_once_with(auth={"user_id": sample_user_id})
        log.info.assert_called_once_with(
            f"{LogTag.ONBOARDING} Onboarding completed successfully for user",
            user_id=sample_user_id,
        )

    async def test_complete_onboarding_replay_log_is_exact(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
    ) -> None:
        # The atomic gate makes a repeat submission a no-op: complete_onboarding
        # returns None and the existing user is returned unchanged.
        existing = UserDocument.model_validate(
            {"id": sample_user_id, "onboarding": {"phase": "personalization_pending"}}
        )
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = existing
        with patch("app.services.onboarding.onboarding_service.log") as log:
            result = await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )

        assert result["_id"] == sample_user_id
        mock_repo.get.assert_awaited_once_with(sample_user_id)
        log.info.assert_called_once_with(
            f"{LogTag.ONBOARDING} complete_onboarding replay — onboarding already submitted",
            user_id=sample_user_id,
            phase="personalization_pending",
        )

    async def test_enqueue_failure_rolls_back_with_exact_error_log(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
        sample_user: UserDocument,
    ) -> None:
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
        assert log.error.call_args_list[0] == call(
            f"{LogTag.ONBOARDING} Enqueue failed, rolling back onboarding state for user",
            user_id=sample_user_id,
            error="queue down",
            error_type="RuntimeError",
            exc_info=True,
        )

    async def test_generic_exception_logs_exactly_and_raises_500_with_exact_detail(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
    ) -> None:
        mock_repo.complete_onboarding.side_effect = RuntimeError("Unexpected")
        with patch("app.services.onboarding.onboarding_service.log") as log:
            with pytest.raises(HTTPException) as exc_info:
                await complete_onboarding(
                    sample_user_id, sample_onboarding_request, sample_background_tasks
                )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to complete onboarding"
        log.error.assert_called_once_with(
            f"{LogTag.ONBOARDING} Error completing onboarding for user",
            user_id=sample_user_id,
            error="Unexpected",
            error_type="RuntimeError",
            exc_info=True,
        )

    async def test_rollback_failure_logs_exactly_and_still_raises_503(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_background_tasks: BackgroundTasks,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        with (
            patch(
                "app.services.onboarding.onboarding_service.enqueue_intelligence_job",
                new_callable=AsyncMock,
                side_effect=RuntimeError("queue down"),
            ),
            patch(
                "app.services.onboarding.onboarding_service.user_repository.clear_onboarding",
                new_callable=AsyncMock,
                side_effect=RuntimeError("rollback blew up"),
            ),
            patch("app.services.onboarding.onboarding_service.log") as log,
            pytest.raises(HTTPException) as exc_info,
        ):
            await complete_onboarding(
                sample_user_id, sample_onboarding_request, sample_background_tasks
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Could not start onboarding. Please retry."
        assert len(log.error.call_args_list) == 2
        assert log.error.call_args_list[1] == call(
            f"{LogTag.ONBOARDING} Rollback also failed for user",
            user_id=sample_user_id,
            error="rollback blew up",
            error_type="RuntimeError",
            exc_info=True,
        )

    async def test_get_status_returns_every_field_from_the_document(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
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
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.get.side_effect = RuntimeError("mongo down")
        with pytest.raises(HTTPException) as exc_info:
            await get_user_onboarding_status(sample_user_id)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "An internal error occurred"

    async def test_update_preferences_success_log_is_exact(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
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
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.update_onboarding_preferences.side_effect = RuntimeError("db down")
        prefs = OnboardingPreferences(profession="Writer", response_style="formal")

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(sample_user_id, prefs)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to update preferences"


class TestCompleteOnboardingExactKwargs:
    async def test_repository_receives_the_exact_normalized_kwargs(
        self,
        mock_repo: MagicMock,
        mock_enqueue_intelligence_job: AsyncMock,
        sample_user_id: str,
        sample_background_tasks: BackgroundTasks,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        request = OnboardingRequest(
            name="  Alice  ",
            profession="Engineer",
            timezone=" UTC ",
            defer_workflows=True,
            focus="  ship v2  ",
            clarify_answers=[
                {"id": "c1", "kind": "goal", "question": "q", "value": "  grow  "},
                {"id": "c2", "kind": "goal", "question": "q", "value": "   "},
            ],
        )
        await complete_onboarding(sample_user_id, request, sample_background_tasks)

        completion = mock_repo.complete_onboarding.await_args.args[1]
        assert completion.name == "Alice"
        assert completion.timezone == "UTC"
        assert completion.pipeline_mode == "split"
        assert completion.focus == "ship v2"
        assert completion.clarify_answers == [
            {"id": "c1", "kind": "goal", "question": "q", "value": "grow"}
        ]
        assert completion.preferences == OnboardingPreferences(
            profession="Engineer", response_style="casual", custom_instructions=None
        )
