"""Unit tests for the Gmail personalization pipeline orchestration.

`process_onboarding_intelligence` runs once, when a user connects Gmail. The
tests below pin down its two early exits (already personalized, Gmail not
connected), which nodes the happy path runs and in what shape, that the pipeline
creates nothing the user has to clean up (no todos, no workflows), and that the
tail announces the result and stamps the marker that makes a reconnect a no-op.

Every node is faked at its own function boundary so the orchestration itself —
guard order, wiring, the context threaded through it — is what is under test.
"""

from dataclasses import replace
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.constants.notifications import MEMORY_SETTINGS_URL
from app.constants.onboarding import (
    GMAIL_PERSONALIZATION_MARKER,
    LEGACY_PERSONALIZATION_MARKER,
)
from app.models.notification.notification_models import (
    ActionStyle,
    ActionType,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.onboarding_models import (
    EmailSummary,
    InboxTriage,
    SocialProfile,
    WritingStyleExampleBlocks,
    WritingStyleProfile,
)
from app.models.user_models import UserDocument
from app.services.onboarding import intelligence_service
from app.services.onboarding.intelligence_service import (
    InboxScanContext,
    OnboardingContext,
    _announce_personalization,
    _holo_card_message,
    _scan_then_enqueue_memory,
    holo_card_url,
    process_onboarding_intelligence,
)

MODULE = "app.services.onboarding.intelligence_service"
USER = "user-42"

# Everything the refactor removed. Each of these was a node the pipeline used to
# run; a re-import of any of them silently reinstates work the user must clean up.
REMOVED_FROM_THE_PIPELINE = (
    "process_onboarding_workflows_phase",
    "_finalize_onboarding",
    "_finish_early_phase",
    "_wait_for_early_phase",
    "_persist_completion",
    "_start_gmail_branch",
    "_run_provision_gmail",
    "_seed_conversation",
    "_safe_run",
    "_run_todos",
    "_create_todos_from_triage",
    "_create_focus_todos",
    "_run_workflows",
    "_create_onboarding_workflows",
    "_create_fallback_workflow",
    "_build_one_workflow",
    "_generate_workflow_specs",
    "_fetch_onboarding_todos",
    "_triage_from_doc",
    "_writing_style_from_doc",
)


@pytest.fixture(autouse=True)
def quiet_logs() -> Any:
    with patch(f"{MODULE}.log", MagicMock()):
        yield


def _triage() -> InboxTriage:
    return InboxTriage(
        total_scanned=9,
        total_unread=2,
        summary="Busy",
        important_emails=[EmailSummary(sender="a@x.com", subject="s", why_important="w")],
        patterns=["p"],
    )


def _style() -> WritingStyleProfile:
    return WritingStyleProfile(summary="Terse", example=WritingStyleExampleBlocks(body=["Thanks."]))


def _user(**overrides: Any) -> UserDocument:
    payload: dict[str, Any] = {
        "id": USER,
        "name": "Ann",
        "email": "ann@x.com",
        "onboarding": {
            "preferences": {"profession": "lawyer"},
            "focus": "close Q3",
            "clarify_answers": [{"kind": "goal", "value": "grow"}],
        },
    }
    payload.update(overrides)
    return UserDocument(**payload)


def _expected_ctx() -> OnboardingContext:
    """The context `_user()` must produce, field for field."""
    return OnboardingContext(
        user_id=USER,
        name="Ann",
        profession="lawyer",
        focus="close Q3",
        user_email="ann@x.com",
        clarify_answers=[{"kind": "goal", "value": "grow"}],
    )


# ---------------------------------------------------------------------------
# _scan_then_enqueue_memory
# ---------------------------------------------------------------------------


class TestScanThenEnqueueMemory:
    async def test_queues_memory_ingestion_after_the_scan(self) -> None:
        order: list[str] = []
        pool = MagicMock()

        async def scan(user_id: str, ctx: Any) -> None:
            order.append("scan")

        async def enqueue(job: str, uid: str) -> None:
            order.append(f"enqueue:{job}")

        pool.enqueue_job = AsyncMock(side_effect=enqueue)
        with (
            patch(f"{MODULE}._run_inbox_scanning", AsyncMock(side_effect=scan)),
            patch(f"{MODULE}.RedisPoolManager") as manager,
        ):
            manager.get_pool = AsyncMock(return_value=pool)
            await _scan_then_enqueue_memory(USER, InboxScanContext())

        assert order == ["scan", "enqueue:process_gmail_emails_to_memory"]
        assert pool.enqueue_job.await_args.args == ("process_gmail_emails_to_memory", USER)

    async def test_a_queue_failure_does_not_fail_the_scan(self) -> None:
        # The visible scan already succeeded; losing durable ingestion must not
        # surface as a pipeline error.
        with (
            patch(f"{MODULE}._run_inbox_scanning", AsyncMock()),
            patch(f"{MODULE}.RedisPoolManager") as manager,
        ):
            manager.get_pool = AsyncMock(side_effect=RuntimeError("redis down"))
            await _scan_then_enqueue_memory(USER, InboxScanContext())


# ---------------------------------------------------------------------------
# process_onboarding_intelligence
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_stack() -> Any:
    """Fakes every node so only the orchestration is exercised.

    `personalization_already_ran` is deliberately NOT faked — the guard reads the
    user's real onboarding subdoc, so the tests drive it with real markers.
    """
    with (
        patch(f"{MODULE}.user_repository") as repo,
        patch(f"{MODULE}.get_composio_service") as composio,
        patch(f"{MODULE}._scan_then_enqueue_memory", AsyncMock()) as scan,
        patch(f"{MODULE}._run_writing_style", AsyncMock(return_value=None)) as style,
        patch(f"{MODULE}._run_triage", AsyncMock(return_value=None)) as triage,
        patch(f"{MODULE}._persist_profiles", AsyncMock()) as persist,
        patch(f"{MODULE}._run_social_profiles", AsyncMock(return_value=[])) as social,
        patch(f"{MODULE}._run_holo_card", AsyncMock(return_value=True)) as holo,
        patch(f"{MODULE}._announce_personalization", AsyncMock(return_value="conv-1")) as announce,
    ):
        repo.get = AsyncMock(return_value=_user())
        repo.mark_gmail_personalization_done = AsyncMock()
        service = MagicMock()
        service.check_connection_status = AsyncMock(return_value={"gmail": True})
        composio.return_value = service

        yield {
            "repo": repo,
            "composio": service,
            "scan": scan,
            "style": style,
            "triage": triage,
            "persist": persist,
            "social": social,
            "holo": holo,
            "announce": announce,
        }


class TestProcessOnboardingIntelligenceGuards:
    async def test_an_unknown_user_aborts_before_the_gmail_check(self, pipeline_stack: Any) -> None:
        pipeline_stack["repo"].get = AsyncMock(return_value=None)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["composio"].check_connection_status.await_count == 0
        assert pipeline_stack["scan"].await_count == 0
        assert pipeline_stack["repo"].mark_gmail_personalization_done.await_count == 0

    async def test_an_already_personalized_user_is_a_no_op(self, pipeline_stack: Any) -> None:
        # A queued job can outlive a second connect that already finished the
        # pipeline — re-running would re-scan the inbox and re-seed a conversation.
        user = _user(onboarding={GMAIL_PERSONALIZATION_MARKER: "2026-08-01T00:00:00Z"})
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["scan"].await_count == 0
        assert pipeline_stack["triage"].await_count == 0
        assert pipeline_stack["style"].await_count == 0
        assert pipeline_stack["composio"].check_connection_status.await_count == 0
        assert pipeline_stack["announce"].await_count == 0
        assert pipeline_stack["repo"].mark_gmail_personalization_done.await_count == 0

    async def test_the_legacy_marker_also_short_circuits(self, pipeline_stack: Any) -> None:
        # Users who finished the pre-relocation onboarding carry holo-card fields
        # but no marker; re-running for them would duplicate everything they have.
        user = _user(onboarding={LEGACY_PERSONALIZATION_MARKER: "mistgrove"})
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["scan"].await_count == 0
        assert pipeline_stack["announce"].await_count == 0

    async def test_gmail_not_connected_aborts_before_scanning(self, pipeline_stack: Any) -> None:
        pipeline_stack["composio"].check_connection_status = AsyncMock(
            return_value={"gmail": False}
        )

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["scan"].await_count == 0
        assert pipeline_stack["triage"].await_count == 0
        assert pipeline_stack["style"].await_count == 0
        assert pipeline_stack["announce"].await_count == 0
        assert pipeline_stack["repo"].mark_gmail_personalization_done.await_count == 0

    async def test_an_absent_gmail_key_is_treated_as_not_connected(
        self, pipeline_stack: Any
    ) -> None:
        pipeline_stack["composio"].check_connection_status = AsyncMock(return_value={})

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["scan"].await_count == 0

    async def test_an_already_personalized_user_is_logged_as_skipped_not_failed(
        self, pipeline_stack: Any
    ) -> None:
        """Three no-op exits look identical from outside the job; `outcome` and
        `reason` are the only things that tell a skipped reconnect apart from a
        user whose Gmail fell off, and the second needs chasing."""
        user = _user(onboarding={GMAIL_PERSONALIZATION_MARKER: "2026-08-01T00:00:00Z"})
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        intelligence_service.log.info.assert_any_call(
            f"{LogTag.ONBOARDING} pipeline skipped",
            user_id=USER,
            outcome="skipped",
            reason="already_ran",
        )

    async def test_a_disconnected_gmail_is_logged_as_aborted_with_its_reason(
        self, pipeline_stack: Any
    ) -> None:
        pipeline_stack["composio"].check_connection_status = AsyncMock(
            return_value={"gmail": False}
        )

        await process_onboarding_intelligence(USER)

        intelligence_service.log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} pipeline aborted — gmail not connected",
            user_id=USER,
            outcome="aborted",
            reason="no_gmail",
        )

    async def test_the_connection_check_names_gmail_and_the_user(self, pipeline_stack: Any) -> None:
        await process_onboarding_intelligence(USER)

        assert pipeline_stack["composio"].check_connection_status.await_args.args == (
            ["gmail"],
            USER,
        )


class TestProcessOnboardingIntelligenceHappyPath:
    async def test_every_kept_stage_runs_once(self, pipeline_stack: Any) -> None:
        await process_onboarding_intelligence(USER)

        assert pipeline_stack["scan"].await_count == 1
        assert pipeline_stack["triage"].await_count == 1
        assert pipeline_stack["style"].await_count == 1
        assert pipeline_stack["persist"].await_count == 1
        assert pipeline_stack["social"].await_count == 1
        assert pipeline_stack["holo"].await_count == 1
        assert pipeline_stack["announce"].await_count == 1

    async def test_the_scan_and_triage_share_one_inbox_context(self, pipeline_stack: Any) -> None:
        """Triage starts as soon as the scan has buffered its first batch, which
        only works if both hold the same context object — a second instance
        leaves triage waiting on an event nothing ever sets."""
        await process_onboarding_intelligence(USER)

        scanned_ctx = pipeline_stack["scan"].await_args.args[1]
        assert isinstance(scanned_ctx, InboxScanContext)
        # The scan runs detached, so a lost user id reads nobody's mailbox and
        # nothing downstream notices — the DAG still completes, empty.
        assert pipeline_stack["scan"].await_args.args[0] == USER
        assert pipeline_stack["triage"].await_args.args[1] is scanned_ctx

    async def test_the_pipeline_brackets_itself_with_a_start_and_a_done_line(
        self, pipeline_stack: Any
    ) -> None:
        """A personalization run has no other trace: `phase` is what pairs the
        two lines into a duration, and the counts are the only record of what a
        given user actually got out of it."""
        triage = _triage()
        pipeline_stack["triage"].return_value = triage
        pipeline_stack["style"].return_value = _style()
        pipeline_stack["social"].return_value = [SocialProfile(platform="x", url="u1")]

        await process_onboarding_intelligence(USER)

        intelligence_service.log.info.assert_any_call(
            f"{LogTag.ONBOARDING} pipeline start", user_id=USER, phase="start"
        )
        done = next(
            call
            for call in intelligence_service.log.info.call_args_list
            if call.kwargs.get("phase") == "done"
        )
        assert done.args == (f"{LogTag.ONBOARDING} pipeline done",)
        assert done.kwargs["user_id"] == USER
        assert done.kwargs["writing_style_learned"] is True
        assert done.kwargs["triage_important_count"] == len(triage.important_emails)
        assert done.kwargs["social_profiles_count"] == 1
        assert done.kwargs["conversation_seeded"] is True
        assert done.kwargs["outcome"] == "ok"

    async def test_a_run_that_found_nothing_reports_zero_not_one(self, pipeline_stack: Any) -> None:
        """`triage_important_count` is the volume metric for the whole feature —
        a floor of 1 on empty runs invents inbox findings that never existed."""
        await process_onboarding_intelligence(USER)

        done = next(
            call
            for call in intelligence_service.log.info.call_args_list
            if call.kwargs.get("phase") == "done"
        )
        assert done.kwargs["triage_important_count"] == 0
        assert done.kwargs["writing_style_learned"] is False
        assert done.kwargs["social_profiles_count"] == 0

    async def test_the_context_is_threaded_into_every_node(self, pipeline_stack: Any) -> None:
        """Every node reads its inputs off one context built from the user
        document, so a field dropped where it is built degrades several nodes at
        once — a card with no name, a triage with no focus. Pin the whole object."""
        await process_onboarding_intelligence(USER)

        assert pipeline_stack["triage"].await_args.args[0] == USER
        assert pipeline_stack["triage"].await_args.args[2:] == ("lawyer", "close Q3")
        assert pipeline_stack["style"].await_args.args == (USER, "lawyer")
        assert pipeline_stack["social"].await_args.args == (USER, "Ann", "ann@x.com")
        assert pipeline_stack["holo"].await_args.args[0] == replace(
            _expected_ctx(), triage=None, writing_style=None
        )

    async def test_the_resolved_triage_and_style_are_folded_into_the_card_context(
        self, pipeline_stack: Any
    ) -> None:
        """The two slowest nodes land after the base context is built, so they are
        folded in with `replace`. Losing either leaves the holo card blind to the
        inbox the user just waited on."""
        triage, style = _triage(), _style()
        pipeline_stack["triage"].return_value = triage
        pipeline_stack["style"].return_value = style

        await process_onboarding_intelligence(USER)

        expected = replace(_expected_ctx(), triage=triage, writing_style=style)
        assert pipeline_stack["holo"].await_args.args[0] == expected

    async def test_the_learned_profiles_are_persisted_before_the_card_is_built(
        self, pipeline_stack: Any
    ) -> None:
        triage, style = _triage(), _style()
        pipeline_stack["triage"].return_value = triage
        pipeline_stack["style"].return_value = style
        order: list[str] = []

        def _persist(*_args: Any) -> None:
            order.append("persist")

        def _holo(*_args: Any) -> bool:
            order.append("holo")
            return True

        pipeline_stack["persist"].side_effect = _persist
        pipeline_stack["holo"].side_effect = _holo

        await process_onboarding_intelligence(USER)

        assert order == ["persist", "holo"]
        assert pipeline_stack["persist"].await_args.args == (USER, style, triage)

    async def test_the_extracted_social_profiles_reach_the_card(self, pipeline_stack: Any) -> None:
        # The card renders them; recomputing or dropping them empties that row.
        profiles = [SocialProfile(platform="x", url="u1")]
        pipeline_stack["social"].return_value = profiles

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["holo"].await_args.args[2] is profiles

    async def test_the_loaded_user_document_reaches_the_card(self, pipeline_stack: Any) -> None:
        # Without it the card node re-reads Mongo for metadata it already has.
        user = _user()
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["holo"].await_args.args[1] is user

    async def test_the_marker_is_stamped_once_with_the_seeded_conversation_id(
        self, pipeline_stack: Any
    ) -> None:
        """The marker is what makes a Gmail reconnect a no-op, and the seeded
        conversation id rides along so a reset can tear it down."""
        pipeline_stack["announce"].return_value = "conv-7"

        await process_onboarding_intelligence(USER)

        mark = pipeline_stack["repo"].mark_gmail_personalization_done
        assert mark.await_count == 1
        assert mark.await_args.args == (USER,)
        assert mark.await_args.kwargs == {"conversation_id": "conv-7"}

    async def test_a_failed_announcement_still_stamps_the_marker(self, pipeline_stack: Any) -> None:
        # An undelivered reward must not leave the user eligible for a re-run.
        pipeline_stack["announce"].return_value = None

        await process_onboarding_intelligence(USER)

        mark = pipeline_stack["repo"].mark_gmail_personalization_done
        assert mark.await_count == 1
        assert mark.await_args.kwargs == {"conversation_id": None}

    async def test_the_card_outcome_decides_what_is_announced(self, pipeline_stack: Any) -> None:
        await process_onboarding_intelligence(USER)

        assert pipeline_stack["announce"].await_args.args == (USER,)
        assert pipeline_stack["announce"].await_args.kwargs == {"card_ready": True}

    async def test_a_card_that_failed_to_generate_is_announced_as_absent(
        self, pipeline_stack: Any
    ) -> None:
        """The public /profile page 404s until the card exists, so a failed card
        must never be advertised — and with nothing to hand over there is no
        conversation to record against the marker."""
        pipeline_stack["holo"].return_value = False
        pipeline_stack["announce"].return_value = None

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["announce"].await_args.kwargs == {"card_ready": False}
        mark = pipeline_stack["repo"].mark_gmail_personalization_done
        assert mark.await_count == 1
        assert mark.await_args.kwargs == {"conversation_id": None}

    async def test_a_nameless_user_gets_a_friendly_default(self, pipeline_stack: Any) -> None:
        pipeline_stack["repo"].get = AsyncMock(return_value=_user(name=None))

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["social"].await_args.args[1] == "there"
        assert pipeline_stack["holo"].await_args.args[0].name == "there"

    async def test_a_missing_onboarding_subdoc_does_not_crash_the_pipeline(
        self, pipeline_stack: Any
    ) -> None:
        pipeline_stack["repo"].get = AsyncMock(return_value=_user(onboarding=None))

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["holo"].await_args.args[0] == OnboardingContext(
            user_id=USER, name="Ann", user_email="ann@x.com"
        )
        assert pipeline_stack["repo"].mark_gmail_personalization_done.await_count == 1


class TestProcessOnboardingIntelligenceCreatesNothingToCleanUp:
    async def test_no_todos_and_no_workflows_are_created(self, pipeline_stack: Any) -> None:
        """The pipeline's output is memories, a style, a triage, profiles and the
        card. Anything it persists on the user's behalf is theirs to delete."""
        with (
            patch(
                "app.services.todos.todo_service.TodoService.create_todo", AsyncMock()
            ) as create_todo,
            patch(
                "app.services.workflow.service.WorkflowService.create_workflow", AsyncMock()
            ) as create_workflow,
        ):
            await process_onboarding_intelligence(USER)

        assert create_todo.await_count == 0
        assert create_workflow.await_count == 0

    @pytest.mark.parametrize("name", REMOVED_FROM_THE_PIPELINE)
    def test_the_removed_nodes_are_gone_for_good(self, name: str) -> None:
        assert not hasattr(intelligence_service, name)


# ---------------------------------------------------------------------------
# The announcement tail
# ---------------------------------------------------------------------------

CARD_URL = "https://app.example.test/profile/user-42"


@pytest.fixture
def announce_stack() -> Any:
    frontend = MagicMock()
    frontend.FRONTEND_URL = "https://app.example.test"
    with (
        patch(f"{MODULE}.settings", frontend),
        patch(f"{MODULE}.notification_service") as notifications,
        patch(f"{MODULE}.seed_holo_card_conversation", AsyncMock(return_value="conv-1")) as seed,
    ):
        notifications.create_notification = AsyncMock()
        yield notifications, seed


class TestHoloCardUrl:
    def test_points_at_the_public_card_page_for_this_user(self, announce_stack: Any) -> None:
        # The route's card id *is* the user id — the card is live with no publish step.
        assert holo_card_url(USER) == CARD_URL

    def test_a_trailing_slash_on_the_frontend_url_is_not_doubled(self) -> None:
        frontend = MagicMock()
        frontend.FRONTEND_URL = "https://app.example.test/"
        with patch(f"{MODULE}.settings", frontend):
            assert holo_card_url(USER) == CARD_URL

    def test_only_the_trailing_separator_is_trimmed(self) -> None:
        """`rstrip("/")` takes a character SET, so a widened set would eat real
        characters off the end of a deployment URL and 404 the card page."""
        frontend = MagicMock()
        frontend.FRONTEND_URL = "https://app.example.test/X/"
        with patch(f"{MODULE}.settings", frontend):
            assert holo_card_url(USER) == "https://app.example.test/X/profile/user-42"


class TestHoloCardMessage:
    def test_the_card_travels_as_its_public_link(self) -> None:
        # Chat has no holo-card renderer, so a payload the client would drop is
        # not an option — the link has to be in the message body.
        assert CARD_URL in _holo_card_message(CARD_URL)

    def test_the_message_is_the_whole_reward_the_user_reads(self) -> None:
        """This text is the entire hand-off after a Gmail connect — it is seeded
        as GAIA's own turn, so it is prose a user reads, not a log line."""
        assert _holo_card_message(CARD_URL) == (
            "Your holo card is ready — I built it from what I learned in your inbox.\n\n"
            f"{CARD_URL}\n\n"
            "I also added a lot to your memories while I was in there."
        )


class TestAnnouncePersonalization:
    @pytest.mark.parametrize("card_ready", [True, False])
    async def test_creates_exactly_one_notification(
        self, announce_stack: Any, card_ready: bool
    ) -> None:
        notifications, _ = announce_stack

        await _announce_personalization(USER, card_ready=card_ready)

        assert notifications.create_notification.await_count == 1
        request = notifications.create_notification.await_args.args[0]
        assert request.user_id == USER
        assert request.source is NotificationSourceEnum.BACKGROUND_JOB
        assert request.content.title == "Check your memories — I just added a lot"

    async def test_the_notification_offers_the_memories_and_the_card(
        self, announce_stack: Any
    ) -> None:
        notifications, _ = announce_stack

        await _announce_personalization(USER, card_ready=True)

        content = notifications.create_notification.await_args.args[0].content
        assert [a.type for a in content.actions] == [ActionType.REDIRECT, ActionType.REDIRECT]
        assert [a.config.redirect.url for a in content.actions] == [MEMORY_SETTINGS_URL, CARD_URL]
        assert content.body.endswith("Your holo card is ready too.")

    async def test_a_card_that_does_not_exist_is_never_linked(self, announce_stack: Any) -> None:
        """The public card page 404s until the card is persisted, so a failed
        card must leave no link anywhere — action, body, or conversation."""
        notifications, seed = announce_stack

        assert await _announce_personalization(USER, card_ready=False) is None

        content = notifications.create_notification.await_args.args[0].content
        assert [a.config.redirect.url for a in content.actions] == [MEMORY_SETTINGS_URL]
        assert CARD_URL not in content.body
        assert "holo card" not in content.body
        assert seed.await_count == 0

    async def test_the_seeded_conversation_holds_the_card_url(self, announce_stack: Any) -> None:
        _, seed = announce_stack

        assert await _announce_personalization(USER, card_ready=True) == "conv-1"

        assert seed.await_args.args[0] == USER
        assert seed.await_args.args[1] == _holo_card_message(CARD_URL)
        assert CARD_URL in seed.await_args.args[1]

    async def test_an_undeliverable_notification_still_seeds_the_conversation(
        self, announce_stack: Any
    ) -> None:
        # Delivery is fail-soft: the user must not lose the card link because a
        # notification channel was down.
        notifications, seed = announce_stack
        notifications.create_notification = AsyncMock(side_effect=RuntimeError("channel down"))

        assert await _announce_personalization(USER, card_ready=True) == "conv-1"

        assert seed.await_args.args == (USER, ANY)

    async def test_a_failed_seed_reports_no_conversation(self, announce_stack: Any) -> None:
        with patch(f"{MODULE}.seed_holo_card_conversation", AsyncMock(return_value=None)):
            assert await _announce_personalization(USER, card_ready=True) is None

    async def test_the_notification_is_built_field_for_field(self, announce_stack: Any) -> None:
        """Every field here is rendered or acted on by the client: the labels are
        the buttons, the styles decide which one is primary, `open_in_new_tab`
        and `close_notification` decide whether the user loses the notification
        on the way to their memories, and `metadata.source` is what attributes
        the notification to this pipeline in analytics."""
        notifications, _ = announce_stack

        await _announce_personalization(USER, card_ready=True)

        request = notifications.create_notification.await_args.args[0]
        assert request.type is NotificationType.SUCCESS
        assert request.priority == 2
        assert request.metadata == {"source": "gmail_personalization"}
        memories, card = request.content.actions
        assert memories.label == "View memories"
        assert memories.style is ActionStyle.PRIMARY
        assert memories.config.redirect.url == MEMORY_SETTINGS_URL
        assert memories.config.redirect.open_in_new_tab is False
        assert memories.config.redirect.close_notification is True
        assert card.label == "See your holo card"
        assert card.style is ActionStyle.SECONDARY
        assert card.config.redirect.url == CARD_URL
        assert card.config.redirect.open_in_new_tab is True

    async def test_an_undeliverable_notification_is_visible_in_the_wide_event(
        self, announce_stack: Any
    ) -> None:
        """Delivery is swallowed on purpose, so the warning is the ONLY evidence
        a user was never told their personalization finished."""
        notifications, _ = announce_stack
        # Long on purpose: a provider stack trace is what actually lands here,
        # and the 200-char cap is what keeps one failure from flooding the event.
        blurb = "channel down: " + "x" * 500
        notifications.create_notification = AsyncMock(side_effect=RuntimeError(blurb))

        await _announce_personalization(USER, card_ready=True)

        intelligence_service.log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} personalization notification failed",
            user_id=USER,
            step="announce",
            error=blurb[:200],
            error_type="RuntimeError",
        )

    @pytest.mark.parametrize(("seeded", "outcome"), [("conv-1", "ok"), (None, "partial")])
    async def test_the_announce_line_reports_which_half_landed(
        self, announce_stack: Any, seeded: str | None, outcome: str
    ) -> None:
        """`outcome` is what separates a user who got their card handed over from
        one who got only a notification — the two are indistinguishable
        otherwise, and only this line records which happened."""
        with patch(f"{MODULE}.seed_holo_card_conversation", AsyncMock(return_value=seeded)):
            await _announce_personalization(USER, card_ready=True)

        intelligence_service.log.info.assert_called_once_with(
            f"{LogTag.ONBOARDING} announce done",
            user_id=USER,
            step="announce",
            card_ready=True,
            outcome=outcome,
            conversation_id=seeded,
        )
