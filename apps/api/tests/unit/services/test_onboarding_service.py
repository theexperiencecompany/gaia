"""Unit tests for onboarding service, post-onboarding service, and the Gmail-personalization job slot.

Since the intelligence pipeline moved off onboarding and onto Gmail connect,
submitting the form IS completion: nothing is queued, nothing is seeded, and
the phase lands on PERSONALIZATION_COMPLETE in one write.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from arq.connections import ArqRedis
from arq.constants import (
    abort_jobs_ss,
    default_queue_name,
    in_progress_key_prefix,
    result_key_prefix,
)
from arq.jobs import Job, JobStatus
from bson import ObjectId
import fakeredis.aioredis
from fastapi import HTTPException
import pytest

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.onboarding import (
    FIRST_CONVERSATION_ID_FIELD,
    GETTING_STARTED_CONVERSATION_ID_FIELD,
    GMAIL_PERSONALIZATION_MARKER,
    HOLO_CONVERSATION_ID_FIELD,
    INTELLIGENCE_TASK,
)
from app.models.user_models import (
    BioStatus,
    OnboardingAnswers,
    OnboardingNeed,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    UserDocument,
)
from app.services.onboarding.first_question import FirstQuestion
from app.services.onboarding.intelligence_job import (
    abort_active_intelligence_job,
    enqueue_gmail_personalization,
    is_intelligence_job_live,
    personalization_job_id,
)
from app.services.onboarding.onboarding_service import (
    complete_onboarding,
    complete_onboarding_on_platform_link,
    get_user_onboarding_status,
    record_onboarding_step,
    reset_onboarding,
    save_onboarding_answers,
    update_onboarding_preferences,
)
from app.utils.redis_utils import RedisPoolManager
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.onboarding import (
    OnboardingCompleted,
    OnboardingPhaseCompleted,
    OnboardingStarted,
    OnboardingStep,
)
from tests.helpers import captured_wide_event

SERVICE = "app.services.onboarding.onboarding_service"


@pytest.fixture
def mock_repo() -> Iterator[MagicMock]:
    with patch(f"{SERVICE}.user_repository") as repo:
        repo.complete_onboarding = AsyncMock()
        repo.get = AsyncMock()
        repo.reset_onboarding = AsyncMock()
        repo.update_onboarding_preferences = AsyncMock()
        repo.record_onboarding_step = AsyncMock(return_value=True)
        yield repo


@pytest.fixture
def sample_user_id() -> str:
    return str(ObjectId())


@pytest.fixture
def sample_onboarding_request() -> OnboardingRequest:
    return OnboardingRequest(profession="Engineer", needs=["inbox"], timezone="UTC")


@pytest.fixture
async def arq_pool() -> AsyncIterator[ArqRedis]:
    """Install a real ArqRedis on fakeredis as the process pool.

    Real arq rather than a mock, so "nothing was queued" is answered by the
    queue itself: an enqueue anywhere under the call lands in the sorted set
    and fails the assertion.
    """
    fake = fakeredis.aioredis.FakeRedis()
    pool = ArqRedis(connection_pool=fake.connection_pool)
    previous = RedisPoolManager._pool
    RedisPoolManager._pool = pool
    yield pool
    RedisPoolManager._pool = previous
    await fake.aclose()


async def queued_job_calls(pool: ArqRedis) -> list[tuple[str, tuple[Any, ...]]]:
    """Every queued job as (task, args); the args show which user the pipeline runs for."""
    calls: list[tuple[str, tuple[Any, ...]]] = []
    for raw in await pool.zrange(default_queue_name, 0, -1):
        job_id = raw.decode() if isinstance(raw, bytes) else raw
        info = await Job(job_id, redis=pool).info()
        if info is not None:
            calls.append((info.function, tuple(info.args)))
    return calls


async def queued_job_names(pool: ArqRedis) -> list[str]:
    return [name for name, _args in await queued_job_calls(pool)]


def _completed_user(user_id: str, **onboarding: Any) -> UserDocument:
    return UserDocument.model_validate(
        {
            "id": user_id,
            "name": "Alice",
            "onboarding": {
                "completed": True,
                "phase": OnboardingPhase.PERSONALIZATION_COMPLETE,
                "preferences": {"profession": "Engineer", "response_style": "casual"},
                **onboarding,
            },
        }
    )


@pytest.fixture
def sample_user(sample_user_id: str) -> UserDocument:
    return _completed_user(sample_user_id)


@pytest.fixture
def persisting_repo(mock_repo: MagicMock, sample_user_id: str) -> MagicMock:
    """Echo the phase argument back as if it were persisted.

    Real echo instead of a fixture constant, so the returned value is what
    the service actually wrote — a constant would look right even if the
    service wrote the wrong phase.
    """

    async def _write(user_id: str, **fields: Any) -> UserDocument:
        return UserDocument.model_validate(
            {
                "id": user_id,
                "onboarding": {
                    "completed": True,
                    "phase": fields["phase"],
                    "bio_status": fields["bio_status"],
                    "preferences": fields["preferences"].model_dump(),
                },
            }
        )

    mock_repo.complete_onboarding.side_effect = _write
    return mock_repo


@pytest.fixture(autouse=True)
def no_llm_question() -> Iterator[MagicMock]:
    """Stub the first-question resolver so no test reaches a model or Redis.

    Default returns the static conversation; the two tests that care patch
    the return value themselves.
    """
    with patch(f"{SERVICE}.resolve_first_question", AsyncMock(return_value=None)) as mock:
        yield mock


class TestCompleteOnboarding:
    async def test_the_written_jobs_become_the_chips(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
        no_llm_question: MagicMock,
    ) -> None:
        """The chips ride the question they answer — static ones would answer a question nobody asked."""
        mock_repo.complete_onboarding.return_value = sample_user
        mock_repo.set_first_conversation_id = AsyncMock(return_value=None)
        no_llm_question.return_value = FirstQuestion(
            chips=["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"]
        )

        with patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value="conv-1")) as seed:
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        composed = seed.await_args.args[1]
        assert composed.question == "You're an engineer. What's first?"
        assert composed.follow_ups == [
            "Find investors",
            "Fix my marketing",
            "Hire someone",
            "Write my pitch",
        ]

    async def test_no_written_jobs_means_no_chips_rather_than_invented_ones(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        mock_repo.set_first_conversation_id = AsyncMock(return_value=None)

        with patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value="conv-1")) as seed:
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        composed = seed.await_args.args[1]
        assert composed.follow_ups == []

    async def test_successful_onboarding(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user

        result = await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert result["_id"] == sample_user_id
        assert result["user_id"] == sample_user_id

    async def test_persists_the_completed_phase(
        self,
        persisting_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
    ) -> None:
        """Submitting the form is completion; any non-terminal phase parks the user on a pipeline that will never run."""
        result = await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert (
            persisting_repo.complete_onboarding.await_args.kwargs["phase"]
            == OnboardingPhase.COMPLETED
        )
        assert result["onboarding"]["phase"] == OnboardingPhase.COMPLETED.value

    async def test_queues_no_job_and_seeds_nothing(
        self,
        mock_repo: MagicMock,
        arq_pool: ArqRedis,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        """The pipeline, starter todo, and seeded conversation are now earned only by connecting Gmail."""
        mock_repo.complete_onboarding.return_value = sample_user

        with patch(
            "app.utils.seeding_utils.seed_holo_card_conversation",
            new_callable=AsyncMock,
        ) as mock_seed:
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert await queued_job_names(arq_pool) == []
        mock_seed.assert_not_awaited()

    async def test_seeds_the_getting_started_conversation_and_persists_its_id(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        """The web routes a freshly onboarded user into this conversation by its persisted id."""
        mock_repo.complete_onboarding.return_value = sample_user
        mock_repo.set_first_conversation_id = AsyncMock(
            return_value=_completed_user(
                sample_user_id, **{GETTING_STARTED_CONVERSATION_ID_FIELD: "conv-1"}
            )
        )

        with patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value="conv-1")) as seed:
            result = await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert seed.await_args.args[0] == sample_user_id
        composed = seed.await_args.args[1]
        assert composed.question == "You're an engineer. What's first?"
        mock_repo.set_first_conversation_id.assert_awaited_once_with(sample_user_id, "conv-1")
        assert result["onboarding"][GETTING_STARTED_CONVERSATION_ID_FIELD] == "conv-1"
        # The legacy holo-card field is a different conversation; the seed must
        # not squat on it. It is now a declared field on OnboardingSubdocument,
        # so it serializes as null rather than being absent.
        assert result["onboarding"][FIRST_CONVERSATION_ID_FIELD] is None

    async def test_the_closing_question_is_resolved_for_this_user_and_these_answers(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        no_llm_question: AsyncMock,
    ) -> None:
        """User, stored answers, and platform together are the cache key the answers save prewarmed under."""
        # What the completion write stored: the seeder reads the document, not the request.
        user = _completed_user(
            sample_user_id, preferences={"profession": "Engineer", "needs": ["inbox"]}
        )
        user.platform_links = {"telegram": {"id": "tg-1"}}
        mock_repo.complete_onboarding.return_value = user
        mock_repo.set_first_conversation_id = AsyncMock(return_value=None)

        with patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value="conv-1")):
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        user_arg, prefs_arg, platform_arg = no_llm_question.await_args.args
        assert user_arg == sample_user_id
        assert prefs_arg.profession == sample_onboarding_request.profession
        assert prefs_arg.needs == sample_onboarding_request.needs
        assert platform_arg == "telegram"

    async def test_a_failed_seed_is_reported_with_its_cause(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        """Swallowed so completion still succeeds; this warning is the only trace the seed failed."""
        mock_repo.complete_onboarding.return_value = sample_user

        with (
            patch(
                f"{SERVICE}.seed_first_conversation",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch(f"{SERVICE}.log") as log,
        ):
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} complete_onboarding failed to seed the first conversation",
            user_id=sample_user_id,
            error="mongo down",
            error_type="RuntimeError",
        )

    async def test_a_platform_linked_during_onboarding_reaches_the_jobs_prompt(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        no_llm_question: MagicMock,
    ) -> None:
        """The platform link lands on the user doc before submission, so completion reads it from that write."""
        user = _completed_user(sample_user_id)
        user.platform_links = {"telegram": {"id": "tg-1"}}
        mock_repo.complete_onboarding.return_value = user
        mock_repo.set_first_conversation_id = AsyncMock(return_value=None)

        with patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value="conv-1")) as seed:
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert no_llm_question.await_args.args[2] == "telegram"
        assert "I'm on your Telegram too." in seed.await_args.args[1].lines[1]

    async def test_a_failed_seed_still_completes_onboarding(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        """Completion already landed; failing the request here would bounce the user back into the wizard."""
        mock_repo.complete_onboarding.return_value = sample_user
        mock_repo.set_first_conversation_id = AsyncMock()

        with patch(
            f"{SERVICE}.seed_first_conversation",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            result = await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert result["user_id"] == sample_user_id
        assert result["onboarding"]["completed"] is True
        mock_repo.set_first_conversation_id.assert_not_awaited()

    async def test_a_seed_that_returned_no_id_writes_nothing(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        mock_repo.set_first_conversation_id = AsyncMock()

        with patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value=None)):
            result = await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert result["user_id"] == sample_user_id
        mock_repo.set_first_conversation_id.assert_not_awaited()

    async def test_captures_the_completion_event_once(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_user: UserDocument,
    ) -> None:
        """A retried POST never reaches the capture: the atomic gate returns early on it."""
        mock_repo.complete_onboarding.return_value = sample_user
        request = OnboardingRequest(profession="Engineer", needs=["reminders", "inbox"])

        with (
            patch(f"{SERVICE}.capture") as capture,
            patch(f"{SERVICE}.identify_user") as identify,
        ):
            await complete_onboarding(sample_user_id, request)

        capture.assert_called_once_with(
            UserId(sample_user_id),
            OnboardingCompleted(needs=["inbox", "reminders"], has_other_need=False),
        )
        # The profession lands on the person, not the event, so cohorts can
        # cut by it; the free-text need only travels as a flag.
        identify.assert_called_once_with(
            UserId(sample_user_id),
            {"profession": "Engineer", "onboarding_completed": True},
        )

    async def test_the_linked_platform_reaches_the_event_and_the_first_conversation(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        """The wizard submits after the link lands, so the platform line and the event both see it."""
        linked = _completed_user(sample_user_id).model_copy(
            update={"platform_links": {"telegram": {"id": "tg-1"}}}
        )
        mock_repo.complete_onboarding.return_value = linked
        request = OnboardingRequest(profession="Engineer", needs=["inbox"])

        with (
            patch(f"{SERVICE}.capture") as capture,
            patch(f"{SERVICE}.identify_user"),
            patch(f"{SERVICE}.compose_first_conversation") as compose,
            patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value=None)),
            patch(f"{SERVICE}.resolve_first_question", AsyncMock(return_value=None)),
        ):
            await complete_onboarding(sample_user_id, request)

        assert capture.call_args.args[1].linked_platform == "telegram"
        assert compose.call_args.args[1] == "telegram"

    async def test_the_first_conversation_is_built_from_the_stored_preferences(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        """The wizard stored the language earlier; the request does not carry it."""
        mock_repo.complete_onboarding.return_value = _completed_user(
            sample_user_id, preferences={"profession": "Engineer", "language": "de"}
        )
        request = OnboardingRequest(profession="Engineer", needs=["inbox"])

        with (
            patch(f"{SERVICE}.capture"),
            patch(f"{SERVICE}.identify_user"),
            patch(f"{SERVICE}.compose_first_conversation") as compose,
            patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value=None)),
            patch(f"{SERVICE}.resolve_first_question", AsyncMock(return_value=None)),
        ):
            await complete_onboarding(sample_user_id, request)

        assert compose.call_args.args[0].language == "de"

    async def test_a_typed_need_travels_only_as_a_flag(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        request = OnboardingRequest(
            profession="Engineer", needs=["reminders"], other_need="chase invoices"
        )

        with (
            patch(f"{SERVICE}.capture") as capture,
            patch(f"{SERVICE}.identify_user"),
        ):
            await complete_onboarding(sample_user_id, request)

        props = capture.call_args.args[1]
        assert props.has_other_need is True
        assert "chase invoices" not in str(props)

    async def test_a_replay_captures_nothing(
        self,
        mock_repo: MagicMock,
        sample_user: UserDocument,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
    ) -> None:
        """The atomic gate loses here, so counting this POST would double the milestone for a retry."""
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = sample_user

        with patch(f"{SERVICE}.capture") as capture:
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        capture.assert_not_called()

    async def test_user_not_found(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
    ) -> None:
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(sample_user_id, sample_onboarding_request)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"

    async def test_already_onboarded_replays_idempotently(
        self,
        mock_repo: MagicMock,
        sample_user: UserDocument,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
    ) -> None:
        # The atomic gate makes a repeat submission a no-op: complete_onboarding
        # returns None and the existing user is returned unchanged.
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = sample_user

        result = await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert result["_id"] == sample_user_id

    async def test_sets_timezone(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_user: UserDocument,
    ) -> None:
        request = OnboardingRequest(
            profession="Engineer", needs=["inbox"], timezone="America/New_York"
        )
        mock_repo.complete_onboarding.return_value = sample_user

        await complete_onboarding(sample_user_id, request)

        assert mock_repo.complete_onboarding.call_args.kwargs["timezone"] == "America/New_York"

    async def test_passes_exact_normalized_kwargs_to_repository(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_user: UserDocument,
    ) -> None:
        request = OnboardingRequest(
            profession="  Engineer  ", needs=["inbox", "calendar"], timezone=" UTC "
        )
        mock_repo.complete_onboarding.return_value = sample_user

        await complete_onboarding(sample_user_id, request)

        mock_repo.complete_onboarding.assert_awaited_once_with(
            sample_user_id,
            timezone="UTC",
            phase=OnboardingPhase.COMPLETED,
            bio_status=BioStatus.PENDING,
            preferences=OnboardingPreferences(
                profession="Engineer",
                needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR],
                response_style="casual",
            ),
        )

    async def test_an_absent_timezone_is_not_written(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_user: UserDocument,
    ) -> None:
        request = OnboardingRequest(profession="Engineer", needs=["inbox"])
        mock_repo.complete_onboarding.return_value = sample_user

        await complete_onboarding(sample_user_id, request)

        assert mock_repo.complete_onboarding.await_args.kwargs["timezone"] is None

    async def test_duplicate_needs_are_deduped_in_selection_order(self) -> None:
        request = OnboardingRequest(
            profession="Engineer", needs=["reminders", "inbox", "reminders"]
        )
        assert request.needs == [OnboardingNeed.REMINDERS, OnboardingNeed.INBOX]

    async def test_generic_exception_returns_500(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
    ) -> None:
        mock_repo.complete_onboarding.side_effect = RuntimeError("Unexpected")

        with pytest.raises(HTTPException) as exc_info:
            await complete_onboarding(sample_user_id, sample_onboarding_request)
        assert exc_info.value.status_code == 500


class TestResetOnboarding:
    """Reset tears down every seeded conversation.

    The legacy first-message one and the holo-card one — a user who resets
    must not keep a conversation pointing at personalization that no longer
    exists.
    """

    @pytest.fixture
    def deleted_conversations(self, sample_user_id: str) -> Iterator[list[str]]:
        deleted: list[str] = []

        conversations = AsyncMock()

        async def _delete(conversation_id: str, *, user_id: str) -> bool:
            # Scoped like the real repository: a delete that arrives without the
            # owner's id matches nothing, so an unscoped call shows up as a
            # conversation the reset silently left behind.
            if user_id != sample_user_id:
                return False
            deleted.append(conversation_id)
            return True

        conversations.delete.side_effect = _delete
        conversations.delete_onboarding_demos.return_value = 0

        todos = AsyncMock()
        todos.delete_onboarding_todos.return_value = 0

        integrations = AsyncMock()
        integrations.list_for_user.return_value = []

        memory = AsyncMock()
        memory.delete_all.return_value = 0

        with (
            patch(f"{SERVICE}.conversation_repository", conversations),
            patch(f"{SERVICE}.todo_repository", todos),
            patch(f"{SERVICE}.user_integration_repository", integrations),
            patch(f"{SERVICE}.memory_engine", memory),
            patch(f"{SERVICE}.abort_active_intelligence_job", new_callable=AsyncMock),
        ):
            yield deleted

    async def test_deletes_both_the_legacy_and_holo_conversations(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        mock_repo.get.return_value = _completed_user(
            sample_user_id,
            first_message_conversation_id="conv-legacy",
            **{HOLO_CONVERSATION_ID_FIELD: "conv-holo"},
        )

        counts = await reset_onboarding(sample_user_id)

        assert deleted_conversations == ["conv-legacy", "conv-holo"]
        assert counts.conversation_deleted == 2
        mock_repo.reset_onboarding.assert_awaited_once_with(sample_user_id)

    async def test_a_full_reset_disconnects_integrations_and_clears_memories_for_that_user(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
    ) -> None:
        """The product's Restart button is the full reset — integrations and memories go too, scoped to that user."""
        mock_repo.get.return_value = _completed_user(sample_user_id)
        integrations = AsyncMock()
        integrations.list_for_user.return_value = []
        memory = AsyncMock()
        memory.delete_all.return_value = 3
        with (
            patch(f"{SERVICE}.conversation_repository", AsyncMock()),
            patch(f"{SERVICE}.todo_repository", AsyncMock()),
            patch(f"{SERVICE}.user_integration_repository", integrations),
            patch(f"{SERVICE}.memory_engine", memory),
            patch(f"{SERVICE}.abort_active_intelligence_job", new_callable=AsyncMock),
        ):
            counts = await reset_onboarding(sample_user_id)

        integrations.list_for_user.assert_awaited_once_with(sample_user_id)
        memory.delete_all.assert_awaited_once_with(sample_user_id)
        assert counts.memories_cleared == 3

    async def test_keep_connections_leaves_integrations_and_memories_alone(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
    ) -> None:
        mock_repo.get.return_value = _completed_user(sample_user_id)
        integrations = AsyncMock()
        memory = AsyncMock()
        with (
            patch(f"{SERVICE}.conversation_repository", AsyncMock()),
            patch(f"{SERVICE}.todo_repository", AsyncMock()),
            patch(f"{SERVICE}.user_integration_repository", integrations),
            patch(f"{SERVICE}.memory_engine", memory),
            patch(f"{SERVICE}.abort_active_intelligence_job", new_callable=AsyncMock),
        ):
            counts = await reset_onboarding(sample_user_id, keep_connections=True)

        integrations.list_for_user.assert_not_awaited()
        memory.delete_all.assert_not_awaited()
        assert counts.integrations_disconnected == 0
        assert counts.memories_cleared == 0
        mock_repo.reset_onboarding.assert_awaited_once_with(sample_user_id)

    async def test_deletes_the_getting_started_conversation_too(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """A returning user can carry all three; skipping getting-started seeds a second copy and orphans the first."""
        mock_repo.get.return_value = _completed_user(
            sample_user_id,
            first_message_conversation_id="conv-legacy",
            **{
                GETTING_STARTED_CONVERSATION_ID_FIELD: "conv-started",
                HOLO_CONVERSATION_ID_FIELD: "conv-holo",
            },
        )

        counts = await reset_onboarding(sample_user_id)

        assert deleted_conversations == ["conv-legacy", "conv-started", "conv-holo"]
        assert counts.conversation_deleted == 3

    async def test_deletes_the_getting_started_conversation_on_its_own(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """The common case: a user who only ever ran the current flow."""
        mock_repo.get.return_value = _completed_user(
            sample_user_id, **{GETTING_STARTED_CONVERSATION_ID_FIELD: "conv-started"}
        )

        counts = await reset_onboarding(sample_user_id)

        assert deleted_conversations == ["conv-started"]
        assert counts.conversation_deleted == 1

    async def test_deletes_the_holo_conversation_on_its_own(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """Post-relocation users only ever have the holo one."""
        mock_repo.get.return_value = _completed_user(
            sample_user_id, **{HOLO_CONVERSATION_ID_FIELD: "conv-holo"}
        )

        counts = await reset_onboarding(sample_user_id)

        assert deleted_conversations == ["conv-holo"]
        assert counts.conversation_deleted == 1

    async def test_the_legacy_suggested_workflows_are_deleted_through_the_service(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """Pre-relocation workflows carry scheduled executions and Composio triggers that only the service teardown unwinds."""
        mock_repo.get.return_value = _completed_user(
            sample_user_id, suggested_workflows=["wf-1", "wf-2"]
        )

        with patch(f"{SERVICE}.WorkflowService.delete_workflow", AsyncMock(return_value=True)) as d:
            counts = await reset_onboarding(sample_user_id)

        assert [c.args for c in d.await_args_list] == [
            ("wf-1", sample_user_id),
            ("wf-2", sample_user_id),
        ]
        assert counts.workflows_deleted == 2

    async def test_a_failed_workflow_delete_is_reported_with_its_cause(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """The reset still reports success, so this warning is the only sign the workflow is still live."""
        mock_repo.get.return_value = _completed_user(sample_user_id, suggested_workflows=["wf-1"])

        with (
            patch(
                f"{SERVICE}.WorkflowService.delete_workflow",
                AsyncMock(side_effect=RuntimeError("composio down")),
            ),
            patch(f"{SERVICE}.log") as log,
        ):
            counts = await reset_onboarding(sample_user_id)

        assert counts.workflows_deleted == 0
        log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} reset_onboarding failed to delete workflow",
            wf_id="wf-1",
            error="composio down",
            error_type="RuntimeError",
            user_id=sample_user_id,
        )

    async def test_a_missing_user_is_a_404_that_says_so(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await reset_onboarding(sample_user_id)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"

    async def test_a_failed_todo_delete_is_reported_with_its_cause(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """Counted as zero and reported as success, so without this warning the todos silently survive."""
        mock_repo.get.return_value = _completed_user(sample_user_id)

        with (
            patch(f"{SERVICE}.todo_repository") as todos,
            patch(f"{SERVICE}.log") as log,
        ):
            todos.delete_onboarding_todos = AsyncMock(side_effect=RuntimeError("mongo down"))
            counts = await reset_onboarding(sample_user_id)

        assert counts.todos_deleted == 0
        log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} reset_onboarding failed to delete todos",
            error="mongo down",
            error_type="RuntimeError",
            user_id=sample_user_id,
        )

    async def test_a_failed_abort_is_reported_with_its_cause(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """The reset reports success regardless, so this warning is the only sign a live pipeline is still writing to the wiped document."""
        mock_repo.get.return_value = _completed_user(sample_user_id)

        with (
            patch(
                f"{SERVICE}.abort_active_intelligence_job",
                AsyncMock(side_effect=RuntimeError("redis down")),
            ),
            patch(f"{SERVICE}.log") as log,
        ):
            await reset_onboarding(sample_user_id)

        log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} reset_onboarding failed to abort personalization job",
            error="redis down",
            error_type="RuntimeError",
            user_id=sample_user_id,
        )

    async def test_aborts_the_personalization_job_before_wiping(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """A surviving job keeps writing stages onto the socket of a user who already restarted."""
        mock_repo.get.return_value = _completed_user(sample_user_id)

        with patch(f"{SERVICE}.abort_active_intelligence_job", new_callable=AsyncMock) as abort:
            await reset_onboarding(sample_user_id)

        abort.assert_awaited_once_with(sample_user_id)

    async def test_a_failed_abort_does_not_block_the_reset(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        mock_repo.get.return_value = _completed_user(sample_user_id)

        async with captured_wide_event() as event:
            with patch(
                f"{SERVICE}.abort_active_intelligence_job",
                new_callable=AsyncMock,
                side_effect=RuntimeError("redis down"),
            ):
                counts = await reset_onboarding(sample_user_id)

        assert counts.conversation_deleted == 0
        mock_repo.reset_onboarding.assert_awaited_once_with(sample_user_id)
        # Swallowed on purpose, so the wide event is the only place the orphaned
        # job is visible — a blank error there makes it undiagnosable.
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.ONBOARDING} reset_onboarding failed to abort personalization job",
                "error": "redis down",
                "error_type": "RuntimeError",
                "user_id": sample_user_id,
            }
        ]

    async def test_unknown_user_is_a_404(self, mock_repo: MagicMock, sample_user_id: str) -> None:
        mock_repo.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await reset_onboarding(sample_user_id)

        assert exc_info.value.status_code == 404


@pytest.fixture
def store(sample_user_id: str) -> Iterator[dict[str, Any]]:
    """Provide the user's onboarding subdocument behind a user-scoped fake repository."""
    onboarding: dict[str, Any] = {}
    doc = {"id": sample_user_id, "email": "test@example.com", "onboarding": onboarding}

    repo = AsyncMock()

    def _get(uid: str) -> UserDocument | None:
        # User-scoped like the real repository: a lookup for anyone else
        # finds nobody, so a call that loses the user id cannot pass.
        return UserDocument.model_validate(doc) if uid == sample_user_id else None

    repo.get.side_effect = _get

    with patch("app.services.onboarding.intelligence_job.user_repository", repo):
        yield onboarding


class TestEnqueueGmailPersonalization:
    """Guard against double-running Gmail personalization.

    The marker stops a reconnect from re-running a completed
    personalization; the per-user job id stops two simultaneous connects
    from running it twice.
    """

    async def test_a_first_connect_enqueues_the_pipeline_once(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        job_id = await enqueue_gmail_personalization(sample_user_id)

        assert job_id == personalization_job_id(sample_user_id)
        # The queued args decide whose mailbox is read — a pipeline enqueued for
        # nobody looks identical here unless the args are asserted.
        assert await queued_job_calls(arq_pool) == [(INTELLIGENCE_TASK, (sample_user_id,))]

    async def test_a_reconnect_while_the_run_is_live_joins_it(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """Two live pipelines would interleave stage events on one WebSocket, so the second connect must join, not start or kill."""
        first = await enqueue_gmail_personalization(sample_user_id)

        second = await enqueue_gmail_personalization(sample_user_id)

        assert second == first
        assert await queued_job_names(arq_pool) == [INTELLIGENCE_TASK]
        assert await arq_pool.zrange(abort_jobs_ss, 0, -1) == []

    async def test_racing_connects_admit_one_run(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """The claim is Redis's, not a read-then-write in Python."""
        results = await asyncio.gather(
            *(enqueue_gmail_personalization(sample_user_id) for _ in range(5))
        )

        assert set(results) == {personalization_job_id(sample_user_id)}
        assert await queued_job_names(arq_pool) == [INTELLIGENCE_TASK]

    async def test_the_live_job_is_what_a_reset_aborts(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        job_id = await enqueue_gmail_personalization(sample_user_id)

        aborted = await abort_active_intelligence_job(sample_user_id)

        assert aborted is True
        assert await arq_pool.zscore(abort_jobs_ss, job_id) is not None

    async def test_nothing_queued_means_nothing_to_abort(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        assert await abort_active_intelligence_job(sample_user_id) is False
        assert await arq_pool.zrange(abort_jobs_ss, 0, -1) == []

    async def test_a_queue_that_hands_back_no_job_reports_it(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """ARQ returning nothing with no live run is a dropped enqueue, visible only in the wide event."""
        async with captured_wide_event() as event:
            with patch(
                "app.services.onboarding.intelligence_job.enqueue_worker_job",
                new_callable=AsyncMock,
                return_value=None,
            ):
                job_id = await enqueue_gmail_personalization(sample_user_id)

        assert job_id is None
        assert event["errors"] == [
            {
                "msg": f"{LogTag.ONBOARDING} personalization enqueue returned no job",
                "user_id": sample_user_id,
            }
        ]

    async def test_a_reconnect_after_the_marker_enqueues_nothing(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """Reconnecting Gmail is a no-op once the pipeline has run — a second run would rewrite the holo card."""
        first = await enqueue_gmail_personalization(sample_user_id)
        store[GMAIL_PERSONALIZATION_MARKER] = "2026-08-01T00:00:00Z"

        second = await enqueue_gmail_personalization(sample_user_id)

        assert first is not None
        assert second is None
        assert await queued_job_names(arq_pool) == [INTELLIGENCE_TASK]

    async def test_a_legacy_user_with_a_house_but_no_marker_enqueues_nothing(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """Users who finished pre-relocation onboarding carry house and no marker, and must not be re-run."""
        store["house"] = "explorer"

        job_id = await enqueue_gmail_personalization(sample_user_id)

        assert job_id is None
        assert await queued_job_names(arq_pool) == []

    async def test_a_missing_user_enqueues_nothing(self, arq_pool: ArqRedis) -> None:
        repo = AsyncMock()
        repo.get.return_value = None

        with patch("app.services.onboarding.intelligence_job.user_repository", repo):
            job_id = await enqueue_gmail_personalization("ghost")

        assert job_id is None
        assert await queued_job_names(arq_pool) == []


class TestIsIntelligenceJobLive:
    """Verify is_intelligence_job_live against real arq job state, never mocked.

    The stuck-user sweep asks this before re-enqueueing; a wrong answer either
    starves a user of personalization or runs two pipelines onto one
    WebSocket.
    """

    async def test_a_job_still_in_the_queue_is_live(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        job_id = await enqueue_gmail_personalization(sample_user_id)

        assert job_id is not None
        assert await Job(job_id, redis=arq_pool).status() == JobStatus.queued
        assert await is_intelligence_job_live(sample_user_id) is True

    async def test_a_job_a_worker_has_picked_up_is_live(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """in_progress is the state the queued-only check misses — popped off the queue but still running."""
        job_id = await enqueue_gmail_personalization(sample_user_id)
        assert job_id is not None
        await arq_pool.zrem(default_queue_name, job_id)
        await arq_pool.set(in_progress_key_prefix + job_id, b"1")

        assert await Job(job_id, redis=arq_pool).status() == JobStatus.in_progress
        assert await is_intelligence_job_live(sample_user_id) is True

    async def test_a_finished_job_is_not_live(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """Treating a finished run as live would block the stuck-user sweep from ever re-queueing."""
        job_id = await enqueue_gmail_personalization(sample_user_id)
        assert job_id is not None
        await arq_pool.zrem(default_queue_name, job_id)
        await arq_pool.set(result_key_prefix + job_id, b"done")

        assert await Job(job_id, redis=arq_pool).status() == JobStatus.complete
        assert await is_intelligence_job_live(sample_user_id) is False

    async def test_a_user_arq_has_never_seen_is_not_live(self, arq_pool: ArqRedis) -> None:
        assert await is_intelligence_job_live("ghost") is False


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


class TestLocalAuthOnboardingSynthesis:
    """Report completed=True regardless of stored state under AUTH_MODE=local.

    The unified synthesis (F8): the status endpoint and build_user_context must
    agree, because self-host has no pipeline that could produce a meaningful
    False.
    """

    @pytest.fixture
    def local_auth(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "AUTH_MODE", "local")

    async def test_local_forces_completed_over_stored_false(
        self, mock_repo, sample_user_id, local_auth
    ):
        mock_repo.get.return_value = UserDocument.model_validate(
            {"id": sample_user_id, "onboarding": {"completed": False}}
        )

        result = await get_user_onboarding_status(sample_user_id)

        assert result.completed is True

    async def test_local_synthesizes_completion_when_nothing_stored(
        self, mock_repo, sample_user_id, local_auth
    ):
        mock_repo.get.return_value = UserDocument.model_validate({"id": sample_user_id})

        result = await get_user_onboarding_status(sample_user_id)

        assert result.completed is True
        assert result.phase == "completed"

    async def test_local_preserves_stored_phase_and_metadata(
        self, mock_repo, sample_user_id, local_auth
    ):
        mock_repo.get.return_value = UserDocument.model_validate(
            {
                "id": sample_user_id,
                "onboarding": {
                    "completed": False,
                    "phase": OnboardingPhase.PERSONALIZATION_PENDING,
                    "preferences": {"profession": "Engineer"},
                },
            }
        )

        result = await get_user_onboarding_status(sample_user_id)

        assert result.completed is True  # forced…
        assert result.phase == OnboardingPhase.PERSONALIZATION_PENDING  # …stored phase kept
        assert result.preferences.profession == "Engineer"

    async def test_workos_keeps_stored_state_untouched(
        self, mock_repo, sample_user_id, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")
        mock_repo.get.return_value = UserDocument.model_validate(
            {"id": sample_user_id, "onboarding": {"completed": False}}
        )

        result = await get_user_onboarding_status(sample_user_id)

        assert result.completed is False
        assert result.phase is None


class TestSaveOnboardingAnswers:
    async def test_saving_the_answers_starts_writing_the_question(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        """The wizard's remaining screens are the whole latency budget for the model call, so it starts here, detached."""
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id, "platform_links": {"telegram": {"id": "tg-1"}}}
        )
        answers = OnboardingAnswers(profession="founder", needs=[OnboardingNeed.INBOX])

        with (
            patch(f"{SERVICE}.spawn_background_task") as spawn,
            patch(f"{SERVICE}.prewarm_first_question") as prewarm,
            patch(f"{SERVICE}.capture"),
        ):
            await save_onboarding_answers(sample_user_id, answers)

        spawn.assert_called_once()
        user_id, prefs, platform = prewarm.call_args.args
        assert (user_id, prefs.profession, prefs.needs, platform) == (
            sample_user_id,
            "founder",
            [OnboardingNeed.INBOX],
            "telegram",
        )
        # The task name is how this shows up in the wide event; unnamed, a stuck
        # prewarm is indistinguishable from every other background task.
        assert spawn.call_args.kwargs["name"] == f"prewarm_first_question:{sample_user_id}"

    async def test_stamps_questions_answered_with_the_answer_shape(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.update_onboarding_preferences.return_value = UserDocument(id=sample_user_id)
        answers = OnboardingAnswers(
            profession="founder",
            needs=[OnboardingNeed.REMINDERS, OnboardingNeed.INBOX],
            other_need="x",
        )

        with (
            patch(f"{SERVICE}.spawn_background_task"),
            patch(f"{SERVICE}.capture") as capture,
        ):
            await save_onboarding_answers(sample_user_id, answers)

        step = mock_repo.record_onboarding_step.await_args.args[1]
        assert step is OnboardingStep.QUESTIONS_ANSWERED
        assert capture.call_args.args[1] == OnboardingPhaseCompleted(
            phase=OnboardingStep.QUESTIONS_ANSWERED,
            needs=["inbox", "reminders"],
            has_other_need=True,
        )

    async def test_writes_every_answer_for_this_user_and_stamps_them_for_this_user(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.update_onboarding_preferences.return_value = UserDocument(id=sample_user_id)
        answers = OnboardingAnswers(
            profession="founder",
            needs=[OnboardingNeed.INBOX],
            other_need="chasing invoices",
            language="de-DE",
        )

        with (
            patch(f"{SERVICE}.spawn_background_task"),
            patch(f"{SERVICE}.prewarm_first_question"),
            patch(f"{SERVICE}.capture"),
        ):
            await save_onboarding_answers(sample_user_id, answers)

        written_for, written = mock_repo.update_onboarding_preferences.await_args.args
        assert written_for == sample_user_id
        assert (written.profession, written.needs, written.other_need, written.language) == (
            "founder",
            [OnboardingNeed.INBOX],
            "chasing invoices",
            "de",
        )
        assert mock_repo.record_onboarding_step.await_args.args[0] == sample_user_id

    async def test_a_missing_user_is_a_404_and_stamps_nothing(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.update_onboarding_preferences.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await save_onboarding_answers(
                sample_user_id,
                OnboardingAnswers(profession="founder", needs=[OnboardingNeed.INBOX]),
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"
        mock_repo.record_onboarding_step.assert_not_awaited()


class TestRecordOnboardingStep:
    async def test_the_first_stamp_reports_the_step_deduped_on_its_own_time(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        with patch(f"{SERVICE}.capture") as capture:
            assert await record_onboarding_step(sample_user_id, OnboardingStep.PAYWALL_REACHED)

        _, _, reached_at = mock_repo.record_onboarding_step.await_args.args
        capture.assert_called_once_with(
            UserId(sample_user_id),
            OnboardingPhaseCompleted(phase=OnboardingStep.PAYWALL_REACHED),
            Dedupe(key="onboarding_step:paywall_reached", occurred_at=reached_at),
        )

    async def test_the_start_reports_onboarding_started(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        with patch(f"{SERVICE}.capture") as capture:
            await record_onboarding_step(sample_user_id, OnboardingStep.STARTED)

        assert capture.call_args.args[1] == OnboardingStarted()

    async def test_an_already_stamped_step_reports_nothing(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.record_onboarding_step.return_value = False

        with patch(f"{SERVICE}.capture") as capture:
            assert not await record_onboarding_step(sample_user_id, OnboardingStep.STARTED)

        capture.assert_not_called()


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

        # Only response_style is provided — the patch must carry only that key.
        prefs = OnboardingPreferences(response_style="brief")
        await update_onboarding_preferences(sample_user_id, prefs)

        # The repository writes model_dump(exclude_unset=True) as the $set, so the
        # unsent fields must be absent from the model's set-fields, not merely None.
        patch_arg = mock_repo.update_onboarding_preferences.call_args[0][1]
        assert patch_arg.model_dump(exclude_unset=True) == {"response_style": "brief"}

    async def test_generic_exception_returns_500(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.update_onboarding_preferences.side_effect = RuntimeError("Unexpected")

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(
                sample_user_id, OnboardingPreferences(profession="Engineer")
            )
        assert exc_info.value.status_code == 500


class TestOnboardingServiceLogPins:
    """Exact pins for log calls and error paths the flow tests don't assert."""

    async def test_complete_onboarding_success_log_is_exact(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        with patch(f"{SERVICE}.log") as log:
            await complete_onboarding(sample_user_id, sample_onboarding_request)

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
    ) -> None:
        # The atomic gate makes a repeat submission a no-op: complete_onboarding
        # returns None and the existing user is returned unchanged.
        existing = UserDocument.model_validate(
            {"id": sample_user_id, "onboarding": {"phase": "personalization_complete"}}
        )
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = existing
        with patch(f"{SERVICE}.log") as log:
            result = await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert result["_id"] == sample_user_id
        mock_repo.get.assert_awaited_once_with(sample_user_id)
        log.info.assert_called_once_with(
            f"{LogTag.ONBOARDING} complete_onboarding replay — onboarding already submitted",
            user_id=sample_user_id,
            phase="personalization_complete",
        )

    async def test_generic_exception_logs_exactly_and_raises_500_with_exact_detail(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
    ) -> None:
        mock_repo.complete_onboarding.side_effect = RuntimeError("Unexpected")
        with patch(f"{SERVICE}.log") as log:
            with pytest.raises(HTTPException) as exc_info:
                await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to complete onboarding"
        log.error.assert_called_once_with(
            f"{LogTag.ONBOARDING} Error completing onboarding for user",
            user_id=sample_user_id,
            error="Unexpected",
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
                    "phase": OnboardingPhase.PERSONALIZATION_COMPLETE.value,
                    "preferences": {"profession": "Engineer", "response_style": "casual"},
                    "first_message_conversation_id": "conv-9",
                    GETTING_STARTED_CONVERSATION_ID_FIELD: "conv-started",
                },
            }
        )
        mock_repo.get.return_value = user

        status = await get_user_onboarding_status(sample_user_id)

        assert status.completed is True
        assert status.phase == OnboardingPhase.PERSONALIZATION_COMPLETE
        assert status.preferences.profession == "Engineer"
        assert status.first_message_conversation_id == "conv-9"
        # Separately addressable: this is the id the web redirects into, and it
        # must not be shadowed by the legacy holo-card one.
        assert status.getting_started_conversation_id == "conv-started"

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

        with patch(f"{SERVICE}.log") as log:
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
        sample_user_id: str,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        request = OnboardingRequest(profession="  Engineer  ", needs=["mornings"], timezone=" UTC ")
        await complete_onboarding(sample_user_id, request)

        kwargs = mock_repo.complete_onboarding.await_args.kwargs
        assert kwargs["timezone"] == "UTC"
        assert kwargs["preferences"] == OnboardingPreferences(
            profession="Engineer",
            needs=[OnboardingNeed.MORNINGS],
            response_style="casual",
        )


class TestCompleteOnboardingOnPlatformLink:
    """The bot link landing finishes onboarding through the one completion path the web submit uses."""

    @staticmethod
    def _at_platform_step(user_id: str, **onboarding: Any) -> UserDocument:
        return UserDocument.model_validate(
            {
                "id": user_id,
                "onboarding": {
                    "preferences": {
                        "profession": "founder",
                        "needs": ["inbox"],
                        "other_need": "invoices",
                    },
                    "steps_reached": {"paid_reveal_seen": "2026-11-02T10:00:00Z"},
                    **onboarding,
                },
            }
        )

    async def test_completes_from_the_stored_answers(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.get.return_value = self._at_platform_step(sample_user_id)

        with patch(f"{SERVICE}.complete_onboarding", AsyncMock()) as complete:
            await complete_onboarding_on_platform_link(sample_user_id)

        mock_repo.get.assert_awaited_once_with(sample_user_id)
        user_id, request = complete.await_args.args
        assert user_id == sample_user_id
        assert (request.profession, request.needs, request.other_need) == (
            "founder",
            [OnboardingNeed.INBOX],
            "invoices",
        )

    @pytest.mark.parametrize(
        "onboarding",
        [
            {"completed": True},
            {"steps_reached": {}},
            {"preferences": {"profession": None}},
        ],
        ids=["already-complete", "before-the-platform-step", "no-stored-answers"],
    )
    async def test_leaves_anyone_else_alone(
        self, mock_repo: MagicMock, sample_user_id: str, onboarding: dict[str, Any]
    ) -> None:
        mock_repo.get.return_value = self._at_platform_step(sample_user_id, **onboarding)

        with patch(f"{SERVICE}.complete_onboarding", AsyncMock()) as complete:
            await complete_onboarding_on_platform_link(sample_user_id)

        complete.assert_not_awaited()

    async def test_a_user_without_onboarding_is_left_alone(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.get.return_value = UserDocument(id=sample_user_id)

        with patch(f"{SERVICE}.complete_onboarding", AsyncMock()) as complete:
            await complete_onboarding_on_platform_link(sample_user_id)

        complete.assert_not_awaited()
