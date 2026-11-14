"""What a finished tracked todo run's write-up sends, and the note its write-up is written under.

The run through the step runs end to end in tests/integration/real/test_conversation_runtime_real.py.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from pymongo.errors import PyMongoError
import pytest

from app.agents.core.background import todo_run_delivery as trd
from app.agents.core.background.todo_run_delivery import (
    FinishedTodoRun,
    finish_todo_run,
    hand_unfinished_run_to_job,
    report_form_of,
    write_up_note,
)
from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants import todos as todo_constants
from app.constants.log_tags import LogTag
from app.models import todo_models
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import TodoRun
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRecord,
    NotificationRequest,
    NotificationStatus,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.delivery.chat_channel import ChatChannel, InApp, ProactiveTarget
from app.services.notification_service import notification_service
from app.services.tracked_todo_service import CANVAS_TEMPLATE
from app.utils import auth_utils
from app.utils.notification.orchestrator import Notified
from app.workers.tasks import tracked_todo_tasks
from shared.py.analytics import UserId
from shared.py.analytics.catalog.todos import TodosRunResultDelivered
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER, ReplyOutcome
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import todo_run as typed_todo_run

pytestmark = pytest.mark.unit

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
OWNER_ID = "6812f0b3c9a14e2b7d5a91cd"
USER = AuthenticatedUser(user_id=USER_ID)
_RUN = typed_todo_run()
SCHEDULED = _RUN.model_copy(
    update={
        "todo_id": "todo-1",
        "title": "Watch the deploy",
        "trigger_type": TriggerType.SCHEDULED_TODO,
        "runs_once": True,
    }
)
WATCHING = SCHEDULED.model_copy(
    update={"trigger_type": TriggerType.TODO_TRIGGER, "runs_once": False}
)


@dataclass
class _Seams:
    todo: TodoDocument | None
    write_up: str
    #: notification_service.notify; send and in_app name the same one call.
    send: AsyncMock
    activity: AsyncMock
    capture: MagicMock
    in_app: AsyncMock
    #: Where the pipeline routed the result.
    target: MagicMock
    read_todo: AsyncMock
    #: The note the run's write-up was written under, as the turn builder reads it.
    note: str = ""

    def entry(self) -> str:
        return self.activity.await_args.args[3]

    def event(self) -> TodosRunResultDelivered:
        return self.capture.call_args.args[1]


@contextmanager
def _seams(
    *, todo: TodoDocument | None, write_up: str = "Deploy failed.", sent_on: object = None
) -> Iterator[_Seams]:
    target = MagicMock(return_value=InApp(reason="no_chat_app"))
    notify = AsyncMock(side_effect=lambda request: _notified(request, sent_on, target()))
    seams = _Seams(
        todo=todo,
        write_up=write_up,
        send=notify,
        activity=AsyncMock(return_value=True),
        capture=MagicMock(),
        in_app=notify,
        target=target,
        read_todo=AsyncMock(return_value=todo),
    )
    repo = MagicMock()
    repo.get_by_id = seams.read_todo
    with (
        patch.object(trd, "todo_repository", repo),
        patch.object(trd, "record_run_finished", seams.activity),
        patch.object(trd, "capture", seams.capture),
        patch.object(notification_service, "notify", seams.in_app),
    ):
        yield seams


def _notified(request: NotificationRequest, sent_on: object, target: ProactiveTarget) -> Notified:
    """Answer as the pipeline does: the inbox always took it, a chat app when sent_on names one."""
    channels = [ChannelDeliveryStatus(channel_type="inapp", status=NotificationStatus.DELIVERED)]
    if isinstance(sent_on, ConversationSource):
        channels.append(
            ChannelDeliveryStatus(channel_type=sent_on.value, status=NotificationStatus.DELIVERED)
        )
    record = NotificationRecord(
        id=request.id,
        user_id=request.user_id,
        status=NotificationStatus.DELIVERED,
        created_at=request.created_at,
        channels=channels,
        original_request=request,
    )
    return Notified(record=record, target=target)


async def deliver(
    seams: _Seams,
    kind: TodoRun,
    report: str,
    *,
    nothing_for_user: bool = False,
    reply: ReplyOutcome = ReplyOutcome.ANSWERED,
) -> None:
    """Write the run up as the step does, under its note, then hand what its reply settled to delivery."""
    form = report_form_of(seams.todo) if seams.todo is not None else kind.report_form
    run = kind.model_copy(update={"report_form": form})
    seams.note = await write_up_note(run)
    finished = FinishedTodoRun(
        run_id="s1",
        todo_id=run.todo_id,
        user_id=USER_ID,
        conversation_id="run-conv",
        trigger_type=run.trigger_type,
        report_form=form,
        result_text=report,
        write_up=seams.write_up if reply is ReplyOutcome.ANSWERED else "",
        reply=reply,
        nothing_for_user=nothing_for_user,
    )
    if (undone := await finish_todo_run(finished)) is not None:
        await hand_unfinished_run_to_job(undone)


def _todo(**fields: object) -> TodoDocument:
    return TodoDocument.model_validate(
        {"id": "todo-1", "user_id": USER_ID, "title": "Watch the deploy", **fields}
    )


def _thread_todo(**fields: object) -> TodoDocument:
    ref = todo_models.ExternalRef(source=todo_models.ExternalRefSource.GMAIL_THREAD, id="t1")
    return _todo(external_ref=ref, **fields)


class TestResultsThatReachNobody:
    async def test_a_failed_write_up_sends_nothing_and_is_recorded(self) -> None:
        with _seams(todo=_todo()) as seams:
            await deliver(seams, SCHEDULED, "report", reply=ReplyOutcome.FAILED)

        seams.send.assert_not_awaited()
        assert "result not sent: it could not be written up" in seams.entry()
        assert seams.event().outcome == "narration_failed"

    async def test_with_no_linked_chat_app_the_result_arrives_in_the_app(self) -> None:
        """A web-only user never received a tracked todo's result before."""
        with _seams(todo=_todo(), sent_on=None) as seams:
            await deliver(seams, SCHEDULED, "report")

        request = seams.in_app.await_args.args[0]
        assert request.user_id == USER_ID
        assert request.type is NotificationType.INFO
        assert request.content.title == "Watch the deploy"
        assert request.content.body == "Deploy failed."
        assert request.metadata == {"todo_id": "todo-1"}
        assert seams.entry() == "result sent as an in-app notification (summary='report')"
        assert seams.event().outcome == "delivered"
        assert seams.event().platform is None

    @pytest.mark.regression
    async def test_an_in_app_result_keeps_its_lines_and_turns_bubble_breaks_into_paragraphs(
        self,
    ) -> None:
        """Regression: the raw break token reached the in-app body, which no client splits on."""
        narrated = (
            f"Here's today's briefing.{NEW_MESSAGE_BREAKER}Needs you\n- Sam: the lease, by Friday"
        )
        with _seams(todo=_todo(), write_up=narrated, sent_on=None) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.in_app.await_args.args[0].content.body == (
            "Here's today's briefing.\n\nNeeds you\n- Sam: the lease, by Friday"
        )

    async def test_a_result_neither_a_chat_app_nor_the_app_took_is_undelivered(self) -> None:
        """Counting a delivery that reached nobody as sent hides the failure."""
        with _seams(todo=_todo(), sent_on=None) as seams:
            seams.in_app.side_effect = None
            seams.in_app.return_value = Notified(
                record=MagicMock(status=NotificationStatus.FAILED, channels=[]),
                target=InApp(reason="no_chat_app"),
            )
            await deliver(seams, SCHEDULED, "report")

        assert seams.event().outcome == "undelivered"
        assert seams.event().delivered is False


class TestABriefingThatOwnsItsForm:
    """The desk's run guidance sets its briefing's form; comms decides only whether it is sent."""

    BRIEFING = "1 need you\n\nNeeds you\n- Priya · pitch deck · by Fri · draft ready"

    def _desk(self) -> TodoDocument:
        return _todo(
            external_ref=todo_models.ExternalRef(
                source=todo_models.ExternalRefSource.INBOX_DESK, id="int-1"
            )
        )

    @pytest.mark.regression
    async def test_a_desk_briefing_reaches_the_app_as_the_desk_wrote_it(self) -> None:
        """Regression: comms retold a sectioned desk briefing as flat lines, its headings gone."""
        with _seams(todo=self._desk(), write_up="Priya: send the deck by Friday.") as seams:
            await deliver(seams, SCHEDULED, self.BRIEFING)

        assert seams.in_app.await_args.args[0].content.body == self.BRIEFING

    async def test_a_desk_briefing_reaches_a_chat_app_as_the_desk_wrote_it(self) -> None:
        with _seams(
            todo=self._desk(),
            write_up="Priya: send the deck by Friday.",
            sent_on=ConversationSource.TELEGRAM,
        ) as seams:
            await deliver(seams, SCHEDULED, self.BRIEFING)

        assert seams.send.await_args.args[0].message == self.BRIEFING

    async def test_its_write_up_can_still_keep_a_desk_briefing_quiet(self) -> None:
        with _seams(todo=self._desk()) as seams:
            await deliver(seams, SCHEDULED, self.BRIEFING, reply=ReplyOutcome.SILENT)

        seams.send.assert_not_awaited()
        seams.in_app.assert_not_awaited()
        assert seams.event().outcome == "silenced"

    @pytest.mark.regression
    async def test_a_thread_todos_alert_reaches_the_user_as_written(self) -> None:
        """Regression: comms retold a thread's one-email alert, dropping its who, what and where."""
        with _seams(todo=_thread_todo()) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.in_app.await_args.args[0].content.body == "report"


class TestARunThatFoundNothingForTheUser:
    """A report-form todo's run declares it; its note is the run's record, never a message."""

    NOTE = "Nothing needs the user now; the next briefing lists this open Stripe thread."

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "source",
        [todo_models.ExternalRefSource.GMAIL_THREAD, todo_models.ExternalRefSource.INBOX_DESK],
    )
    async def test_its_note_is_sent_nowhere_whatever_comms_would_have_said(
        self, source: todo_models.ExternalRefSource
    ) -> None:
        """Regression, seen live: comms answered the note instead of silencing it, and the note was sent."""
        todo = _todo(external_ref=todo_models.ExternalRef(source=source, id="ref-1"))
        with _seams(
            todo=todo, write_up="Nothing new.", sent_on=ConversationSource.TELEGRAM
        ) as seams:
            await deliver(seams, WATCHING, self.NOTE, nothing_for_user=True)
        seams.target.assert_not_called()
        seams.send.assert_not_awaited()
        seams.in_app.assert_not_awaited()
        assert seams.entry() == (
            f"result not sent: the run found nothing for the user (summary={self.NOTE!r})"
        )
        seams.capture.assert_called_once_with(
            UserId(USER_ID),
            TodosRunResultDelivered(
                outcome="nothing_to_report",
                delivered=False,
                trigger_type=TriggerType.TODO_TRIGGER.value,
                recurring=False,
            ),
        )

    async def test_a_run_that_did_not_declare_it_is_still_left_to_comms(self) -> None:
        with _seams(todo=_thread_todo()) as seams:
            await deliver(seams, WATCHING, "Priya · pitch deck")
        assert seams.in_app.await_args.args[0].content.body == "Priya · pitch deck"

    async def test_a_todo_that_sets_no_report_form_is_written_up_whatever_its_run_declared(
        self,
    ) -> None:
        """Only a kind whose guidance defines the declaration may silence itself with it."""
        with _seams(todo=_todo()) as seams:
            await deliver(seams, SCHEDULED, "report", nothing_for_user=True)
        assert seams.in_app.await_args.args[0].content.body == "Deploy failed."
        assert seams.event().outcome == "delivered"

    async def test_with_delivery_off_the_run_is_recorded_as_delivery_off(self) -> None:
        with _seams(todo=_thread_todo(notify_on_run=False)) as seams:
            await deliver(seams, WATCHING, self.NOTE, nothing_for_user=True)

        assert seams.event().outcome == "notify_off"
        assert "result not sent: delivery is off for this todo" in seams.entry()

    async def test_the_wide_event_names_the_outcome(self) -> None:
        with _seams(todo=_thread_todo()) as seams:
            async with captured_wide_event() as event:
                await deliver(seams, WATCHING, self.NOTE, nothing_for_user=True)

        assert event["todo_delivery"] == {
            "todo_id": "todo-1",
            "reply": "answered",
            "outcome": "nothing_to_report",
        }

    async def test_the_durable_job_keeps_the_declaration(self) -> None:
        """A store failure hands the run to a job, which must not then ask comms about the note."""
        with _seams(todo=_thread_todo()) as seams, patch.object(trd, "enqueue_worker_job") as queue:
            seams.activity.side_effect = PyMongoError("primary stepped down")
            with patch.object(trd, "RedisPoolManager", MagicMock(get_pool=AsyncMock())):
                await deliver(seams, WATCHING, self.NOTE, nothing_for_user=True)

        assert queue.await_args.args[2].nothing_for_user is True


class TestAOneTimeTodoAlwaysAnswers:
    """A one-time check the user asked for was silenced when its answer was 'no'."""

    @pytest.mark.regression
    async def test_a_todo_with_no_schedule_or_watch_is_written_up_as_its_answer(self) -> None:
        with _seams(todo=_todo()) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert "This todo runs once" in seams.note

    @pytest.mark.regression
    async def test_a_watching_todo_that_completes_itself_keeps_the_silence_rule(self) -> None:
        """Regression: completing a todo tore its watch down before delivery read it."""
        completed_thread = _todo(
            completed=True,
            external_ref=todo_models.ExternalRef(
                source=todo_models.ExternalRefSource.GMAIL_THREAD, id="t1"
            ),
        )
        watching = SCHEDULED.model_copy(
            update={"trigger_type": TriggerType.TODO_TRIGGER, "runs_once": False}
        )
        with _seams(todo=completed_thread) as seams:
            await deliver(seams, watching, "report")

        preamble = seams.note
        assert "Nobody asked for it just now" in preamble
        assert "This todo runs once" not in preamble


class TestAttribution:
    async def test_the_event_names_what_woke_the_run_and_whose_it_is(self) -> None:
        triggered = SCHEDULED.model_copy(
            update={"trigger_type": TriggerType.TODO_TRIGGER, "runs_once": False}
        )
        with _seams(todo=_todo(recurrence="daily", user_id=OWNER_ID)) as seams:
            await deliver(seams, triggered, "report")

        user_id, event = seams.capture.call_args.args
        assert user_id == UserId(OWNER_ID)
        assert event.trigger_type == TriggerType.TODO_TRIGGER.value
        assert event.recurring is True

    async def test_the_activity_entry_lands_on_the_todos_owner(self) -> None:
        with _seams(todo=_todo(user_id=OWNER_ID)) as seams:
            await deliver(seams, SCHEDULED, "a\nlong\nreport")

        todo_id, user_id, run_id, detail = seams.activity.await_args.args
        assert (todo_id, user_id, run_id) == ("todo-1", OWNER_ID, "s1")
        assert "(summary='a long report')" in detail


class TestTheEventSaysWhereTheResultWasRouted:
    """Routing is measurable: the event names the destination kind and the rule that chose it."""

    async def test_a_result_sent_where_the_user_is_active_names_that_chat_app(self) -> None:
        active = ChatChannel(
            source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="recent_activity"
        )
        with _seams(todo=_todo(), sent_on=ConversationSource.TELEGRAM) as seams:
            seams.target.return_value = active
            await deliver(seams, SCHEDULED, "report")

        seams.capture.assert_called_once_with(
            UserId(USER_ID),
            TodosRunResultDelivered(
                outcome="delivered",
                delivered=True,
                trigger_type=TriggerType.SCHEDULED_TODO.value,
                recurring=False,
                platform="telegram",
                destination="chat_app",
                destination_basis="recent_activity",
            ),
        )

    async def test_a_result_kept_in_the_app_for_an_active_user_says_so(self) -> None:
        with _seams(todo=_todo()) as seams:
            seams.target.return_value = InApp(reason="active_in_app")
            await deliver(seams, SCHEDULED, "report")

        seams.capture.assert_called_once_with(
            UserId(USER_ID),
            TodosRunResultDelivered(
                outcome="delivered",
                delivered=True,
                trigger_type=TriggerType.SCHEDULED_TODO.value,
                recurring=False,
                destination="in_app",
                destination_basis="active_in_app",
            ),
        )


class TestTheWideEventSaysWhatHappened:
    """The executor_run event is where an operator reads why a todo did or did not message."""

    async def test_a_delivered_result_names_its_todo_and_outcome(self) -> None:
        with _seams(todo=_todo(), sent_on=ConversationSource.TELEGRAM) as seams:
            async with captured_wide_event() as event:
                await deliver(seams, SCHEDULED, "report")

        assert event["todo_delivery"] == {
            "todo_id": "todo-1",
            "reply": "answered",
            "outcome": "delivered",
        }

    async def test_a_deleted_todo_is_a_warning_naming_it(self) -> None:
        with _seams(todo=None) as seams:
            async with captured_wide_event() as event:
                await deliver(seams, SCHEDULED, "report")

        (warning,) = event["warnings"]
        assert warning["msg"] == f"{LogTag.AGENT} todo run finished for a deleted todo"
        assert warning["todo_id"] == "todo-1"


class TestTheDecisionSeesTheStandingRules:
    async def test_the_standing_rules_reach_the_write_up_bounded(self) -> None:
        long_rules = (
            "- 2026-09-28: tell me every time.\n" + "x" * todo_constants.STANDING_RULES_MAX_CHARS
        )
        todo = _todo(
            canvas_content=f"## Standing rules\n{long_rules}\n\n## Key Details\n- thread abc\n"
        )
        with _seams(todo=todo) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.note == tracked_todo_delivery_note(
            "Watch the deploy",
            long_rules[: todo_constants.STANDING_RULES_MAX_CHARS],
            "- thread abc",
            runs_once=True,
            run_history=(),
        )

    async def test_key_details_reach_the_write_up_as_details_not_rules(self) -> None:
        todo = _todo(canvas_content="## Standing rules\n\n## Key Details\n- thread abc\n")
        with _seams(todo=todo) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.note == tracked_todo_delivery_note(
            "Watch the deploy",
            None,
            "- thread abc",
            runs_once=True,
            run_history=(),
        )

    @pytest.mark.regression
    async def test_a_request_an_older_todo_kept_in_key_details_still_reaches_the_write_up(
        self,
    ) -> None:
        details = "- tell me every time.\n" + "x" * todo_constants.DELIVERY_KEY_DETAILS_MAX_CHARS
        todo = _todo(canvas_content=f"## Key Details\n{details}\n\n## Current State\n- ok\n")
        with _seams(todo=todo) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.note == tracked_todo_delivery_note(
            "Watch the deploy",
            None,
            details[: todo_constants.DELIVERY_KEY_DETAILS_MAX_CHARS],
            runs_once=True,
            run_history=(),
        )

    @pytest.mark.regression
    async def test_a_new_todo_template_carries_no_rules(self) -> None:
        todo = _todo(canvas_content=CANVAS_TEMPLATE.format(title="Watch the deploy"))
        with _seams(todo=todo) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.note == tracked_todo_delivery_note(
            "Watch the deploy",
            None,
            None,
            runs_once=True,
            run_history=(),
        )

    @pytest.mark.regression
    async def test_a_title_cased_heading_still_reaches_the_write_up(self) -> None:
        todo = _todo(canvas_content="## Standing Rules\n- 2026-09-28: tell me every time.\n")
        with _seams(todo=todo) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.note == tracked_todo_delivery_note(
            "Watch the deploy",
            "- 2026-09-28: tell me every time.",
            None,
            runs_once=True,
            run_history=(),
        )

    async def test_a_todo_without_standing_rules_gets_the_defaults_alone(self) -> None:
        with _seams(todo=_todo(canvas_content="## Current State\n- ok\n")) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.note == tracked_todo_delivery_note(
            "Watch the deploy",
            None,
            None,
            runs_once=True,
            run_history=(),
        )

    async def test_a_todo_with_no_canvas_gets_the_defaults_alone(self) -> None:
        with _seams(todo=_todo(canvas_content=None)) as seams:
            await deliver(seams, SCHEDULED, "report")

        assert seams.note == tracked_todo_delivery_note(
            "Watch the deploy",
            None,
            None,
            runs_once=True,
            run_history=(),
        )


class TestTheWriteUpSeesWhatEarlierRunsSent:
    """Seen live: a nudge was silenced as already sent; comms never saw that nothing went out."""

    async def test_the_todos_record_of_earlier_runs_reaches_the_write_up(self) -> None:
        log = (
            "- 2026-11-06T05:31:00+00:00 [reminder_issued] Reminder delivered.\n"
            "- 2026-11-06T05:32:00+00:00 [run_finished] run r1: kept quiet: routine check\n"
        )
        with _seams(todo=_todo(recurrence="every_1h", activity_content=log)) as seams:
            await deliver(seams, SCHEDULED, "report")

        preamble = seams.note
        assert "[run_finished] run r1: kept quiet: routine check" in preamble
        assert "Reminder delivered." not in preamble


def _finished(**fields: object) -> FinishedTodoRun:
    return FinishedTodoRun.model_validate(
        {
            "run_id": "run-1",
            "todo_id": "todo-1",
            "user_id": USER_ID,
            "conversation_id": "run-conv",
            "trigger_type": TriggerType.SCHEDULED_TODO,
            "report_form": "write_up",
            "result_text": "report",
            "write_up": "Deploy failed.",
            "reply": ReplyOutcome.ANSWERED,
            **fields,
        }
    )


@contextmanager
def _job_seams() -> Iterator[AsyncMock]:
    """Queue finish jobs into a recorder and skip the Mongo retry's backoff sleeps."""
    enqueue = AsyncMock()
    with (
        patch.object(trd, "enqueue_worker_job", enqueue),
        patch.object(trd, "RedisPoolManager", MagicMock(get_pool=AsyncMock())),
        patch("app.db.mongodb.retry.TRANSIENT_MONGO_RETRY.sleep", AsyncMock()),
        patch.object(auth_utils, "load_user_context", AsyncMock(return_value=USER)),
    ):
        yield enqueue


def _queued(enqueue: AsyncMock, undone: str) -> FinishedTodoRun:
    """Return the payload of the one finish job queued, checking its key."""
    _pool, task, payload = enqueue.await_args.args
    assert task == todo_constants.TODO_RUN_FINISH_TASK
    assert enqueue.await_args.kwargs["_job_id"] == (
        f"{todo_constants.TODO_RUN_FINISH_JOB_PREFIX}{payload.run_id}:{undone}"
    )
    return payload


class TestAFinishedRunIsNeverRunAgainForItsDelivery:
    """The work is done, so a store failure is retried as delivery, never as the todo."""

    async def test_a_read_that_keeps_failing_is_delivered_by_the_runs_job(self) -> None:
        with (
            _seams(todo=_todo(), sent_on=ConversationSource.TELEGRAM) as seams,
            _job_seams() as enqueue,
        ):
            repo_read = seams.read_todo
            repo_read.side_effect = PyMongoError("primary stepped down")
            undone = await finish_todo_run(_finished())
            assert undone is not None
            await hand_unfinished_run_to_job(undone)
            seams.send.assert_not_awaited()
            payload = _queued(enqueue, "todo_run_result_not_delivered")

            repo_read.side_effect = None
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 2}, payload)

        seams.send.assert_awaited_once()
        assert seams.send.await_args.args[0].message == "Deploy failed."
        assert "result sent on telegram (summary='report')" in seams.entry()

    async def test_an_entry_that_keeps_failing_is_written_by_its_job_without_a_second_send(
        self,
    ) -> None:
        with (
            _seams(todo=_todo(), sent_on=ConversationSource.TELEGRAM) as seams,
            _job_seams() as enqueue,
        ):
            seams.activity.side_effect = PyMongoError("primary stepped down")
            undone = await finish_todo_run(_finished())
            assert undone is not None
            await hand_unfinished_run_to_job(undone)
            payload = _queued(enqueue, "todo_run_result_not_recorded")

            seams.activity.side_effect = None
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 1}, payload)

        seams.send.assert_awaited_once()
        assert "result sent on telegram" in seams.entry()

    async def test_the_job_keeps_what_the_runs_reply_settled_to(self) -> None:
        """A retried job must not send a write-up its run's reply settled silent."""
        with _seams(todo=_todo()) as seams, _job_seams() as enqueue:
            seams.activity.side_effect = PyMongoError("primary stepped down")
            undone = await finish_todo_run(_finished(reply=ReplyOutcome.SILENT, write_up=""))
            assert undone is not None
            await hand_unfinished_run_to_job(undone)

        assert _queued(enqueue, "todo_run_result_not_recorded").reply is ReplyOutcome.SILENT
        seams.send.assert_not_awaited()
        seams.in_app.assert_not_awaited()

    async def test_a_job_for_a_run_already_finished_sends_nothing(self) -> None:
        marker = f"[{todo_constants.TodoActivityEvent.RUN_FINISHED.value}] run run-1:"
        todo = _todo(activity_content=f"- t {marker} result sent")
        with _seams(todo=todo) as seams, _job_seams():
            await tracked_todo_tasks.finish_tracked_todo_run({"job_try": 1}, _finished())

        seams.send.assert_not_awaited()
        seams.activity.assert_not_awaited()
