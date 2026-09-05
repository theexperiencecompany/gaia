"""Unit tests for onboarding service, post-onboarding service and the
Gmail-personalization job slot.

Since the intelligence pipeline moved off onboarding and onto Gmail connect,
submitting the form IS completion: nothing is queued, nothing is seeded, and the
phase lands on PERSONALIZATION_COMPLETE in one write.
"""

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

from app.constants.log_tags import LogTag
from app.constants.onboarding import (
    FIRST_CONVERSATION_ID_FIELD,
    GETTING_STARTED_CONVERSATION_ID_FIELD,
    GMAIL_PERSONALIZATION_MARKER,
    HOLO_CONVERSATION_ID_FIELD,
    INTELLIGENCE_TASK,
    LEGACY_PERSONALIZATION_MARKER,
)
from app.models.user_models import (
    BioStatus,
    OnboardingNeed,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingRequest,
    UserDocument,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.onboarding.first_question import FirstQuestion
from app.services.onboarding.intelligence_job import (
    abort_active_intelligence_job,
    enqueue_gmail_personalization,
    is_intelligence_job_live,
)
from app.services.onboarding.onboarding_service import (
    complete_onboarding,
    get_user_onboarding_status,
    reset_onboarding,
    update_onboarding_preferences,
)
from app.utils.redis_utils import RedisPoolManager
from tests.helpers import captured_wide_event

SERVICE = "app.services.onboarding.onboarding_service"


@pytest.fixture
def mock_repo() -> Iterator[MagicMock]:
    with patch(f"{SERVICE}.user_repository") as repo:
        repo.complete_onboarding = AsyncMock()
        repo.get = AsyncMock()
        repo.reset_onboarding = AsyncMock()
        repo.update_onboarding_preferences = AsyncMock()
        yield repo


@pytest.fixture
def sample_user_id() -> str:
    return str(ObjectId())


@pytest.fixture
def sample_onboarding_request() -> OnboardingRequest:
    return OnboardingRequest(profession="Engineer", needs=["inbox"], timezone="UTC")


@pytest.fixture
async def arq_pool() -> AsyncIterator[ArqRedis]:
    """A real ArqRedis on fakeredis, installed as the process pool.

    Real arq rather than a mock so "nothing was queued" is answered by the
    queue itself: any enqueue re-introduced anywhere under the call lands in
    the sorted set and fails the assertion.
    """
    fake = fakeredis.aioredis.FakeRedis()
    pool = ArqRedis(connection_pool=fake.connection_pool)
    previous = RedisPoolManager._pool
    RedisPoolManager._pool = pool
    yield pool
    RedisPoolManager._pool = previous
    await fake.aclose()


async def queued_job_calls(pool: ArqRedis) -> list[tuple[str, tuple[Any, ...]]]:
    """Every queued job as (task name, positional args) — the args carry which
    user the pipeline will actually run for."""
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
    """A repository that echoes the phase it was asked to write, so the value
    the endpoint returns is the value the service persisted — not a fixture
    constant that would stay right if the service wrote the wrong phase."""

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
    """No unit test reaches a model or Redis. The default is the static
    conversation; the two cases that care patch the return value themselves."""
    with patch(f"{SERVICE}.resolve_first_question", AsyncMock(return_value=None)) as mock:
        yield mock


class TestCompleteOnboarding:
    async def test_the_written_question_replaces_the_static_closing_line(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
        no_llm_question: MagicMock,
    ) -> None:
        """The chips ride the question they answer, so a seeded turn keeping the
        static ones would offer answers to a question nobody asked."""
        mock_repo.complete_onboarding.return_value = sample_user
        mock_repo.set_first_conversation_id = AsyncMock(return_value=None)
        no_llm_question.return_value = FirstQuestion(
            question="Engineer drowning in email. What actually breaks first, reviews or releases?",
            chips=["Reviews", "Releases", "Neither"],
        )

        with patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value="conv-1")) as seed:
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        composed = seed.await_args.args[1]
        assert composed.lines[-1] == (
            "Engineer drowning in email. What actually breaks first, reviews or releases?"
        )
        assert composed.follow_ups == ["Reviews", "Releases", "Neither"]

    async def test_no_written_question_leaves_the_static_conversation_alone(
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
        assert composed.lines[-1] == (
            "Start with Gmail. Connect it and I'll get into your inbox tonight, sort what "
            "needs you from what doesn't, and have drafts waiting by morning."
        )
        assert composed.follow_ups == ["Sort my inbox"]

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
        """Submitting the form is completion. Any non-terminal phase parks the
        user on onboarding waiting for a pipeline that will never run."""
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
        """The pipeline, the starter todo and the seeded conversation are all
        earned by connecting Gmail now. Queueing or seeding anything here gives
        every user a holo-card conversation and todos they never earned."""
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
        """The web routes the freshly onboarded user into this conversation, so
        an id that never reaches `onboarding.getting_started_conversation_id`
        drops them on an empty composer instead."""
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
        assert composed.opener == "I'm an engineer. Email is out of control."
        assert composed.lines[0] == "Email first. It's the one that eats everything else."
        mock_repo.set_first_conversation_id.assert_awaited_once_with(sample_user_id, "conv-1")
        assert result["onboarding"][GETTING_STARTED_CONVERSATION_ID_FIELD] == "conv-1"
        # The legacy holo-card field is a different conversation; the seed must
        # not squat on it.
        assert FIRST_CONVERSATION_ID_FIELD not in result["onboarding"]

    async def test_the_closing_question_is_resolved_for_this_user_and_these_answers(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        no_llm_question: AsyncMock,
    ) -> None:
        """All three are the cache key the answers PATCH prewarmed under. Resolve
        on the wrong user, the wrong answers or the wrong platform and it is a
        miss at best, and another user's question at worst."""
        user = _completed_user(sample_user_id)
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
        """Swallowed so completion still succeeds, so this warning is the only
        trace that the user landed without their opening conversation."""
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

    async def test_the_seeded_line_names_a_platform_linked_during_onboarding(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
    ) -> None:
        """The link lands on the user doc before the answers are submitted, so
        the platform line is composed from the document completion just wrote —
        no second read."""
        user = _completed_user(sample_user_id)
        user.platform_links = {"telegram": {"id": "tg-1"}}
        mock_repo.complete_onboarding.return_value = user
        mock_repo.set_first_conversation_id = AsyncMock(return_value=None)

        with patch(f"{SERVICE}.seed_first_conversation", AsyncMock(return_value="conv-1")) as seed:
            await complete_onboarding(sample_user_id, sample_onboarding_request)

        assert seed.await_args.args[1].lines[2] == (
            "And I'm in your Telegram now. Text me from there whenever. If something "
            "needs you, I'll text first."
        )

    async def test_a_failed_seed_still_completes_onboarding(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
        sample_user: UserDocument,
    ) -> None:
        """Completion already landed. Failing the request here would bounce the
        user back into the wizard over a welcome message."""
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

    async def test_captures_the_completion_event_deduped_per_user(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_user: UserDocument,
    ) -> None:
        """The milestone is emitted here now that nothing runs afterwards, keyed
        on the user so a retried POST cannot count it twice."""
        mock_repo.complete_onboarding.return_value = sample_user
        request = OnboardingRequest(profession="Engineer", needs=["todos", "inbox"])

        with (
            patch(f"{SERVICE}.capture_event") as capture,
            patch(f"{SERVICE}.identify_user") as identify,
        ):
            await complete_onboarding(sample_user_id, request)

        capture.assert_called_once_with(
            sample_user_id,
            AnalyticsEvents.ONBOARDING_COMPLETED,
            {"needs": ["inbox", "todos"], "has_other_need": False},
            dedupe_key=sample_user_id,
        )
        # The profession lands on the person, not the event, so cohorts can
        # cut by it; the free-text need only travels as a flag.
        identify.assert_called_once_with(
            sample_user_id,
            {"profession": "Engineer", "onboarding_completed": True},
        )

    async def test_a_typed_need_travels_only_as_a_flag(
        self,
        mock_repo: MagicMock,
        sample_user_id: str,
        sample_user: UserDocument,
    ) -> None:
        mock_repo.complete_onboarding.return_value = sample_user
        request = OnboardingRequest(
            profession="Engineer", needs=["todos"], other_need="chase invoices"
        )

        with (
            patch(f"{SERVICE}.capture_event") as capture,
            patch(f"{SERVICE}.identify_user"),
        ):
            await complete_onboarding(sample_user_id, request)

        props = capture.call_args.args[2]
        assert props["has_other_need"] is True
        assert "chase invoices" not in str(props)

    async def test_a_replay_captures_nothing(
        self,
        mock_repo: MagicMock,
        sample_user: UserDocument,
        sample_user_id: str,
        sample_onboarding_request: OnboardingRequest,
    ) -> None:
        """The atomic gate loses, so this POST completed nothing — counting it
        would double the milestone for every user who retried."""
        mock_repo.complete_onboarding.return_value = None
        mock_repo.get.return_value = sample_user

        with patch(f"{SERVICE}.capture_event") as capture:
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
            profession="  Engineer  ", needs=["inbox", "briefings"], timezone=" UTC "
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
                needs=[OnboardingNeed.INBOX, OnboardingNeed.BRIEFINGS],
                response_style="casual",
                custom_instructions=None,
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
        request = OnboardingRequest(profession="Engineer", needs=["todos", "inbox", "todos"])
        assert request.needs == [OnboardingNeed.TODOS, OnboardingNeed.INBOX]

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
    """Reset has to tear down both seeded conversations — the legacy
    first-message one and the holo card one — or a user who resets keeps a
    conversation pointing at personalization that no longer exists."""

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

    async def test_deletes_the_getting_started_conversation_too(
        self,
        mock_repo: MagicMock,
        deleted_conversations: list[str],
        sample_user_id: str,
    ) -> None:
        """A returning user can carry all three at once. Reset has to take the
        Getting-started one as well, or the next run seeds a second copy and
        the first is orphaned in the sidebar forever."""
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
        """Read off that exact key: the pre-relocation flow generated real
        workflows with scheduled executions and Composio triggers behind them,
        and only the service teardown unwinds those."""
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
        """The reset still reports success, so this warning is the only sign the
        workflow (and its schedule) is still live."""
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
        """Counted as zero and reported as success, so without this warning the
        onboarding todos silently survive into the user's fresh run."""
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
        """The reset carries on and reports success, so this warning is the only
        sign a live pipeline is still running and may write stage events onto
        the document that was just wiped."""
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
        """A surviving job keeps writing stages onto the socket of a user who
        already restarted."""
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
    """The user's onboarding subdocument, behind a user-scoped fake repository."""
    onboarding: dict[str, Any] = {}
    doc = {"id": sample_user_id, "email": "test@example.com", "onboarding": onboarding}

    repo = AsyncMock()

    def _get(uid: str) -> UserDocument | None:
        # User-scoped like the real repository: a lookup for anyone else
        # finds nobody, so a call that loses the user id cannot pass.
        return UserDocument.model_validate(doc) if uid == sample_user_id else None

    repo.get.side_effect = _get

    async def _set_active(uid: str, field: str, job_id: str) -> None:
        if uid != sample_user_id:
            return
        onboarding[field.removeprefix("onboarding.")] = job_id

    async def _clear_active(uid: str, field: str) -> None:
        if uid != sample_user_id:
            return
        onboarding.pop(field.removeprefix("onboarding."), None)

    repo.set_active_job.side_effect = _set_active
    repo.clear_active_job.side_effect = _clear_active

    with patch("app.services.onboarding.intelligence_job.user_repository", repo):
        yield onboarding


class TestEnqueueGmailPersonalization:
    """The marker is the only thing standing between a Gmail reconnect and a
    second full personalization run."""

    async def test_a_first_connect_enqueues_the_pipeline_once(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        job_id = await enqueue_gmail_personalization(sample_user_id)

        assert job_id is not None
        # The queued args decide whose mailbox is read — a pipeline enqueued for
        # nobody looks identical here unless the args are asserted.
        assert await queued_job_calls(arq_pool) == [(INTELLIGENCE_TASK, (sample_user_id,))]
        assert store["intelligence_job_id"] == job_id

    async def test_the_stored_job_id_is_what_a_later_abort_cancels(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """The whole point of storing the id: a reset has to reach the job that
        is actually running, and leave the slot empty afterwards."""
        job_id = await enqueue_gmail_personalization(sample_user_id)

        aborted = await abort_active_intelligence_job(sample_user_id)

        assert aborted is True
        assert await arq_pool.zscore(abort_jobs_ss, job_id) is not None
        assert "intelligence_job_id" not in store

    async def test_a_second_enqueue_cancels_the_job_still_in_flight(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """Two live pipelines interleave their stage events on one WebSocket and
        corrupt the frontend's cursor — the older one has to go."""
        first = await enqueue_gmail_personalization(sample_user_id)

        second = await enqueue_gmail_personalization(sample_user_id)

        assert second is not None and second != first
        assert await arq_pool.zscore(abort_jobs_ss, first) is not None
        assert store["intelligence_job_id"] == second

    async def test_nothing_stored_means_nothing_to_abort(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        assert await abort_active_intelligence_job(sample_user_id) is False
        assert await arq_pool.zrange(abort_jobs_ss, 0, -1) == []

    async def test_a_queue_that_hands_back_no_job_leaves_no_stored_id(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """A dropped enqueue must not leave a job id pointing at nothing, and
        has to be visible in the wide event — nothing else reports it."""
        async with captured_wide_event() as event:
            with patch(
                "app.services.onboarding.intelligence_job.enqueue_worker_job",
                new_callable=AsyncMock,
                return_value=None,
            ):
                job_id = await enqueue_gmail_personalization(sample_user_id)

        assert job_id is None
        assert "intelligence_job_id" not in store
        assert event["errors"] == [
            {
                "msg": f"{LogTag.ONBOARDING} personalization enqueue returned no job",
                "user_id": sample_user_id,
            }
        ]

    async def test_a_reconnect_after_the_marker_enqueues_nothing(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """Reconnecting Gmail is a no-op once the pipeline has run: a second run
        rewrites the holo card and seeds a second announcement conversation."""
        first = await enqueue_gmail_personalization(sample_user_id)
        store[GMAIL_PERSONALIZATION_MARKER] = "2026-08-01T00:00:00Z"

        second = await enqueue_gmail_personalization(sample_user_id)

        assert first is not None
        assert second is None
        assert await queued_job_names(arq_pool) == [INTELLIGENCE_TASK]

    async def test_a_legacy_user_with_a_house_but_no_marker_enqueues_nothing(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """Users who finished the pre-relocation onboarding already have their
        card; they carry `house` and no marker, and must not be re-run."""
        store[LEGACY_PERSONALIZATION_MARKER] = "explorer"

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
    """`is_intelligence_job_live` is what the Gmail-connect handler asks before
    re-enqueueing, so a wrong answer either starves a user of their
    personalization or runs two pipelines onto one WebSocket. Every case below
    is driven by real arq job state on the pool, never by mocking the function."""

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
        """in_progress is the state the queued-only check misses: the worker has
        already popped the job off the queue, and it is very much still running."""
        job_id = await enqueue_gmail_personalization(sample_user_id)
        assert job_id is not None
        await arq_pool.zrem(default_queue_name, job_id)
        await arq_pool.set(in_progress_key_prefix + job_id, b"1")

        assert await Job(job_id, redis=arq_pool).status() == JobStatus.in_progress
        assert await is_intelligence_job_live(sample_user_id) is True

    async def test_a_finished_job_is_not_live(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        """A completed job leaves its id behind on the user; treating that stale
        id as live would block the next connect from ever personalizing."""
        job_id = await enqueue_gmail_personalization(sample_user_id)
        assert job_id is not None
        await arq_pool.zrem(default_queue_name, job_id)
        await arq_pool.set(result_key_prefix + job_id, b"done")

        assert await Job(job_id, redis=arq_pool).status() == JobStatus.complete
        assert store["intelligence_job_id"] == job_id
        assert await is_intelligence_job_live(sample_user_id) is False

    async def test_an_id_arq_no_longer_knows_is_not_live(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        store["intelligence_job_id"] = "a-job-arq-never-heard-of"

        assert await is_intelligence_job_live(sample_user_id) is False

    async def test_no_stored_job_id_is_not_live(
        self, arq_pool: ArqRedis, store: dict[str, Any], sample_user_id: str
    ) -> None:
        assert "intelligence_job_id" not in store
        assert await is_intelligence_job_live(sample_user_id) is False

    async def test_a_missing_user_is_not_live(self, arq_pool: ArqRedis) -> None:
        repo = AsyncMock()
        repo.get.return_value = None

        with patch("app.services.onboarding.intelligence_job.user_repository", repo):
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


class TestUpdateOnboardingPreferences:
    async def test_saving_the_answers_starts_writing_the_question(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        """The wizard's remaining screens are the whole latency budget for the
        one model call completion needs, so it has to start here, detached."""
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id, "platform_links": {"telegram": {"id": "tg-1"}}}
        )
        prefs = OnboardingPreferences(profession="founder", needs=[OnboardingNeed.INBOX])

        with (
            patch(f"{SERVICE}.spawn_background_task") as spawn,
            patch(f"{SERVICE}.prewarm_first_question") as prewarm,
        ):
            await update_onboarding_preferences(sample_user_id, prefs)

        spawn.assert_called_once()
        assert prewarm.call_args.args == (sample_user_id, prefs, "telegram")
        # The task name is how this shows up in the wide event; unnamed, a stuck
        # prewarm is indistinguishable from every other background task.
        assert spawn.call_args.kwargs["name"] == f"prewarm_first_question:{sample_user_id}"

    async def test_a_user_with_no_linked_platform_prewarms_without_one(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        """Linking is optional and happens on a later screen. With no default for
        the lookup, the save raises instead of prewarming."""
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id}
        )
        prefs = OnboardingPreferences(profession="founder")

        with (
            patch(f"{SERVICE}.spawn_background_task"),
            patch(f"{SERVICE}.prewarm_first_question") as prewarm,
        ):
            await update_onboarding_preferences(sample_user_id, prefs)

        assert prewarm.call_args.args == (sample_user_id, prefs, None)

    async def test_a_missing_user_is_a_404_that_says_so(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        """The settings page shows this detail verbatim."""
        mock_repo.update_onboarding_preferences.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_onboarding_preferences(
                sample_user_id, OnboardingPreferences(profession="founder")
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "User not found"

    async def test_a_failed_prewarm_never_fails_the_save(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id}
        )
        prefs = OnboardingPreferences(profession="founder")

        with patch(f"{SERVICE}.spawn_background_task", side_effect=RuntimeError("no loop")):
            result = await update_onboarding_preferences(sample_user_id, prefs)

        assert result["user_id"] == sample_user_id

    async def test_a_failed_prewarm_is_reported_with_its_cause(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        """Swallowed by design, so this warning is the only trace. Without the
        error and its type it says a prewarm failed and nothing about why."""
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id}
        )

        with (
            patch(f"{SERVICE}.spawn_background_task", side_effect=RuntimeError("no loop")),
            patch(f"{SERVICE}.log") as log,
        ):
            await update_onboarding_preferences(
                sample_user_id, OnboardingPreferences(profession="founder")
            )

        log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} could not start the first question prewarm",
            user_id=sample_user_id,
            error="no loop",
            error_type="RuntimeError",
        )

    async def test_a_long_prewarm_failure_is_truncated_before_it_reaches_the_event(
        self, mock_repo: MagicMock, sample_user_id: str
    ) -> None:
        """The cause is attacker-influenced text of any length (a provider body,
        a stack of nested messages). Unbounded, one failed prewarm can dominate
        the wide event it shares with the rest of the request."""
        mock_repo.update_onboarding_preferences.return_value = UserDocument.model_validate(
            {"id": sample_user_id}
        )
        cause = "x" * 250

        with (
            patch(f"{SERVICE}.spawn_background_task", side_effect=RuntimeError(cause)),
            patch(f"{SERVICE}.log") as log,
        ):
            await update_onboarding_preferences(
                sample_user_id, OnboardingPreferences(profession="founder")
            )

        assert log.warning.call_args.kwargs["error"] == "x" * 200

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
        request = OnboardingRequest(profession="  Engineer  ", needs=["memory"], timezone=" UTC ")
        await complete_onboarding(sample_user_id, request)

        kwargs = mock_repo.complete_onboarding.await_args.kwargs
        assert kwargs["timezone"] == "UTC"
        assert kwargs["preferences"] == OnboardingPreferences(
            profession="Engineer",
            needs=[OnboardingNeed.MEMORY],
            response_style="casual",
            custom_instructions=None,
        )
