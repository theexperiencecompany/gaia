"""The task tools comms works through when it has no direct executor."""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.task_tools import (
    NO_SUCH_TASK,
    cancel_task,
    find_tasks,
    message_task,
    start_task,
)
from app.constants.tasks import HIDDEN_TASK_LABEL, TASK_START_DELAY
from app.constants.todos import TodoActivityEvent, WaitingOn
from app.models.executor_activity_models import ExecutorActivity
from app.models.todo_models import AskOrigin, TodoDocument, TodoUpdate
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import (
    TaskCancelled,
    TaskFound,
    TaskMessaged,
    TaskStarted,
)

pytestmark = pytest.mark.unit

MODULE = "app.agents.tools.task_tools"
USER = "6812f0b3c9a14e2b7d5a91cc"
TASK = "6812f0b3c9a14e2b7d5a91dd"
CHAT = "the-users-whatsapp-chat"
TASK_CHAT = "the-tasks-own-chat"
CONFIG = {
    "configurable": {
        "thread_id": CHAT,
        "user_id": USER,
        "stream_id": "s1",
        "user_request": "find me flights to Lisbon",
        "bot_message_id": "bot-msg-1",
        "user_timezone": "+05:30",
    },
    "metadata": {"user_id": USER},
}
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)

START_ARGS = {
    "title": "Lisbon flights",
    "request": "Find the cheapest flights to Lisbon next month.",
    "acceptance_criteria": ["three options are listed with prices"],
    "desired_outcome": "books the cheapest sensible flight",
    "time_horizon": "one_shot",
}


def _task(**fields: object) -> TodoDocument:
    return TodoDocument(
        id=TASK, user_id=USER, title="Lisbon flights", source_conversation_id=CHAT, **fields
    )


@pytest.fixture
def captured() -> MagicMock:
    with patch(f"{MODULE}.capture") as capture:
        yield capture


@pytest.fixture
def todos():
    with (
        patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_task())) as get,
        patch(f"{MODULE}.todo_repository.update", AsyncMock()) as update,
        patch(f"{MODULE}.todo_repository.find_by_ids", AsyncMock(return_value=[])),
        patch(
            f"{MODULE}.todo_repository.list_active_tracked",
            AsyncMock(return_value=[_task(), _task()]),
        ),
    ):
        yield SimpleNamespace(get=get, update=update)


@pytest.fixture
def service():
    with (
        patch(
            f"{MODULE}.tracked_todo_service.create_tracked_todo",
            AsyncMock(return_value=SimpleNamespace(todo=SimpleNamespace(id=TASK))),
        ) as create,
        patch(f"{MODULE}.tracked_todo_service.schedule_execution", AsyncMock()) as schedule,
        patch(f"{MODULE}.tracked_todo_service.complete_tracked_todo", AsyncMock()) as complete,
    ):
        yield SimpleNamespace(create=create, schedule=schedule, complete=complete)


@pytest.fixture
def run_state():
    """Hold what the task's own chat is doing; set .activity before the call."""
    state = SimpleNamespace(activity=ExecutorActivity.IDLE)
    with (
        patch(f"{MODULE}.get_or_create_todo_conversation", AsyncMock(return_value=TASK_CHAT)),
        patch(
            f"{MODULE}.read_executor_activity",
            AsyncMock(side_effect=lambda _chat: SimpleNamespace(activity=state.activity)),
        ),
    ):
        yield state


class TestStartTask:
    @pytest.fixture(autouse=True)
    def _comms_turn(self, in_process_redis, captured, todos, service):
        with patch(f"{MODULE}.mark_task_handed_off") as handed_off:
            self.handed_off = handed_off
            self.captured = captured
            self.service = service
            yield

    async def test_a_request_becomes_a_hidden_task_armed_to_run_now(self) -> None:
        result = await start_task.ainvoke(START_ARGS, config=CONFIG)

        create = self.service.create.await_args.kwargs
        assert create["user_id"] == USER
        assert create["labels"] == [HIDDEN_TASK_LABEL]
        assert create["done_when"] == ["three options are listed with prices"]
        assert create["source_conversation_id"] == CHAT
        assert create["schedule"].waiting_on is WaitingOn.TIME
        assert "Find the cheapest flights to Lisbon next month." in create["initial_canvas"]
        assert "find me flights to Lisbon" in create["initial_canvas"]
        scheduled_for = self.service.schedule.await_args.args[1]
        assert create["schedule"].scheduled_at == scheduled_for
        assert self.service.schedule.await_args.args[0] == TASK
        assert self.service.schedule.await_args.kwargs["defer_until"] <= datetime.now(UTC)
        assert TASK in result

    async def test_the_task_remembers_the_turn_that_asked_for_it_in_the_users_words(self) -> None:
        await start_task.ainvoke(START_ARGS, config=CONFIG)

        assert self.service.create.await_args.kwargs["ask_origin"] == AskOrigin(
            conversation_id=CHAT, message_id="bot-msg-1", user_request="find me flights to Lisbon"
        )

    async def test_a_start_time_with_no_offset_is_the_users_own_clock(self) -> None:
        tomorrow_nine = (datetime.now(UTC) + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0, tzinfo=None
        )

        await start_task.ainvoke({**START_ARGS, "start_at": tomorrow_nine}, config=CONFIG)

        expected = tomorrow_nine.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        assert self.service.schedule.await_args.args[1] == expected
        assert self.service.schedule.await_args.args[1].utcoffset() == timedelta(
            hours=5, minutes=30
        )

    async def test_a_visible_task_carries_no_hidden_label(self) -> None:
        await start_task.ainvoke({**START_ARGS, "visible": True}, config=CONFIG)

        assert self.service.create.await_args.kwargs["labels"] is None

    async def test_a_task_for_later_waits_for_its_time(self) -> None:
        later = datetime.now(UTC) + timedelta(days=1)

        await start_task.ainvoke({**START_ARGS, "start_at": later}, config=CONFIG)

        assert self.service.schedule.await_args.args[1] == later
        assert self.service.schedule.await_args.kwargs["defer_until"] == later
        assert self.captured.call_args.args[1].timing == "scheduled"

    async def test_a_start_time_in_the_past_creates_nothing(self) -> None:
        past = datetime.now(UTC) - timedelta(minutes=5)

        result = await start_task.ainvoke({**START_ARGS, "start_at": past}, config=CONFIG)

        assert "in the past" in result
        self.service.create.assert_not_awaited()
        self.service.schedule.assert_not_awaited()

    async def test_the_turn_reads_as_a_hand_off_and_the_start_is_measured(self) -> None:
        await start_task.ainvoke(START_ARGS, config=CONFIG)

        self.handed_off.assert_called_once_with("s1")
        user, event = self.captured.call_args.args
        assert user == UserId(USER)
        assert event == TaskStarted(timing="now", visible=False, open_tasks=2)

    async def test_the_run_is_armed_one_beat_ahead_so_the_open_todo_has_a_next_check(self) -> None:
        before = datetime.now(UTC)

        await start_task.ainvoke(START_ARGS, config=CONFIG)

        fire = self.service.create.await_args.kwargs["schedule"].scheduled_at
        assert before + TASK_START_DELAY <= fire <= datetime.now(UTC) + TASK_START_DELAY


class TestMessageTask:
    @pytest.fixture(autouse=True)
    def _tools(self, captured, todos, service, run_state):
        self.captured = captured
        self.todos = todos
        self.service = service
        self.run_state = run_state

    async def test_a_running_task_takes_the_message_into_the_run_in_flight(self) -> None:
        self.run_state.activity = ExecutorActivity.RUNNING
        with patch(f"{MODULE}.ExecutorInbox") as inbox_class:
            inbox_class.return_value.append = AsyncMock()
            result = await message_task.ainvoke({"task_id": TASK, "text": "also cc Jonah"}, CONFIG)

        inbox_class.assert_called_once_with(TASK_CHAT)
        assert inbox_class.return_value.append.await_args.args[1] == "also cc Jonah"
        self.service.schedule.assert_not_awaited()
        assert "in progress" in result
        assert self.captured.call_args.args[1] == TaskMessaged(
            running=True, cross_conversation=False
        )

    async def test_a_finished_task_runs_again_with_the_message(self) -> None:
        self.todos.get.return_value = _task(completed=True)
        with (
            patch(f"{MODULE}.record_activity", AsyncMock()) as record,
            patch(f"{MODULE}.TodoService.update_todo", AsyncMock()) as reopen,
        ):
            await message_task.ainvoke({"task_id": TASK, "text": "make it Friday"}, CONFIG)

        assert record.await_args.args[2:] == (TodoActivityEvent.USER_MESSAGE, "make it Friday")
        assert reopen.await_args.args[1].completed is False
        update: TodoUpdate = self.todos.update.await_args.kwargs["update"]
        assert update.waiting_on is WaitingOn.TIME
        assert self.service.schedule.await_args.args[0] == TASK
        assert self.captured.call_args.args[1] == TaskMessaged(
            running=False, cross_conversation=False
        )

    async def test_an_open_task_that_is_idle_is_not_reopened(self) -> None:
        with (
            patch(f"{MODULE}.record_activity", AsyncMock()),
            patch(f"{MODULE}.TodoService.update_todo", AsyncMock()) as reopen,
        ):
            await message_task.ainvoke({"task_id": TASK, "text": "check again"}, CONFIG)

        reopen.assert_not_awaited()
        self.service.schedule.assert_awaited_once()

    async def test_the_message_makes_this_turn_the_one_the_answer_comes_back_to(self) -> None:
        with (
            patch(f"{MODULE}.record_activity", AsyncMock()),
            patch(f"{MODULE}.TodoService.update_todo", AsyncMock()),
        ):
            await message_task.ainvoke({"task_id": TASK, "text": "check again"}, CONFIG)

        origins = [
            call.kwargs["update"].ask_origin
            for call in self.todos.update.await_args_list
            if call.kwargs["update"].ask_origin is not None
        ]
        assert origins == [
            AskOrigin(
                conversation_id=CHAT,
                message_id="bot-msg-1",
                user_request="find me flights to Lisbon",
            )
        ]

    async def test_a_message_into_a_running_task_also_moves_where_its_answer_goes(self) -> None:
        self.run_state.activity = ExecutorActivity.RUNNING
        with patch(f"{MODULE}.ExecutorInbox") as inbox_class:
            inbox_class.return_value.append = AsyncMock()
            await message_task.ainvoke({"task_id": TASK, "text": "also cc Jonah"}, CONFIG)

        assert self.todos.update.await_args.kwargs["update"].ask_origin.message_id == "bot-msg-1"

    async def test_a_task_in_another_chat_is_steered_and_measured_as_such(self) -> None:
        self.todos.get.return_value = _task().model_copy(
            update={"source_conversation_id": "telegram-chat"}
        )
        with (
            patch(f"{MODULE}.record_activity", AsyncMock()),
            patch(f"{MODULE}.TodoService.update_todo", AsyncMock()),
        ):
            await message_task.ainvoke({"task_id": TASK, "text": "still on?"}, CONFIG)

        assert self.captured.call_args.args[1].cross_conversation is True

    async def test_a_task_that_is_not_the_users_is_refused(self) -> None:
        self.todos.get.return_value = None

        result = await message_task.ainvoke({"task_id": "nope", "text": "x"}, CONFIG)

        assert result == NO_SUCH_TASK
        self.service.schedule.assert_not_awaited()


class TestCancelTask:
    @pytest.fixture(autouse=True)
    def _tools(self, captured, todos, service, run_state):
        self.captured = captured
        self.todos = todos
        self.service = service
        self.run_state = run_state

    async def test_a_running_task_is_cancelled_in_its_own_chat_and_closed(self) -> None:
        self.run_state.activity = ExecutorActivity.RUNNING
        with patch(f"{MODULE}.stop_executor_work", AsyncMock()) as stop:
            result = await cancel_task.ainvoke({"task_id": TASK}, CONFIG)

        assert stop.await_args.args[1:] == (TASK_CHAT, [], None)
        self.service.complete.assert_awaited_once_with(TASK, USER, "Stopped by the user.")
        assert result == "Stopped."
        assert self.captured.call_args.args[1] == TaskCancelled(was_running=True)

    async def test_an_open_idle_task_is_closed_and_its_browser_job_still_stopped(self) -> None:
        with patch(f"{MODULE}.stop_executor_work", AsyncMock()) as stop:
            result = await cancel_task.ainvoke({"task_id": TASK}, CONFIG)

        assert stop.await_args.args[1:] == (TASK_CHAT, [], None)
        self.service.complete.assert_awaited_once()
        assert "will not run" in result

    async def test_a_finished_task_has_nothing_to_stop(self) -> None:
        self.todos.get.return_value = _task(completed=True)

        result = await cancel_task.ainvoke({"task_id": TASK}, CONFIG)

        assert "already finished" in result
        self.service.complete.assert_not_awaited()


class TestFindTasks:
    async def test_it_searches_every_conversation_and_measures_the_matches_from_elsewhere(
        self, captured: MagicMock
    ) -> None:
        matches = [
            {
                "todo_id": TASK,
                "title": "Lisbon flights",
                "score": 0.9,
                "snippet": "s",
                "completed": False,
            },
            {"todo_id": "other", "title": "Rent", "score": 0.8, "snippet": "s", "completed": True},
        ]
        owned = [
            _task(),
            _task().model_copy(update={"id": "other", "source_conversation_id": "tg"}),
        ]
        with (
            patch(f"{MODULE}.search_canvas_context", AsyncMock(return_value=matches)) as search,
            patch(f"{MODULE}.todo_repository.find_by_ids", AsyncMock(return_value=owned)),
        ):
            text = await find_tasks.ainvoke({"query": "lisbon"}, CONFIG)

        assert search.await_args.kwargs["user_id"] == USER
        assert search.await_args.kwargs["include_completed"] is True
        assert f"todo_id: {TASK}" in text
        assert "todo_id: other" in text
        assert captured.call_args.args[1] == TaskFound(results=2, cross_conversation=1)

    async def test_no_match_says_so(self, captured: MagicMock) -> None:
        with (
            patch(f"{MODULE}.search_canvas_context", AsyncMock(return_value=[])),
            patch(f"{MODULE}.todo_repository.find_by_ids", AsyncMock(return_value=[])),
        ):
            assert await find_tasks.ainvoke({"query": "x"}, CONFIG) == "No task matches that."
