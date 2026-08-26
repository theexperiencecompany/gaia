"""Dropping a workflow conversation's checkpoint threads before it runs.

Two ways this goes wrong and nobody notices: it deletes a thread that is not
this conversation's (a different conversation, a spawn the nightly sweep owns,
an id that merely contains this one), or it deletes a thread whose run is still
in flight. Both are silent in production, so they are pinned here.
"""

from types import TracebackType
from unittest.mock import AsyncMock, MagicMock, patch

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

    async def execute(self, sql: str, params: tuple[object, ...]) -> None:
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


def _manager(threads: dict[str, bool], checkpointer: MagicMock) -> MagicMock:
    manager = MagicMock()
    manager.pool = _FakePool(_FakeCursor(threads))
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
