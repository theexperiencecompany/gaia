"""Dropping a workflow conversation's checkpoint threads before it runs.

Two ways this goes wrong and nobody notices: it deletes a thread that is not
this conversation's (a different conversation, a spawn the nightly sweep owns,
an id that merely contains this one), or it deletes a thread whose run is still
in flight. Both are silent in production, so they are pinned here.
"""

from types import TracebackType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow.thread_reset import reset_workflow_threads

MODULE = "app.services.workflow.thread_reset"

CONV = "0d0dfd3d-8c0b-4a0b-9f7a-6a1b2c3d4e5f"
OTHER_CONV = "9a9a9a9a-1111-2222-3333-444444444444"


class _FakeCursor:
    """Evaluates the module's two queries against an in-memory thread table.

    ``threads`` maps thread_id -> whether a write is parked on its head
    checkpoint (an in-flight or interrupted run).
    """

    def __init__(self, threads: dict[str, bool]) -> None:
        self.threads = threads
        self._rows: list[tuple[str]] = []
        #: Every statement as it was sent, in order.
        self.statements: list[str] = []

    async def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.statements.append(sql)
        if "FROM checkpoint_writes" in sql:
            (candidates,) = params
            assert isinstance(candidates, list)
            self._rows = [(tid,) for tid in candidates if self.threads[tid]]
            return
        conversation_id, executor_thread, suffix_len, suffix = params
        # Postgres right(x, n) is x[-n:] for n > 0.
        self._rows = [
            (tid,)
            for tid in self.threads
            if tid in (conversation_id, executor_thread) or tid[-int(str(suffix_len)) :] == suffix
        ]

    async def fetchall(self) -> list[tuple[str]]:
        return self._rows

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    async def __aenter__(self) -> "_FakeConnection":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class _FakePool:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._conn = _FakeConnection(cursor)

    def connection(self) -> _FakeConnection:
        return self._conn


def _manager(
    threads: dict[str, bool], checkpointer: MagicMock, cursor: _FakeCursor | None = None
) -> MagicMock:
    manager = MagicMock()
    manager.pool = _FakePool(cursor or _FakeCursor(threads))
    manager.get_checkpointer.return_value = checkpointer
    return manager


def _checkpointer() -> MagicMock:
    checkpointer = MagicMock()
    checkpointer.adelete_thread = AsyncMock()
    return checkpointer


def _deleted(checkpointer: MagicMock) -> set[str]:
    return {call.args[0] for call in checkpointer.adelete_thread.await_args_list}


class TestThreadDerivation:
    async def test_it_deletes_only_the_threads_this_conversation_owns(self) -> None:
        checkpointer = _checkpointer()
        threads = {
            CONV: False,
            f"executor_{CONV}": False,
            f"gmail_executor_{CONV}": False,
            f"notion_executor_{CONV}": False,
            # Not ours: another conversation, a spawn the nightly sweep owns, and
            # an id that merely contains ours somewhere in the middle.
            OTHER_CONV: False,
            f"executor_{OTHER_CONV}": False,
            f"spawn_{CONV}_a1b2": False,
            f"executor_{CONV}_suffixed": False,
        }

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager(threads, checkpointer)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            deleted_count = await reset_workflow_threads(CONV)

        assert _deleted(checkpointer) == {
            CONV,
            f"executor_{CONV}",
            f"gmail_executor_{CONV}",
            f"notion_executor_{CONV}",
        }
        assert deleted_count == 4

    async def test_it_leaves_a_thread_whose_run_is_still_in_flight(self) -> None:
        checkpointer = _checkpointer()
        threads = {CONV: False, f"executor_{CONV}": True}

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager(threads, checkpointer)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            deleted_count = await reset_workflow_threads(CONV)

        assert _deleted(checkpointer) == {CONV}
        assert deleted_count == 1


class TestGuards:
    async def test_it_touches_nothing_for_a_normal_chat_conversation(self) -> None:
        checkpointer = _checkpointer()
        threads = {CONV: False, f"executor_{CONV}": False}
        get_manager = AsyncMock(return_value=_manager(threads, checkpointer))

        with (
            patch(f"{MODULE}.get_checkpointer_manager", get_manager),
            patch(f"{MODULE}.conversation_repository") as conversations,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=False)
            deleted_count = await reset_workflow_threads(CONV)

        assert deleted_count == 0
        checkpointer.adelete_thread.assert_not_awaited()
        get_manager.assert_not_awaited()

    async def test_a_checkpointer_failure_degrades_the_run_instead_of_failing_it(self) -> None:
        checkpointer = _checkpointer()
        checkpointer.adelete_thread = AsyncMock(side_effect=RuntimeError("postgres is down"))
        threads = {CONV: False}

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager(threads, checkpointer)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
            patch(f"{MODULE}.log") as log,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            deleted_count = await reset_workflow_threads(CONV)

        assert deleted_count == 0
        assert log.warning.call_count == 1
        assert log.warning.call_args.kwargs["error_type"] == "RuntimeError"
        assert log.warning.call_args.kwargs["conversation_id"] == CONV

    async def test_it_gives_up_quietly_when_there_is_no_checkpointer_pool(self) -> None:
        """No Postgres means nothing to reset; the run must still go ahead."""
        checkpointer = _checkpointer()
        manager = _manager({CONV: False}, checkpointer)
        manager.pool = None

        with (
            patch(f"{MODULE}.get_checkpointer_manager", AsyncMock(return_value=manager)),
            patch(f"{MODULE}.conversation_repository") as conversations,
            patch(f"{MODULE}.log") as log,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            deleted_count = await reset_workflow_threads(CONV)

        assert deleted_count == 0
        checkpointer.adelete_thread.assert_not_awaited()
        assert "no checkpointer pool" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs["conversation_id"] == CONV

    async def test_a_workflow_with_no_threads_yet_deletes_nothing(self) -> None:
        """First run of a workflow: nothing to reset, and no in-flight query either."""
        checkpointer = _checkpointer()

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager({}, checkpointer)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            deleted_count = await reset_workflow_threads(CONV)

        assert deleted_count == 0
        checkpointer.adelete_thread.assert_not_awaited()

    async def test_the_skip_for_a_chat_conversation_says_why(self) -> None:
        with (
            patch(f"{MODULE}.conversation_repository") as conversations,
            patch(f"{MODULE}.log") as log,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=False)
            await reset_workflow_threads(CONV)

        assert "not a workflow conversation" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs["conversation_id"] == CONV


@pytest.mark.unit
class TestResetWideEvent:
    """How much was reset, and how much was left alone, on the run's wide event.

    Without both numbers a reset that quietly stopped resetting anything — the
    exact failure this feature exists to prevent — looks identical in production
    to one with nothing left to do.
    """

    async def test_it_reports_what_it_reset_and_what_it_spared(self) -> None:
        checkpointer = _checkpointer()
        threads = {
            CONV: False,
            f"executor_{CONV}": False,
            f"gmail_executor_{CONV}": True,
        }

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager(threads, checkpointer)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
            patch(f"{MODULE}.log") as log,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            deleted_count = await reset_workflow_threads(CONV)

        assert deleted_count == 2
        log.set_ns.assert_called_once_with("workflow", threads_reset=2, threads_skipped_inflight=1)


class TestTheQueriesItSends:
    """The two statements, exactly as Postgres receives them.

    This function deletes checkpoint rows, so the predicate is the whole safety
    argument: an anchored ``right()`` comparison rather than a LIKE (the ids are
    full of underscores, and an unescaped ``_`` matches any character), and an
    in-flight check anchored to each thread's own head checkpoint. A predicate
    that drifts is silent in production and takes another conversation's history
    with it, so both statements are pinned character for character.
    """

    async def test_the_thread_query_matches_ids_by_anchored_suffix_not_by_pattern(self) -> None:
        checkpointer = _checkpointer()
        cursor = _FakeCursor({CONV: False})

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager({}, checkpointer, cursor)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            await reset_workflow_threads(CONV)

        assert cursor.statements[0] == (
            "SELECT DISTINCT thread_id FROM checkpoints "
            "WHERE thread_id IN (%s, %s) OR right(thread_id, %s) = %s"
        )

    async def test_the_in_flight_query_looks_at_each_threads_own_head_checkpoint(self) -> None:
        checkpointer = _checkpointer()
        cursor = _FakeCursor({CONV: False})

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager({}, checkpointer, cursor)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            await reset_workflow_threads(CONV)

        assert cursor.statements[1] == (
            "SELECT DISTINCT w.thread_id FROM checkpoint_writes w "
            "WHERE w.thread_id = ANY(%s) AND w.checkpoint_id = ("
            "  SELECT max(c.checkpoint_id) FROM checkpoints c"
            "  WHERE c.thread_id = w.thread_id AND c.checkpoint_ns = w.checkpoint_ns"
            ")"
        )

    async def test_it_asks_the_repository_about_the_conversation_it_was_given(self) -> None:
        """The workflow guard is only a guard if it is asked about the right conversation.

        Asked about anything else it answers "not a workflow" for a workflow, or
        worse, "workflow" for a chat, and this function deletes that chat's
        checkpoint threads.
        """
        checkpointer = _checkpointer()
        threads = {CONV: False, f"executor_{CONV}": False}

        async def is_workflow(conversation_id: str) -> bool:
            return conversation_id == CONV

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager(threads, checkpointer)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
        ):
            conversations.is_workflow_execution = AsyncMock(side_effect=is_workflow)
            deleted_count = await reset_workflow_threads(CONV)

        assert deleted_count == 2


class TestTheFailureWarning:
    """What a failed reset leaves behind for whoever reads the run later.

    A reset that fails is deliberately not fatal, so the wide event is the ONLY
    trace that it happened. Without the error itself on the event, a workflow
    quietly replaying its whole history every fire looks exactly like one that
    reset cleanly.
    """

    async def test_it_names_the_failure_and_the_consequence(self) -> None:
        checkpointer = _checkpointer()
        checkpointer.adelete_thread = AsyncMock(side_effect=RuntimeError("postgres is down"))

        with (
            patch(
                f"{MODULE}.get_checkpointer_manager",
                AsyncMock(return_value=_manager({CONV: False}, checkpointer)),
            ),
            patch(f"{MODULE}.conversation_repository") as conversations,
            patch(f"{MODULE}.log") as log,
        ):
            conversations.is_workflow_execution = AsyncMock(return_value=True)
            deleted_count = await reset_workflow_threads(CONV)

        assert deleted_count == 0
        message = log.warning.call_args.args[0]
        assert "Workflow thread reset failed" in message
        assert "run will replay its history" in message
        assert log.warning.call_args.kwargs["error"] == "postgres is down"
