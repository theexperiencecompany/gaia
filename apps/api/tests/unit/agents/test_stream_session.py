"""Unit tests for the per-stream session model (session.py).

Pins the orchestration-state invariants: one session per stream, teardown
leaves no residue, the tool_data ownership truth table, and the background
subagent counter/result contract. These are the rules every terminal handler
relies on — if any of them drifts, cards get duplicated or lost.
"""

import pytest

from app.agents.core.background import session as sess
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    append_bg_subagent_result,
    create_session,
    decrement_pending_subagents,
    drain_bg_subagent_results,
    get_or_create_session,
    get_pending_subagents,
    get_session,
    increment_pending_subagents,
    mark_executor_spawned,
    signal_executor_done,
    teardown_session,
    was_executor_spawned,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Sessions are module-global; isolate every test."""
    sess._sessions.clear()
    yield
    sess._sessions.clear()


@pytest.mark.unit
class TestSessionRegistry:
    def test_create_then_get_returns_same_session(self) -> None:
        created = create_session("s1", RunKind.LIVE)
        assert get_session("s1") is created
        assert created.kind is RunKind.LIVE
        assert created.executor_spawned is False

    def test_create_overwrites_existing_session(self) -> None:
        # register_executor_capture semantics: a new turn on the same stream id
        # starts from a clean slate (fresh done-event, empty collector).
        first = create_session("s1", RunKind.LIVE)
        first.tool_events.append({"tool_data": {"x": 1}})
        second = create_session("s1", RunKind.LIVE)
        assert get_session("s1") is second
        assert second.tool_events == []

    def test_teardown_leaves_no_residue(self) -> None:
        create_session("s1", RunKind.QUEUED)
        mark_executor_spawned("s1")
        increment_pending_subagents("s1")
        append_bg_subagent_result("s1", "agent", "result")

        teardown_session("s1")

        assert get_session("s1") is None
        assert was_executor_spawned("s1") is False
        assert get_pending_subagents("s1") == 0
        assert drain_bg_subagent_results("s1") == []

    def test_teardown_is_idempotent(self) -> None:
        create_session("s1", RunKind.LIVE)
        teardown_session("s1")
        teardown_session("s1")  # must not raise
        assert get_session("s1") is None

    def test_get_or_create_auto_vivifies_missing_session(self) -> None:
        # Parity with the old dicts' setdefault behavior: touching state for an
        # unregistered stream must work (and not crash callers like handoff).
        session = get_or_create_session("ghost")
        assert get_session("ghost") is session
        assert session.kind is RunKind.LIVE


@pytest.mark.unit
class TestExecutorLifecycleFlags:
    def test_spawned_flag_lifecycle(self) -> None:
        create_session("s1", RunKind.LIVE)
        assert was_executor_spawned("s1") is False
        mark_executor_spawned("s1")
        assert was_executor_spawned("s1") is True

    def test_signal_executor_done_sets_event(self) -> None:
        session = create_session("s1", RunKind.LIVE)
        assert not session.done_event.is_set()
        signal_executor_done("s1")
        assert session.done_event.is_set()

    def test_signal_without_session_is_safe(self) -> None:
        signal_executor_done("missing")  # must not raise


@pytest.mark.unit
class TestOwnershipRule:
    """The single source of truth that prevents duplicate/lost tool cards.

    Live runs: the comms path attaches executor tool_data — the executor must
    NOT self-persist. Queued and workflow runs have no comms consumer, so the
    executor self-persists. Exactly one owner per stream.
    """

    @pytest.mark.parametrize(
        ("kind", "workflow_id", "owns"),
        [
            (RunKind.LIVE, None, False),
            (RunKind.QUEUED, None, True),
            (RunKind.LIVE, "wf-1", True),
            (RunKind.QUEUED, "wf-1", True),
        ],
    )
    def test_executor_owns_tool_data_truth_table(self, kind, workflow_id, owns) -> None:
        run = ExecutorRun(
            stream_id="s1",
            conversation_id="conv-1",
            user={"user_id": "u1"},
            kind=kind,
            task_id="t1",
            user_message_id=None,
            workflow_id=workflow_id,
        )
        assert run.executor_owns_tool_data is owns

    def test_is_queued_reflects_kind_not_stream_id(self) -> None:
        # The id prefix is cosmetic; behavior must key on RunKind only.
        run = ExecutorRun(
            stream_id="queued_looking_but_live",
            conversation_id="c",
            user={},
            kind=RunKind.LIVE,
            task_id=None,
            user_message_id=None,
        )
        assert run.is_queued is False

    def test_from_configurable_extracts_user_and_workflow_context(self) -> None:
        run = ExecutorRun.from_configurable(
            {
                "user_id": "u1",
                "email": "u1@x.com",
                "user_name": "Uno",
                "workflow_id": "wf-9",
                "workflow_title": "Daily digest",
                "workflow_notify_on_completion": False,
            },
            stream_id="s1",
            conversation_id="conv-1",
            kind=RunKind.QUEUED,
            task_id="t1",
            user_message_id="m1",
        )
        assert run.user == {"user_id": "u1", "email": "u1@x.com", "name": "Uno", "timezone": None}
        assert run.workflow_id == "wf-9"
        assert run.workflow_title == "Daily digest"
        assert run.workflow_notify_on_completion is False

    def test_from_configurable_defaults(self) -> None:
        run = ExecutorRun.from_configurable(
            {},
            stream_id="s1",
            conversation_id="conv-1",
            kind=RunKind.LIVE,
            task_id=None,
            user_message_id=None,
        )
        assert run.workflow_id is None
        assert run.workflow_notify_on_completion is True
        assert run.executor_owns_tool_data is False


@pytest.mark.unit
class TestSubagentCoordination:
    def test_counter_increments_and_decrements(self) -> None:
        create_session("s1", RunKind.LIVE)
        assert increment_pending_subagents("s1") == 1
        assert increment_pending_subagents("s1") == 2
        assert decrement_pending_subagents("s1") == 1
        assert get_pending_subagents("s1") == 1

    def test_counter_floors_at_zero(self) -> None:
        create_session("s1", RunKind.LIVE)
        assert decrement_pending_subagents("s1") == 0
        assert get_pending_subagents("s1") == 0

    def test_counter_for_missing_session_is_zero(self) -> None:
        assert get_pending_subagents("missing") == 0
        assert decrement_pending_subagents("missing") == 0

    def test_results_drain_returns_and_clears(self) -> None:
        create_session("s1", RunKind.LIVE)
        append_bg_subagent_result("s1", "researcher", "found it")
        append_bg_subagent_result("s1", "writer", "wrote it")

        results = drain_bg_subagent_results("s1")

        assert results == [
            {"agent": "researcher", "message": "found it"},
            {"agent": "writer", "message": "wrote it"},
        ]
        assert drain_bg_subagent_results("s1") == []  # drained

    def test_results_for_missing_session_empty(self) -> None:
        assert drain_bg_subagent_results("missing") == []
