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
    RunIdentity,
    RunKind,
    claim_tool_output,
    create_session,
    get_or_create_session,
    get_session,
    mark_executor_spawned,
    note_tool_output_owner,
    run_user_from_configurable,
    signal_executor_done,
    teardown_session,
)
from app.models.user_models import AuthenticatedUser


@pytest.fixture(autouse=True)
def _clean_registry():
    """Sessions are module-global; isolate every test."""
    sess._sessions.clear()
    yield
    sess._sessions.clear()


class TestSessionRegistry:
    def test_create_then_get_returns_same_session(self) -> None:
        created = create_session("s1", RunKind.LIVE)
        assert get_session("s1") is created
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

        teardown_session("s1")

        assert get_session("s1") is None

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


class TestExecutorLifecycleFlags:
    def test_spawned_flag_lifecycle(self) -> None:
        session = create_session("s1", RunKind.LIVE)
        assert session.executor_spawned is False
        mark_executor_spawned("s1")
        assert session.executor_spawned is True

    def test_signal_executor_done_sets_event(self) -> None:
        session = create_session("s1", RunKind.LIVE)
        assert not session.done_event.is_set()
        signal_executor_done("s1")
        assert session.done_event.is_set()

    def test_signal_without_session_is_safe(self) -> None:
        signal_executor_done("missing")  # must not raise


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
            identity=RunIdentity(
                stream_id="s1",
                conversation_id="conv-1",
                kind=RunKind.QUEUED,
                task_id="t1",
                user_message_id="m1",
            ),
        )
        assert run.user == AuthenticatedUser(user_id="u1", email="u1@x.com", name="Uno")
        assert run.workflow_id == "wf-9"
        assert run.workflow_title == "Daily digest"
        assert run.workflow_notify_on_completion is False

    def test_from_configurable_defaults(self) -> None:
        run = ExecutorRun.from_configurable(
            {},
            identity=RunIdentity(
                stream_id="s1",
                conversation_id="conv-1",
                kind=RunKind.LIVE,
                task_id=None,
                user_message_id=None,
            ),
        )
        assert run.workflow_id is None
        assert run.workflow_notify_on_completion is True
        assert run.executor_owns_tool_data is False


class TestToolOutputOwnership:
    """Who may stream a tool result, when both drivers see the same ToolMessage.

    A subagent handed off to from an executor tool is a nested run, and "messages"
    mode replays its chunks into the outer run's stream. Only the subagent's copy
    carries a subagent_id, so if the outer driver wins the card renders outside the
    subagent's row. Ownership — recorded when the call is announced, before any
    result exists — is what decides it; arrival order must not.
    """

    def test_the_announcing_run_wins_however_late_it_looks(self) -> None:
        create_session("s1", RunKind.LIVE)
        note_tool_output_owner("s1", "tc_fetch", "row-1")

        # The outer driver (no subagent_id) sees the echo FIRST and must lose.
        assert claim_tool_output("s1", "tc_fetch", None) is False
        assert claim_tool_output("s1", "tc_fetch", "row-1") is True

    def test_the_owner_still_streams_only_once(self) -> None:
        create_session("s1", RunKind.LIVE)
        note_tool_output_owner("s1", "tc_fetch", "row-1")

        assert claim_tool_output("s1", "tc_fetch", "row-1") is True
        assert claim_tool_output("s1", "tc_fetch", "row-1") is False

    def test_an_executors_own_call_is_owned_by_the_untagged_run(self) -> None:
        create_session("s1", RunKind.LIVE)
        note_tool_output_owner("s1", "tc_exec", None)

        assert claim_tool_output("s1", "tc_exec", "row-1") is False
        assert claim_tool_output("s1", "tc_exec", None) is True

    def test_an_unannounced_call_fails_open(self) -> None:
        # A HIL resume announced its call in the run before the pause, so nothing
        # owns it here. Suppressing would drop the only copy.
        create_session("s1", RunKind.LIVE)
        assert claim_tool_output("s1", "tc_resumed", "row-1") is True
        assert claim_tool_output("s1", "tc_resumed", "row-1") is False

    def test_ownership_for_missing_session_is_safe(self) -> None:
        note_tool_output_owner("missing", "tc_fetch", "row-1")  # must not raise
        assert claim_tool_output("missing", "tc_fetch", None) is True


@pytest.mark.regression
class TestExecutorRunCarriesWorkflowExecution:
    """The execution id lives only on the workflow task's wide event, never in configurable; the run built inside that boundary has to pick it up or every executor call it makes is unattributable to the run in the ledger."""

    async def test_from_configurable_reads_the_execution_id_off_the_boundary(self) -> None:
        from shared.py.wide_events import WorkflowContext, log, wide_task

        async with wide_task("workflow_execution"):
            log.set(workflow=WorkflowContext(id="wf-9", execution_id="exec-42"))
            run = ExecutorRun.from_configurable(
                {"workflow_id": "wf-9"},
                identity=RunIdentity(
                    stream_id="s1",
                    conversation_id="conv-1",
                    kind=RunKind.LIVE,
                    task_id=None,
                    user_message_id=None,
                ),
            )

        assert run.workflow_execution_id == "exec-42"

    def test_no_boundary_means_no_execution_id(self) -> None:
        run = ExecutorRun.from_configurable(
            {},
            identity=RunIdentity(
                stream_id="s1",
                conversation_id="conv-1",
                kind=RunKind.LIVE,
                task_id=None,
                user_message_id=None,
            ),
        )

        assert run.workflow_execution_id is None


class TestRunUserFromConfigurable:
    """A detached run acts for the user its configurable names, rebuilt field by field."""

    def test_every_carried_field_is_the_users_own(self) -> None:
        user = run_user_from_configurable(
            {
                "user_id": "u1",
                "email": "u1@x.com",
                "user_name": "Uno",
                "user_timezone": "Asia/Kolkata",
            }
        )

        assert user == AuthenticatedUser(
            user_id="u1", email="u1@x.com", name="Uno", timezone="Asia/Kolkata"
        )

    def test_absent_identity_keys_rebuild_as_empty(self) -> None:
        user = run_user_from_configurable({"conversation_id": "c1"})

        assert (user.user_id, user.email, user.name, user.timezone) == ("", "", "", None)

    def test_an_identity_carried_as_none_stays_none(self) -> None:
        user = run_user_from_configurable({"user_id": None, "email": None, "user_name": None})

        assert (user.user_id, user.email, user.name) == ("", None, None)
