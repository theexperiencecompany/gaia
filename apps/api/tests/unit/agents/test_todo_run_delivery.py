"""The outcomes of a tracked todo run's delivery that the wiring test does not reach.

The delivered / silenced / reaction / delivery-off / error paths run end to end in
tests/unit/agents/test_tracked_todo_run_delivery.py; these pin the rest.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import todo_run_delivery as trd
from app.agents.core.background.session import ExecutorRun, RunKind, TodoRun
from app.agents.core.background.todo_run_delivery import deliver_todo_run_result
from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants import todos as todo_constants
from app.constants.log_tags import LogTag
from app.constants.todos import TodoActivityEvent
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import NotificationType
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.tracked_todo_service import CANVAS_TEMPLATE
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

USER = AuthenticatedUser(user_id="user-1")
RUN = ExecutorRun(
    stream_id="s1",
    conversation_id="run-conv",
    user=USER,
    kind=RunKind.LIVE,
    task_id="t1",
    user_message_id=None,
)
SCHEDULED = TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO)


@dataclass
class _Seams:
    narrate: AsyncMock
    send: AsyncMock
    activity: AsyncMock
    capture: MagicMock
    in_app: AsyncMock

    def entry(self) -> str:
        return self.activity.await_args.args[3]

    def props(self) -> dict[str, object]:
        return self.capture.call_args.args[2]


@contextmanager
def _seams(
    *, todo: TodoDocument | None, narrated: str = "Deploy failed.", sent_on: object = None
) -> Iterator[_Seams]:
    seams = _Seams(
        narrate=AsyncMock(return_value=narrated),
        send=AsyncMock(return_value=sent_on),
        activity=AsyncMock(return_value=True),
        capture=MagicMock(),
        in_app=AsyncMock(),
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=todo)
    with (
        patch.object(trd, "narrate_executor_result", seams.narrate),
        patch.object(trd, "deliver_result_to_platforms", seams.send),
        patch.object(trd, "todo_repository", repo),
        patch.object(trd, "record_activity", seams.activity),
        patch.object(trd, "capture_event", seams.capture),
        patch.object(trd.notification_service, "create_notification", seams.in_app),
    ):
        yield seams


def _todo(**fields: object) -> TodoDocument:
    return TodoDocument(
        **{"id": "todo-1", "user_id": "user-1", "title": "Watch the deploy", **fields}
    )


class TestResultsThatReachNobody:
    async def test_a_failed_write_up_sends_nothing_and_is_recorded(self) -> None:
        with _seams(todo=_todo(), narrated="") as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        seams.send.assert_not_awaited()
        assert "result not sent: it could not be written up" in seams.entry()
        assert seams.props()["outcome"] == "narration_failed"

    async def test_with_no_linked_chat_app_the_result_arrives_in_the_app(self) -> None:
        """A web-only user never received a tracked todo's result before."""
        with _seams(todo=_todo(), sent_on=None) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        request = seams.in_app.await_args.args[0]
        assert request.user_id == "user-1"
        assert request.type is NotificationType.INFO
        assert request.content.title == "Watch the deploy"
        assert request.content.body == "Deploy failed."
        assert request.metadata == {"todo_id": "todo-1"}
        assert seams.entry() == "result sent as an in-app notification (summary='report')"
        assert seams.props()["outcome"] == "delivered"
        assert seams.props()["platform"] is None

    async def test_a_result_neither_a_chat_app_nor_the_app_took_is_undelivered(self) -> None:
        """Counting a delivery that reached nobody as sent hides the failure."""
        with _seams(todo=_todo(), sent_on=None) as seams:
            seams.in_app.side_effect = ConnectionError("mongo down")
            async with captured_wide_event() as event:
                await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert seams.props()["outcome"] == "undelivered"
        assert seams.props()["delivered"] is False
        assert event["errors"] == [
            {
                "msg": f"{LogTag.AGENT} todo run result could not be sent in the app",
                "todo_id": "todo-1",
                "error": "mongo down",
                "error_type": "ConnectionError",
            }
        ]

    async def test_a_todo_deleted_mid_run_gets_nothing(self) -> None:
        with _seams(todo=None) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        seams.narrate.assert_not_awaited()
        seams.activity.assert_not_awaited()
        seams.capture.assert_not_called()


class TestAttribution:
    async def test_the_event_names_what_woke_the_run_and_whose_it_is(self) -> None:
        triggered = TodoRun(todo_id="todo-1", trigger_type=TriggerType.TODO_TRIGGER)
        with _seams(todo=_todo(recurrence="daily", user_id="user-9")) as seams:
            await deliver_todo_run_result(RUN, triggered, "report", "final")

        user_id, _event, props = seams.capture.call_args.args
        assert user_id == "user-9"
        assert props["trigger_type"] == TriggerType.TODO_TRIGGER.value
        assert props["recurring"] is True

    async def test_the_activity_entry_lands_on_the_todos_owner(self) -> None:
        with _seams(todo=_todo(user_id="user-9")) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "a\nlong\nreport", "final")

        todo_id, user_id, event, detail = seams.activity.await_args.args
        assert (todo_id, user_id, event) == ("todo-1", "user-9", TodoActivityEvent.RUN_FINISHED)
        assert "(summary='a long report')" in detail


class TestTheWideEventSaysWhatHappened:
    """The executor_run event is where an operator reads why a todo did or did not message."""

    async def test_a_delivered_result_names_its_todo_and_outcome(self) -> None:
        with _seams(todo=_todo(), sent_on=ConversationSource.TELEGRAM):
            async with captured_wide_event() as event:
                await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert event["todo_delivery"] == {
            "todo_id": "todo-1",
            "result_type": "final",
            "outcome": "delivered",
        }

    async def test_a_silenced_result_keeps_the_reason(self) -> None:
        with _seams(todo=_todo(), narrated="<SILENCE>routine check</SILENCE>"):
            async with captured_wide_event() as event:
                await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert event["todo_delivery"]["silence_reason"] == "routine check"
        assert event["todo_delivery"]["outcome"] == "silenced"

    async def test_an_error_result_is_left_to_the_worker(self) -> None:
        with _seams(todo=_todo()) as seams:
            async with captured_wide_event() as event:
                await deliver_todo_run_result(RUN, SCHEDULED, "boom", "error")

        assert event["todo_delivery"] == {"todo_id": "todo-1", "result_type": "error"}
        seams.narrate.assert_not_awaited()
        seams.activity.assert_not_awaited()

    async def test_a_deleted_todo_is_a_warning_naming_it(self) -> None:
        with _seams(todo=None):
            async with captured_wide_event() as event:
                await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        (warning,) = event["warnings"]
        assert warning["msg"] == f"{LogTag.AGENT} todo run finished for a deleted todo"
        assert warning["todo_id"] == "todo-1"

    async def test_a_failed_write_up_is_an_error_naming_the_todo(self) -> None:
        with _seams(todo=_todo(), narrated=""):
            async with captured_wide_event() as event:
                await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        (error,) = event["errors"]
        assert error["msg"] == f"{LogTag.AGENT} todo run result narration failed"
        assert error["todo_id"] == "todo-1"

    async def test_a_reaction_is_an_error_naming_the_emoji(self) -> None:
        with _seams(todo=_todo(), narrated="<EMOJI>👍</EMOJI>"):
            async with captured_wide_event() as event:
                await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        (error,) = event["errors"]
        assert error["msg"] == f"{LogTag.AGENT} todo run result narrated as a reaction; not sent"
        assert (error["todo_id"], error["emoji"]) == ("todo-1", "👍")


class TestTheDecisionSeesTheStandingRules:
    async def test_the_standing_rules_reach_the_write_up_bounded(self) -> None:
        long_rules = (
            "- 2026-09-28: tell me every time.\n" + "x" * todo_constants.STANDING_RULES_MAX_CHARS
        )
        todo = _todo(
            canvas_content=f"## Standing rules\n{long_rules}\n\n## Key Details\n- thread abc\n"
        )
        with _seams(todo=todo) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert seams.narrate.await_args.kwargs["preamble"] == tracked_todo_delivery_note(
            "Watch the deploy",
            long_rules[: todo_constants.STANDING_RULES_MAX_CHARS],
            "- thread abc",
        )

    async def test_key_details_reach_the_write_up_as_details_not_rules(self) -> None:
        todo = _todo(canvas_content="## Standing rules\n\n## Key Details\n- thread abc\n")
        with _seams(todo=todo) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert seams.narrate.await_args.kwargs["preamble"] == tracked_todo_delivery_note(
            "Watch the deploy", None, "- thread abc"
        )

    @pytest.mark.regression
    async def test_a_request_an_older_todo_kept_in_key_details_still_reaches_the_write_up(
        self,
    ) -> None:
        details = "- tell me every time.\n" + "x" * todo_constants.DELIVERY_KEY_DETAILS_MAX_CHARS
        todo = _todo(canvas_content=f"## Key Details\n{details}\n\n## Current State\n- ok\n")
        with _seams(todo=todo) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert seams.narrate.await_args.kwargs["preamble"] == tracked_todo_delivery_note(
            "Watch the deploy", None, details[: todo_constants.DELIVERY_KEY_DETAILS_MAX_CHARS]
        )

    @pytest.mark.regression
    async def test_a_new_todo_template_carries_no_rules(self) -> None:
        todo = _todo(canvas_content=CANVAS_TEMPLATE.format(title="Watch the deploy"))
        with _seams(todo=todo) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert seams.narrate.await_args.kwargs["preamble"] == tracked_todo_delivery_note(
            "Watch the deploy", None, None
        )

    @pytest.mark.regression
    async def test_a_title_cased_heading_still_reaches_the_write_up(self) -> None:
        todo = _todo(canvas_content="## Standing Rules\n- 2026-09-28: tell me every time.\n")
        with _seams(todo=todo) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert seams.narrate.await_args.kwargs["preamble"] == tracked_todo_delivery_note(
            "Watch the deploy", "- 2026-09-28: tell me every time.", None
        )

    async def test_a_todo_without_standing_rules_gets_the_defaults_alone(self) -> None:
        with _seams(todo=_todo(canvas_content="## Current State\n- ok\n")) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert seams.narrate.await_args.kwargs["preamble"] == tracked_todo_delivery_note(
            "Watch the deploy", None, None
        )

    async def test_a_todo_with_no_canvas_gets_the_defaults_alone(self) -> None:
        with _seams(todo=_todo(canvas_content=None)) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        assert seams.narrate.await_args.kwargs["preamble"] == tracked_todo_delivery_note(
            "Watch the deploy", None, None
        )
