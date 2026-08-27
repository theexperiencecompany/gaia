"""Unit tests for the onboarding pipeline orchestration.

`process_onboarding_intelligence` runs one of two shapes chosen at submission
time — `split` (Gmail connected: run the inbox work now, defer workflows to a
second job) and `full` (no Gmail: everything inline). The tests below pin down
which nodes each shape runs, what it persists, and that the tail always advances
the user's phase even when individual nodes fail.

Every node is faked at its own function boundary so the orchestration itself —
branch selection, wiring, ordering — is what is under test.
"""

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.onboarding_models import (
    CompletePayload,
    EmailSummary,
    InboxTriage,
    WritingStyleExampleBlocks,
    WritingStyleProfile,
)
from app.models.user_models import OnboardingPhase
from app.services.onboarding.first_message_service import default_first_message
from app.services.onboarding.intelligence_service import (
    InboxScanContext,
    OnboardingContext,
    OnboardingStage,
    _finalize_onboarding,
    _finish_early_phase,
    _persist_completion,
    _scan_then_enqueue_memory,
    _social_then_holo,
    _start_gmail_branch,
    process_onboarding_intelligence,
    process_onboarding_workflows_phase,
)

MODULE = "app.services.onboarding.intelligence_service"
USER = "user-42"


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


def _user(**overrides: Any) -> MagicMock:
    user = MagicMock()
    user.id = USER
    user.name = "Ann"
    user.email = "ann@x.com"
    user.timezone = "UTC"
    user.onboarding = {
        "preferences": {"profession": "lawyer"},
        "focus": "close Q3",
        "clarify_answers": [{"kind": "goal", "value": "grow"}],
        "selected_integrations": ["slack"],
        "pipeline_mode": "full",
    }
    for key, value in overrides.items():
        setattr(user, key, value)
    user.model_dump.return_value = {"name": user.name, "timezone": user.timezone}
    return user


def _expected_ctx() -> OnboardingContext:
    """The context `_user()` must produce, field for field."""
    return OnboardingContext(
        user_id=USER,
        name="Ann",
        profession="lawyer",
        focus="close Q3",
        has_gmail=False,
        user_timezone="UTC",
        user_email="ann@x.com",
        clarify_answers=[{"kind": "goal", "value": "grow"}],
    )


# ---------------------------------------------------------------------------
# Small orchestration helpers
# ---------------------------------------------------------------------------


class TestPersistCompletion:
    async def test_advances_the_user_to_personalization_complete(self) -> None:
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_pipeline_completion = AsyncMock()
            await _persist_completion(USER, "conv-1", None)

        kwargs = repo.set_pipeline_completion.await_args.kwargs
        assert repo.set_pipeline_completion.await_args.args[0] == USER
        assert kwargs["phase"] is OnboardingPhase.PERSONALIZATION_COMPLETE
        assert kwargs["conversation_id"] == "conv-1"

    async def test_an_empty_conversation_id_is_normalized_to_none(self) -> None:
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_pipeline_completion = AsyncMock()
            await _persist_completion(USER, "", None)

        assert repo.set_pipeline_completion.await_args.kwargs["conversation_id"] is None

    async def test_a_running_provision_task_is_kept_alive(self) -> None:
        done = asyncio.Event()

        async def slow() -> None:
            await done.wait()

        task = asyncio.create_task(slow())
        tasks: set[asyncio.Task] = set()
        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch("app.utils.background_tasks._background_tasks", tasks),
        ):
            repo.set_pipeline_completion = AsyncMock()
            await _persist_completion(USER, "c", task)
            # Without a strong reference the task can be garbage collected mid-flight.
            assert task in tasks

        done.set()
        await task

    async def test_a_finished_provision_task_is_not_retained(self) -> None:
        async def quick() -> None:
            return None

        task = asyncio.create_task(quick())
        await task

        tasks: set[asyncio.Task] = set()
        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch("app.utils.background_tasks._background_tasks", tasks),
        ):
            repo.set_pipeline_completion = AsyncMock()
            await _persist_completion(USER, "c", task)

        assert tasks == set()


class TestFinishEarlyPhase:
    async def test_marks_the_early_half_done(self) -> None:
        with patch(f"{MODULE}.user_repository") as repo:
            repo.mark_early_intelligence_done = AsyncMock()
            await _finish_early_phase(USER, None)

        assert repo.mark_early_intelligence_done.await_args.args == (USER,)

    async def test_a_running_provision_task_is_kept_alive(self) -> None:
        done = asyncio.Event()

        async def slow() -> None:
            await done.wait()

        task = asyncio.create_task(slow())
        tasks: set[asyncio.Task] = set()
        with (
            patch(f"{MODULE}.user_repository") as repo,
            patch("app.utils.background_tasks._background_tasks", tasks),
        ):
            repo.mark_early_intelligence_done = AsyncMock()
            await _finish_early_phase(USER, task)
            assert task in tasks

        done.set()
        await task


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


class TestStartGmailBranch:
    async def test_starts_the_scan_and_the_provision_task(self) -> None:
        with (
            patch(f"{MODULE}._scan_then_enqueue_memory", AsyncMock()) as scan,
            patch(f"{MODULE}._run_provision_gmail", AsyncMock()) as provision,
            patch("app.utils.background_tasks._background_tasks", set()),
        ):
            ctx, provision_future = _start_gmail_branch(USER)
            await asyncio.gather(provision_future)
            await asyncio.sleep(0)

        assert isinstance(ctx, InboxScanContext)
        assert scan.await_count == 1
        assert provision.await_count == 1

    async def test_the_scan_task_is_held_against_garbage_collection(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def scan(user_id: str, ctx: Any) -> None:
            started.set()
            await release.wait()

        tasks: set[asyncio.Task] = set()
        with (
            patch(f"{MODULE}._scan_then_enqueue_memory", AsyncMock(side_effect=scan)),
            patch(f"{MODULE}._run_provision_gmail", AsyncMock()),
            patch("app.utils.background_tasks._background_tasks", tasks),
        ):
            _, provision_future = _start_gmail_branch(USER)
            await started.wait()
            assert len(tasks) == 1

            release.set()
            await asyncio.sleep(0)
            await provision_future


class TestSocialThenHolo:
    async def test_gmail_users_get_social_extraction_before_the_card(self) -> None:
        profiles = [MagicMock()]
        with (
            patch(
                f"{MODULE}._run_social_profiles_background", AsyncMock(return_value=profiles)
            ) as social,
            patch(f"{MODULE}._run_holo_card", AsyncMock()) as holo,
        ):
            await _social_then_holo(
                OnboardingContext(
                    user_id=USER, name="Ann", user_email="ann@x.com", focus="focus", has_gmail=True
                ),
                {"_id": USER},
            )

        assert social.await_args.args == (USER, "Ann", "ann@x.com")
        # The extracted profiles must reach the card, not be recomputed.
        assert holo.await_args.args[2] is profiles

    async def test_without_gmail_the_card_is_built_from_no_profiles(self) -> None:
        with (
            patch(f"{MODULE}._run_social_profiles_background", AsyncMock()) as social,
            patch(f"{MODULE}._run_holo_card", AsyncMock()) as holo,
        ):
            await _social_then_holo(
                OnboardingContext(
                    user_id=USER, name="Ann", user_email="ann@x.com", focus="focus", has_gmail=False
                ),
                {"_id": USER},
            )

        assert social.await_count == 0
        assert holo.await_args.args[2] == []


# ---------------------------------------------------------------------------
# _finalize_onboarding
# ---------------------------------------------------------------------------


@pytest.fixture
def finalize_stack() -> Any:
    with (
        patch(f"{MODULE}.generate_first_message", AsyncMock(return_value="Hi Ann!")) as message,
        patch(f"{MODULE}.user_repository") as repo,
        patch(f"{MODULE}._seed_conversation", AsyncMock(return_value="conv-1")) as seed,
        patch(f"{MODULE}._emit_stage", AsyncMock()) as emit,
    ):
        repo.set_first_message = AsyncMock()
        repo.set_pipeline_completion = AsyncMock()
        yield message, repo, seed, emit


def _finalize_ctx(**overrides: Any) -> OnboardingContext:
    defaults: dict[str, Any] = {
        "user_id": USER,
        "name": "Ann",
        "profession": "lawyer",
        "focus": "close Q3",
    }
    defaults.update(overrides)
    return OnboardingContext(**defaults)


def _finalize_kwargs(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "todos": [],
        "workflows": [],
        "provision_future": None,
    }
    payload.update(overrides)
    return payload


class TestFinalizeOnboarding:
    async def test_returns_the_seeded_conversation_id(self, finalize_stack: Any) -> None:
        assert await _finalize_onboarding(_finalize_ctx(), **_finalize_kwargs()) == "conv-1"

    async def test_first_message_is_persisted_before_anything_else_writes(
        self, finalize_stack: Any
    ) -> None:
        # COMPLETE triggers a frontend fetch of /onboarding/personalization, and the
        # holo leg in `concurrent_tasks` writes that same document — so the message
        # has to land before the gather starts, not merely before the event.
        _, repo, seed, emit = finalize_stack
        order: list[str] = []
        repo.set_first_message = AsyncMock(side_effect=lambda *a: order.append("persist"))

        def _seed(*_args: Any) -> str:
            order.append("seed")
            return "conv-1"

        seed.side_effect = _seed
        emit.side_effect = lambda *a, **k: order.append("emit")

        async def side_work() -> None:
            order.append("side_work")

        await _finalize_onboarding(
            _finalize_ctx(), **_finalize_kwargs(), concurrent_tasks=(side_work(),)
        )

        assert order[0] == "persist"
        assert order.index("persist") < order.index("side_work") < order.index("emit")

    async def test_complete_carries_the_conversation_id(self, finalize_stack: Any) -> None:
        _, _, _, emit = finalize_stack
        await _finalize_onboarding(_finalize_ctx(), **_finalize_kwargs())

        stage, payload = emit.await_args.args[1], emit.await_args.args[2]
        assert stage is OnboardingStage.COMPLETE
        assert payload == CompletePayload(conversation_id="conv-1")

    async def test_context_reaches_the_message_generator(self, finalize_stack: Any) -> None:
        message, _, _, _ = finalize_stack
        triage, style = _triage(), _style()
        await _finalize_onboarding(
            _finalize_ctx(triage=triage, writing_style=style, has_gmail=True),
            **_finalize_kwargs(
                todos=[{"id": "t1"}],
                workflows=[{"id": "w1"}],
            ),
        )

        kwargs = message.await_args.kwargs
        assert kwargs["triage"] is triage
        assert kwargs["writing_style"] is style
        assert kwargs["created_todos"] == [{"id": "t1"}]
        assert kwargs["created_workflows"] == [{"id": "w1"}]
        assert kwargs["has_gmail"] is True

    async def test_every_write_in_the_tail_is_scoped_to_this_user(
        self, finalize_stack: Any
    ) -> None:
        """The tail writes the first message, seeds a conversation and flips the
        phase. Each takes the user id separately, and losing it on any one of
        them writes another user's record — or none at all — with no error."""
        _, repo, seed, _ = finalize_stack
        provision = MagicMock()
        provision.done.return_value = True

        with patch(f"{MODULE}._persist_completion", AsyncMock()) as persist:
            await _finalize_onboarding(
                _finalize_ctx(), **_finalize_kwargs(provision_future=provision)
            )

        repo.set_first_message.assert_awaited_once_with(USER, "Hi Ann!")
        seed.assert_awaited_once_with(USER)
        persist.assert_awaited_once_with(USER, "conv-1", provision)

    async def test_a_message_failure_falls_back_to_the_default_copy(
        self, finalize_stack: Any
    ) -> None:
        _, repo, _, _ = finalize_stack
        with patch(f"{MODULE}.generate_first_message", AsyncMock(side_effect=RuntimeError("llm"))):
            await _finalize_onboarding(_finalize_ctx(), **_finalize_kwargs())

        assert repo.set_first_message.await_args.args[1] == default_first_message("Ann")

    async def test_concurrent_tasks_run_alongside_seeding(self, finalize_stack: Any) -> None:
        ran = asyncio.Event()

        async def side_work() -> None:
            ran.set()

        await _finalize_onboarding(
            _finalize_ctx(), **_finalize_kwargs(), concurrent_tasks=(side_work(),)
        )

        assert ran.is_set()

    async def test_completion_is_persisted_even_when_seeding_fails(
        self, finalize_stack: Any
    ) -> None:
        # The user must still advance out of the personalization phase.
        _, repo, _, emit = finalize_stack
        with patch(f"{MODULE}._seed_conversation", AsyncMock(return_value=None)):
            assert await _finalize_onboarding(_finalize_ctx(), **_finalize_kwargs()) is None

        assert repo.set_pipeline_completion.await_count == 1
        assert emit.await_args.args[2] == CompletePayload(conversation_id=None)


# ---------------------------------------------------------------------------
# process_onboarding_intelligence
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_stack() -> Any:
    """Fakes every node so only the orchestration is exercised."""
    with (
        patch(f"{MODULE}._emit_stage", AsyncMock()) as emit,
        patch(f"{MODULE}.user_repository") as repo,
        patch(f"{MODULE}.get_composio_service") as composio,
        patch(f"{MODULE}._start_gmail_branch") as gmail_branch,
        patch(f"{MODULE}._run_writing_style", AsyncMock(return_value=None)) as style,
        patch(f"{MODULE}._run_triage", AsyncMock(return_value=None)) as triage,
        patch(f"{MODULE}._run_todos", AsyncMock(return_value=[])) as todos,
        patch(f"{MODULE}._run_workflows", AsyncMock(return_value=[])) as workflows,
        patch(f"{MODULE}._persist_profiles", AsyncMock()) as persist,
        patch(f"{MODULE}._social_then_holo", AsyncMock()) as social_holo,
        patch(f"{MODULE}._finalize_onboarding", AsyncMock(return_value="conv-1")) as finalize,
        patch(f"{MODULE}._finish_early_phase", AsyncMock()) as finish_early,
    ):
        repo.get = AsyncMock(return_value=_user())
        service = MagicMock()
        service.check_connection_status = AsyncMock(return_value={"gmail": False})
        composio.return_value = service

        async def _close_side_work(*_args: Any, **kwargs: Any) -> str:
            # The real tail awaits these; closing them keeps the fake from
            # leaking "coroutine was never awaited" warnings.
            for coro in kwargs.get("concurrent_tasks", ()):
                coro.close()
            return "conv-1"

        finalize.side_effect = _close_side_work

        provision_future = MagicMock()
        gmail_branch.return_value = (InboxScanContext(), provision_future)

        yield {
            "emit": emit,
            "repo": repo,
            "composio": service,
            "gmail_branch": gmail_branch,
            "style": style,
            "triage": triage,
            "todos": todos,
            "workflows": workflows,
            "persist": persist,
            "social_holo": social_holo,
            "finalize": finalize,
            "finish_early": finish_early,
            "provision_future": provision_future,
        }


class TestProcessOnboardingIntelligence:
    async def test_activity_is_announced_before_any_slow_check(self, pipeline_stack: Any) -> None:
        # Both first-step cards must light up before the Composio round trip.
        await process_onboarding_intelligence(USER)

        first_two = {call.args[1] for call in pipeline_stack["emit"].await_args_list[:2]}
        assert first_two == {OnboardingStage.INBOX_SCANNING, OnboardingStage.TODOS_CREATING}

    async def test_an_unknown_user_aborts_before_doing_work(self, pipeline_stack: Any) -> None:
        pipeline_stack["repo"].get = AsyncMock(return_value=None)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["style"].await_count == 0
        assert pipeline_stack["finalize"].await_count == 0

    async def test_without_gmail_no_inbox_branch_is_started(self, pipeline_stack: Any) -> None:
        await process_onboarding_intelligence(USER)

        assert pipeline_stack["gmail_branch"].call_count == 0
        assert pipeline_stack["triage"].await_args.args[1] is None

    async def test_with_gmail_the_inbox_branch_is_started(self, pipeline_stack: Any) -> None:
        pipeline_stack["composio"].check_connection_status = AsyncMock(return_value={"gmail": True})
        await process_onboarding_intelligence(USER)

        assert pipeline_stack["gmail_branch"].call_count == 1
        assert pipeline_stack["triage"].await_args.args[1] is not None

    async def test_full_mode_runs_workflows_and_finalizes(self, pipeline_stack: Any) -> None:
        await process_onboarding_intelligence(USER)

        assert pipeline_stack["workflows"].await_count == 1
        assert pipeline_stack["finalize"].await_count == 1
        assert pipeline_stack["finish_early"].await_count == 0

    async def test_split_mode_defers_workflows_to_the_second_job(self, pipeline_stack: Any) -> None:
        user = _user()
        user.onboarding = {**user.onboarding, "pipeline_mode": "split"}
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["workflows"].await_count == 0
        assert pipeline_stack["finalize"].await_count == 0
        assert pipeline_stack["finish_early"].await_count == 1

    async def test_split_mode_still_persists_profiles_and_builds_the_card(
        self, pipeline_stack: Any
    ) -> None:
        user = _user()
        user.onboarding = {**user.onboarding, "pipeline_mode": "split"}
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["persist"].await_count == 1
        # The card leg gets the resolved context AND the user document: the
        # card is rendered from both, so either being dropped empties it.
        assert pipeline_stack["social_holo"].call_args.args == (
            replace(_expected_ctx(), triage=None, writing_style=None),
            user,
        )

    async def test_an_absent_pipeline_mode_defaults_to_full(self, pipeline_stack: Any) -> None:
        user = _user()
        user.onboarding = {"focus": "f"}
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["finalize"].await_count == 1

    async def test_full_mode_hands_its_side_work_to_the_tail(self, pipeline_stack: Any) -> None:
        await process_onboarding_intelligence(USER)

        concurrent = pipeline_stack["finalize"].await_args.kwargs["concurrent_tasks"]
        assert len(concurrent) == 2
        # Built here, awaited by the tail — so this is call_args, not await_args.
        assert pipeline_stack["social_holo"].call_args.args == (
            replace(_expected_ctx(), triage=None, writing_style=None),
            pipeline_stack["repo"].get.return_value,
        )

    async def test_onboarding_context_is_threaded_into_the_nodes(self, pipeline_stack: Any) -> None:
        """Every node downstream reads its inputs off one context object, so a
        field dropped where it is built silently degrades every node at once —
        todos with no focus, a card with no name, a schedule in the wrong zone.
        Pin the whole object, not its type."""
        await process_onboarding_intelligence(USER)

        assert pipeline_stack["style"].await_args.args == (USER, False, "lawyer")
        assert pipeline_stack["triage"].await_args.args == (USER, None, "lawyer", "close Q3")

        base = _expected_ctx()
        # _run_todos gets the base context plus the triage task it waits on.
        todo_args = pipeline_stack["todos"].await_args.args
        assert todo_args[0] == base
        assert isinstance(todo_args[1], asyncio.Task)
        # The workflows and finalize legs each get it with the resolved triage
        # and writing style folded in — here both nodes returned None.
        resolved = replace(base, triage=None, writing_style=None)
        assert pipeline_stack["workflows"].await_args.args == (resolved, ["slack"])
        assert pipeline_stack["finalize"].await_args.args == (resolved,)

    async def test_the_resolved_triage_and_style_are_folded_into_the_context(
        self, pipeline_stack: Any
    ) -> None:
        """The two slowest nodes land after the base context is built, so they
        are folded in with `replace`. Losing either leaves the workflow and
        first-message legs blind to the inbox the user just waited on."""
        triage, style = _triage(), _style()
        pipeline_stack["triage"].return_value = triage
        pipeline_stack["style"].return_value = style
        pipeline_stack["composio"].check_connection_status = AsyncMock(return_value={"gmail": True})

        await process_onboarding_intelligence(USER)

        expected = replace(_expected_ctx(), has_gmail=True, triage=triage, writing_style=style)
        assert pipeline_stack["workflows"].await_args.args == (expected, ["slack"])
        assert pipeline_stack["finalize"].await_args.args == (expected,)
        assert pipeline_stack["social_holo"].call_args.args[0] == expected

    async def test_a_nameless_user_gets_a_friendly_default(self, pipeline_stack: Any) -> None:
        user = _user(name=None)
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["finalize"].await_args.args[0].name == "there"

    @pytest.mark.parametrize("stored", [None, "", "   "])
    async def test_a_blank_timezone_falls_back_to_utc(
        self, pipeline_stack: Any, stored: str | None
    ) -> None:
        user = _user(timezone=stored)
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["workflows"].await_args.args[0].user_timezone == "UTC"

    async def test_a_stored_timezone_is_used(self, pipeline_stack: Any) -> None:
        user = _user(timezone="Europe/London")
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["workflows"].await_args.args[0].user_timezone == "Europe/London"

    async def test_a_missing_onboarding_subdoc_does_not_crash_the_pipeline(
        self, pipeline_stack: Any
    ) -> None:
        user = _user()
        user.onboarding = None
        pipeline_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_intelligence(USER)

        assert pipeline_stack["finalize"].await_count == 1


# ---------------------------------------------------------------------------
# process_onboarding_workflows_phase
# ---------------------------------------------------------------------------


@pytest.fixture
def phase_stack() -> Any:
    with (
        patch(f"{MODULE}._wait_for_early_phase", AsyncMock(return_value=True)) as wait,
        patch(f"{MODULE}.user_repository") as repo,
        patch(f"{MODULE}.workflow_repository") as workflows_repo,
        patch(f"{MODULE}.get_composio_service") as composio,
        patch(f"{MODULE}._run_workflows", AsyncMock(return_value=[{"id": "w1"}])) as run,
        patch(f"{MODULE}._fetch_onboarding_todos", AsyncMock(return_value=[{"id": "t1"}])),
        patch(f"{MODULE}._finalize_onboarding", AsyncMock(return_value="conv-1")) as finalize,
    ):
        repo.get = AsyncMock(return_value=_user())
        workflows_repo.delete_many_for_user = AsyncMock(return_value=0)
        service = MagicMock()
        service.check_connection_status = AsyncMock(return_value={"gmail": True})
        composio.return_value = service
        yield {
            "wait": wait,
            "repo": repo,
            "workflows_repo": workflows_repo,
            "run": run,
            "finalize": finalize,
        }


class TestProcessOnboardingWorkflowsPhase:
    async def test_waits_for_the_early_phase_before_reading_the_user(
        self, phase_stack: Any
    ) -> None:
        await process_onboarding_workflows_phase(USER)
        assert phase_stack["wait"].await_count == 1

    async def test_an_unknown_user_aborts(self, phase_stack: Any) -> None:
        phase_stack["repo"].get = AsyncMock(return_value=None)

        await process_onboarding_workflows_phase(USER)

        assert phase_stack["run"].await_count == 0
        assert phase_stack["finalize"].await_count == 0

    async def test_runs_workflows_then_finalizes(self, phase_stack: Any) -> None:
        await process_onboarding_workflows_phase(USER)

        assert phase_stack["run"].await_count == 1
        assert phase_stack["finalize"].await_args.kwargs["workflows"] == [{"id": "w1"}]
        assert phase_stack["finalize"].await_args.kwargs["todos"] == [{"id": "t1"}]

    async def test_persisted_learnings_are_rebuilt_for_the_prompt(self, phase_stack: Any) -> None:
        # The early phase persisted these; this job must not re-derive them.
        user = _user()
        user.onboarding = {
            **user.onboarding,
            "triage_summary": {"total_scanned": 5, "total_unread": 1, "summary": "S"},
            "writing_style": {"summary": "Terse", "example": {"body": ["x"]}},
        }
        phase_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_workflows_phase(USER)

        ctx = phase_stack["run"].await_args.args[0]
        assert ctx.triage is not None and ctx.triage.total_scanned == 5
        assert ctx.writing_style is not None and ctx.writing_style.summary == "Terse"

    async def test_absent_learnings_degrade_to_none(self, phase_stack: Any) -> None:
        await process_onboarding_workflows_phase(USER)

        ctx = phase_stack["run"].await_args.args[0]
        assert ctx.triage is None
        assert ctx.writing_style is None

    async def test_the_second_job_rebuilds_the_whole_context_and_the_selection(
        self, phase_stack: Any
    ) -> None:
        """This job re-derives the context from Mongo rather than inheriting the
        early phase's, so a field missed here reaches only the workflow leg —
        no other assertion in this pipeline would notice."""
        await process_onboarding_workflows_phase(USER)

        assert phase_stack["run"].await_args.args == (
            OnboardingContext(
                user_id=USER,
                name="Ann",
                profession="lawyer",
                focus="close Q3",
                # The fixture's composio stub reports gmail connected here.
                has_gmail=True,
                user_timezone="UTC",
                clarify_answers=[{"kind": "goal", "value": "grow"}],
            ),
            ["slack"],
        )

    async def test_a_stored_timezone_reaches_the_workflow_leg(self, phase_stack: Any) -> None:
        """Workflow schedules are written in this zone; defaulting to UTC fires
        every onboarding automation at the wrong hour for most of the world."""
        user = _user(timezone="Europe/London")
        phase_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_workflows_phase(USER)

        assert phase_stack["run"].await_args.args[0].user_timezone == "Europe/London"

    async def test_a_retry_purges_the_previous_suggestions(self, phase_stack: Any) -> None:
        # Without this, a killed run that already created workflows doubles up.
        user = _user()
        user.onboarding = {**user.onboarding, "suggested_workflows": ["w-old-1", "w-old-2"]}
        phase_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_workflows_phase(USER)

        assert phase_stack["workflows_repo"].delete_many_for_user.await_args.args == (
            ["w-old-1", "w-old-2"],
            USER,
        )

    async def test_a_first_run_purges_nothing(self, phase_stack: Any) -> None:
        await process_onboarding_workflows_phase(USER)

        assert phase_stack["workflows_repo"].delete_many_for_user.await_count == 0

    async def test_the_purge_happens_before_regenerating(self, phase_stack: Any) -> None:
        user = _user()
        user.onboarding = {**user.onboarding, "suggested_workflows": ["w-old"]}
        phase_stack["repo"].get = AsyncMock(return_value=user)
        order: list[str] = []

        def _purge(*_args: Any) -> int:
            order.append("purge")
            return 1

        def _regenerate(*_args: Any, **_kwargs: Any) -> list[dict]:
            order.append("regenerate")
            return []

        phase_stack["workflows_repo"].delete_many_for_user = AsyncMock(side_effect=_purge)
        phase_stack["run"].side_effect = _regenerate

        await process_onboarding_workflows_phase(USER)

        assert order == ["purge", "regenerate"]

    async def test_gmail_state_is_rechecked_for_this_phase(self, phase_stack: Any) -> None:
        # The user may have connected or revoked Gmail while picking integrations.
        await process_onboarding_workflows_phase(USER)

        ctx = phase_stack["run"].await_args.args[0]
        assert ctx.has_gmail is True
        assert phase_stack["finalize"].await_args.args[0].has_gmail is True

    @pytest.mark.parametrize("stored", [None, "", "   "])
    async def test_a_blank_timezone_falls_back_to_utc(
        self, phase_stack: Any, stored: str | None
    ) -> None:
        user = _user(timezone=stored)
        phase_stack["repo"].get = AsyncMock(return_value=user)

        await process_onboarding_workflows_phase(USER)

        assert phase_stack["run"].await_args.args[0].user_timezone == "UTC"

    async def test_no_provision_task_is_handed_to_the_tail(self, phase_stack: Any) -> None:
        # Provisioning belongs to the first job; this one has nothing to keep alive.
        await process_onboarding_workflows_phase(USER)

        assert phase_stack["finalize"].await_args.kwargs["provision_future"] is None
