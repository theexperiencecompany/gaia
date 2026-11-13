"""JudgeContext: each source is read, each list is bounded, and a source the user lacks is absent."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.agents import OutcomeState
from app.constants.attention_profile import DEFAULT_ATTENTION_PROFILE
from app.constants.outbox_attention import DEFAULT_UNSOLICITED_BUDGET
from app.constants.outbox_judge import (
    JUDGE_BATCH_MAX,
    JUDGE_CALENDAR_EVENTS_MAX,
    JUDGE_MEMORIES_MAX,
    JUDGE_MESSAGE_CHARS,
    JUDGE_MESSAGES_MAX,
    JUDGE_SOURCE_EXCERPT_CHARS,
    JUDGE_UPCOMING_RUNS_MAX,
)
from app.constants.task_report import FactKind
from app.models.attention_profile_models import AttentionProfileDocument, ProfileAnswer
from app.models.attention_settings_models import AttentionSettings
from app.models.calendar_models import (
    CalendarEventsResponse,
    GoogleCalendarEventDateTime,
    GoogleCalendarEventResource,
)
from app.models.conversation_models import ConversationMessageRow
from app.models.memory_models import MemoryEntry, MemorySearchResult
from app.models.outbox_models import OutboxItemDocument, OutboxMessageDocument
from app.models.quiet_hours_models import QuietHours
from app.models.task_report_models import ReportFact, TaskReport
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.services.outbox.judge_context import build_judge_context
from app.services.outbox.models import (
    ComposeMode,
    Initiative,
    ItemState,
    MessageState,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
    UrgencyClass,
)
from app.utils.errors import IntegrationNotConnectedError
from tests._harness.judge import NOW, notice, verdict

MODULE = "app.services.outbox.judge_context"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
USER = AuthenticatedUser(
    user_id=USER_ID,
    timezone="Asia/Kolkata",
    quiet_hours=QuietHours(enabled=True, start_hour=23, end_hour=7),
)


def _row(
    text: str, *, minutes_ago: int, from_user: bool = True, source: str | None = "whatsapp"
) -> ConversationMessageRow:
    return ConversationMessageRow(
        conversation_id="c1",
        source=source,
        type="user" if from_user else "bot",
        response=text,
        date=(NOW - timedelta(minutes=minutes_ago)).isoformat(),
    )


def _item(
    report_id: str,
    *,
    age_seconds: int,
    label: str = "L",
    state: ItemState = ItemState.QUEUED,
    **extra: Any,
) -> OutboxItemDocument:
    return OutboxItemDocument(
        user_id=USER_ID,
        report_id=report_id,
        report=notice(
            report_id=report_id,
            subject={"kind": "todo_run", "id": report_id, "label": label},
        ),
        state=state,
        expires_at=NOW + timedelta(days=1),
        created_at=NOW - timedelta(seconds=age_seconds),
        **extra,
    )


class _Sources:
    """Every read the builder makes, stubbed; a test changes only what it is about."""

    def __init__(self) -> None:
        self.messages: list[ConversationMessageRow] = []
        self.profile = [ProfileAnswer(q="Q", a="A")]
        self.memories: list[MemoryEntry] = []
        self.calendar: CalendarEventsResponse | Exception = CalendarEventsResponse(
            events=[], selected_calendars=[], has_more=False, calendars_truncated=[]
        )
        self.unsettled: list[OutboxItemDocument] = []
        self.waits: list[OutboxItemDocument] = []
        self.settled_for_owner: list[OutboxItemDocument] = []
        self.sent: list[OutboxMessageDocument] = []
        self.todos: list[TodoDocument] = []
        self.workflows: list[Any] = []
        self.presence: dict[str, Any] = {"captured_at": 0, "last_seen": {}}
        self.workflow_conversation: Any = None
        self.todo_conversation: str | None = None
        self.repos = SimpleNamespace()
        self.log = MagicMock()


@contextmanager
def _world() -> Iterator[_Sources]:
    s = _Sources()

    async def calendar(*_: Any, **__: Any) -> CalendarEventsResponse:
        if isinstance(s.calendar, Exception):
            raise s.calendar
        return s.calendar

    with ExitStack() as stack:
        enter = stack.enter_context
        s.repos.recent_messages = AsyncMock(side_effect=lambda *a, **k: s.messages)
        enter(patch(f"{MODULE}.conversation_repository.recent_messages", s.repos.recent_messages))
        enter(
            patch(
                f"{MODULE}.attention_profiles_repository.get_or_seed",
                AsyncMock(
                    side_effect=lambda user_id, seed: AttentionProfileDocument(
                        user_id=user_id, answers=s.profile
                    )
                ),
            )
        )
        s.repos.recall = AsyncMock(
            side_effect=lambda *a, **k: MemorySearchResult(memories=s.memories)
        )
        enter(
            patch(
                f"{MODULE}.attention_settings_repository.read",
                AsyncMock(return_value=AttentionSettings()),
            )
        )
        enter(patch(f"{MODULE}.recall", s.repos.recall))
        s.repos.calendar = calendar
        enter(patch(f"{MODULE}.get_calendar_events", calendar))
        enter(
            patch(
                f"{MODULE}.outbox_items_repository.list_unsettled",
                AsyncMock(side_effect=lambda *a, **k: s.unsettled),
            )
        )
        enter(
            patch(
                f"{MODULE}.outbox_items_repository.list_waits",
                AsyncMock(side_effect=lambda *a, **k: s.waits),
            )
        )
        s.repos.settled_for_owner = AsyncMock(side_effect=lambda *a, **k: s.settled_for_owner)
        enter(
            patch(
                f"{MODULE}.outbox_items_repository.list_settled_for_owner",
                s.repos.settled_for_owner,
            )
        )
        enter(
            patch(
                f"{MODULE}.outbox_messages_repository.sent_since",
                AsyncMock(side_effect=lambda *a, **k: s.sent),
            )
        )
        enter(
            patch(
                f"{MODULE}.todo_repository.find_running_tracked_for_user",
                AsyncMock(side_effect=lambda *a, **k: s.todos),
            )
        )
        enter(
            patch(
                f"{MODULE}.workflow_repository.find_activated_for_user",
                AsyncMock(side_effect=lambda *a, **k: s.workflows),
            )
        )
        enter(
            patch(
                f"{MODULE}.conversation_repository.find_workflow_conversation",
                AsyncMock(side_effect=lambda *a, **k: s.workflow_conversation),
            )
        )
        enter(
            patch(
                f"{MODULE}.conversation_repository.find_todo_conversation_id",
                AsyncMock(side_effect=lambda *a, **k: s.todo_conversation),
            )
        )
        enter(patch(f"{MODULE}.read_presence", AsyncMock(side_effect=lambda *a, **k: s.presence)))
        enter(patch(f"{MODULE}.log", s.log))
        yield s


def _todo(**fields: Any) -> TodoDocument:
    return TodoDocument.model_validate(
        {"id": "t1", "user_id": USER_ID, "title": "Chase Acme", **fields}
    )


async def _build(report: Any = None) -> dict[str, Any]:
    context = await build_judge_context(report or notice(), USER, now=NOW)
    return context.as_state()


async def test_the_item_is_what_the_producer_reported_with_the_producers_own_hint() -> None:
    with _world():
        state = await _build()

    assert state["item"] == {
        "producer": "todo",
        "outcome": "info",
        "subject": "Weekly price check",
        "facts": ["The flight fell to 210 dollars."],
        "producer_suggested": {"urgency": "background"},
    }
    assert state["ask"] == {
        "initiative": "self_initiated",
        "delivery_timing": "when_done",
        "may_wake": False,
    }


async def test_the_users_clock_comes_from_their_timezone_and_quiet_hours() -> None:
    with _world():
        state = await _build()

    assert state["user"]["timezone"] == "Asia/Kolkata"
    assert (state["user"]["usual_wake"], state["user"]["usual_sleep"]) == ("07:00", "23:00")
    assert state["attention_settings"] == {
        "quiet_hours": "23:00-07:00",
        "unsolicited_budget_per_day": DEFAULT_UNSOLICITED_BUDGET,
        "rules": [],
    }


async def test_the_attention_profile_is_read_for_the_user() -> None:
    with _world() as world:
        world.profile = [ProfileAnswer(q="Weekends?", a="Keep work out.")]
        state = await _build()

    assert state["user"]["attention_profile"] == [{"q": "Weekends?", "a": "Keep work out."}]


async def test_a_users_first_read_seeds_the_defaults() -> None:
    seed = AsyncMock(
        return_value=AttentionProfileDocument(
            user_id=USER_ID, answers=[ProfileAnswer(q="q", a="a")]
        )
    )
    with _world(), patch(f"{MODULE}.attention_profiles_repository.get_or_seed", seed):
        await _build()

    assert seed.await_args.args[0] == USER_ID
    assert [(a.q, a.a) for a in seed.await_args.args[1]] == list(DEFAULT_ATTENTION_PROFILE)


async def test_the_users_messages_and_gaias_replies_are_split_across_surfaces_newest_first() -> (
    None
):
    with _world() as world:
        world.messages = [
            _row("older", minutes_ago=30, source="whatsapp"),
            _row("a reply", minutes_ago=20, from_user=False, source="whatsapp"),
            _row("newest", minutes_ago=5, source=None),
        ]
        state = await _build()

    assert [(m["surface"], m["text"]) for m in state["recent_user_messages"]] == [
        ("web", "newest"),
        ("whatsapp", "older"),
    ]
    assert [m["text"] for m in state["recent_gaia_replies"]] == ["a reply"]


async def test_messages_are_bounded_in_age_count_and_length() -> None:
    with _world() as world:
        world.messages = [
            _row(f"m{i}", minutes_ago=i + 1) for i in range(JUDGE_MESSAGES_MAX + 10)
        ] + [
            _row("x" * (JUDGE_MESSAGE_CHARS * 2), minutes_ago=0),
            _row("ancient", minutes_ago=60 * 24 * 30),
        ]
        state = await _build()

    texts = [m["text"] for m in state["recent_user_messages"]]
    assert len(texts) == JUDGE_MESSAGES_MAX
    assert "ancient" not in texts
    assert max(len(t) for t in texts) == JUDGE_MESSAGE_CHARS


async def test_a_message_with_no_readable_date_is_skipped_and_said_so() -> None:
    with _world() as world:
        world.messages = [
            ConversationMessageRow(conversation_id="c", type="user", response="no date", date=None),
            _row("dated", minutes_ago=1),
        ]
        state = await _build()

    assert [m["text"] for m in state["recent_user_messages"]] == ["dated"]
    world.log.warning.assert_called_once()


async def test_memory_is_recalled_for_the_items_own_facts_and_bounded() -> None:
    with _world() as world:
        world.memories = [MemoryEntry(content=f"fact {i}") for i in range(JUDGE_MEMORIES_MAX + 3)]
        state = await _build()

    assert len(state["memory"]) == JUDGE_MEMORIES_MAX
    query = world.repos.recall.await_args.args[1]
    assert "Weekly price check" in query and "210 dollars" in query


async def test_a_calendar_the_user_has_is_read_for_the_next_day() -> None:
    with _world() as world:
        world.calendar = CalendarEventsResponse(
            events=[
                GoogleCalendarEventResource(
                    summary="Investor call",
                    start=GoogleCalendarEventDateTime(dateTime="2026-11-10T14:00:00+00:00"),
                    end=GoogleCalendarEventDateTime(dateTime="2026-11-10T15:00:00+00:00"),
                ),
                GoogleCalendarEventResource(summary="No start"),
            ],
            selected_calendars=["primary"],
            has_more=False,
            calendars_truncated=[],
        )
        state = await _build()

    assert state["calendar"] == [
        {
            "start": "2026-11-10T14:00:00+00:00",
            "end": "2026-11-10T15:00:00+00:00",
            "title": "Investor call",
        }
    ]


async def test_a_calendar_that_is_not_connected_is_absent_not_empty() -> None:
    with _world() as world:
        world.calendar = IntegrationNotConnectedError(
            integration_id="googlecalendar",
            integration_name="Google Calendar",
            why="the user never connected it",
        )
        state = await _build()

    assert "calendar" not in state
    world.log.warning.assert_not_called()


async def test_a_calendar_that_fails_to_read_is_absent_with_a_logged_warning() -> None:
    with _world() as world:
        world.calendar = RuntimeError("google is down")
        state = await _build()

    assert "calendar" not in state
    assert "calendar" in world.log.warning.call_args.args[0]


async def test_calendar_events_are_bounded() -> None:
    event = GoogleCalendarEventResource(
        summary="e", start=GoogleCalendarEventDateTime(dateTime="2026-11-10T14:00:00+00:00")
    )
    with _world() as world:
        world.calendar = CalendarEventsResponse(
            events=[event] * (JUDGE_CALENDAR_EVENTS_MAX + 5),
            selected_calendars=[],
            has_more=False,
            calendars_truncated=[],
        )
        state = await _build()

    assert len(state["calendar"]) == JUDGE_CALENDAR_EVENTS_MAX


async def test_what_arrived_with_the_item_is_the_batch_and_the_rest_is_held_with_its_age() -> None:
    with _world() as world:
        world.unsettled = [
            _item("fresh", age_seconds=5, label="Just arrived"),
            _item("stalled", age_seconds=3 * 3600, label="Stalled thing"),
        ]
        state = await _build()

    assert [i["subject"] for i in state["other_items_in_batch"]] == ["Just arrived"]
    assert state["held_items"] == [{"subject": "Stalled thing", "held_minutes": 180}]


async def test_the_batch_is_bounded() -> None:
    with _world() as world:
        world.unsettled = [_item(f"b{i}", age_seconds=1) for i in range(JUDGE_BATCH_MAX + 4)]
        state = await _build()

    assert len(state["other_items_in_batch"]) == JUDGE_BATCH_MAX


async def test_open_subjects_and_pending_asks_span_the_outbox_and_the_users_todos() -> None:
    with _world() as world:
        world.unsettled = [_item("u", age_seconds=600, label="Held digest")]
        world.todos = [
            _todo(id="t1", title="Chase Acme", waiting_on="time"),
            _todo(id="t2", title="Pick a venue", waiting_on="user", question="Which venue?"),
        ]
        state = await _build()

    assert {s["label"] for s in state["open_subjects"]} == {"Held digest", "Chase Acme"}
    assert [(a["label"], a["question"]) for a in state["pending_asks"]] == [
        ("Pick a venue", "Which venue?")
    ]


async def test_what_gaia_told_the_user_in_the_last_day_is_the_ledger() -> None:
    with _world() as world:
        world.sent = [
            OutboxMessageDocument(
                user_id=USER_ID,
                compose_attempt_id="a1",
                report_ids=["r"],
                state=MessageState.SENT,
                mode=ComposeMode.UNSOLICITED,
                max_class=UrgencyClass.ROUTINE,
                parts=["Your flight", "dropped to 210."],
                destination="chat_app",
                destination_basis="priority",
                conversation_id="c",
                recorded_in=["c"],
                sent_at=NOW - timedelta(hours=2),
                expires_at=NOW + timedelta(days=1),
            )
        ]
        state = await _build()

    assert state["recent_deliveries"] == [
        {
            "at": (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            "channel": "chat_app",
            "summary": "Your flight dropped to 210.",
        }
    ]


async def test_the_source_excerpt_is_the_quotes_of_the_facts_and_bounded() -> None:
    report = RunReport(
        report_id="r",
        recipient=USER_ID,
        producer=ProducerKind.EXECUTOR,
        subject=Subject(kind=SubjectKind.ASK, id="a", label="Inbox"),
        occurred_at=NOW,
        initiative=Initiative.ASKED,
        report=TaskReport(
            outcome=OutcomeState.DONE,
            facts=[
                ReportFact(
                    text="Rejected wire",
                    kind=FactKind.OBSERVED,
                    quote="q" * (JUDGE_SOURCE_EXCERPT_CHARS * 2),
                ),
                ReportFact(text="Other", kind=FactKind.OBSERVED),
            ],
        ),
    )
    with _world():
        state = await _build(report)

    assert len(state["item"]["source_excerpt"]) == JUDGE_SOURCE_EXCERPT_CHARS
    assert state["item"]["facts"] == ["Rejected wire", "Other"]
    assert state["item"]["outcome"] == "done"


async def test_where_the_user_is_active_is_their_presence() -> None:
    now_epoch = int(NOW.timestamp())
    with _world() as world:
        world.presence = {
            "captured_at": now_epoch,
            "last_seen": {"whatsapp": now_epoch - 60, "web": now_epoch - 3600},
        }
        state = await _build()

    assert state["presence"]["last_active_surface"] == "whatsapp"
    assert set(state["presence"]["active_surfaces"]) == {"whatsapp", "web"}


async def test_a_user_never_seen_has_no_last_active_surface() -> None:
    with _world():
        state = await _build()

    assert state["presence"] == {"active_surfaces": {}}


def _workflow(wf_id: str, minutes: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=wf_id,
        title=f"Workflow {wf_id}",
        trigger_config=SimpleNamespace(next_run=NOW + timedelta(minutes=minutes)),
    )


async def test_only_runs_inside_the_next_three_hours_are_upcoming_soonest_first() -> None:
    with _world() as world:
        world.workflows = [_workflow("late", 4 * 60), _workflow("soon", 20), _workflow("past", -5)]
        world.todos = [_todo(id="t9", title="Todo run", scheduled_at=NOW + timedelta(minutes=10))]
        state = await _build()

    assert [r["run_id"] for r in state["upcoming_runs"]] == ["todo:t9", "workflow:soon"]
    assert [r["kind"] for r in state["upcoming_runs"]] == ["todo_run", "workflow_run"]


async def test_upcoming_runs_are_bounded() -> None:
    with _world() as world:
        world.workflows = [_workflow(f"w{i}", 5 + i) for i in range(JUDGE_UPCOMING_RUNS_MAX + 5)]
        state = await _build()

    assert len(state["upcoming_runs"]) == JUDGE_UPCOMING_RUNS_MAX


async def test_a_runs_hit_rate_is_the_share_of_its_recent_runs_that_were_told() -> None:
    with _world() as world:
        world.workflows = [_workflow("wf", 30)]
        world.workflow_conversation = SimpleNamespace(conversation_id="wf-chat")
        world.settled_for_owner = [
            _item("a", age_seconds=1, state=ItemState.SENT),
            _item("b", age_seconds=2, state=ItemState.DROPPED),
            _item("c", age_seconds=3, state=ItemState.DROPPED),
            _item("d", age_seconds=4, state=ItemState.SENT),
        ]
        state = await _build()

    assert state["upcoming_runs"][0]["hit_rate"] == 0.5
    assert world.repos.settled_for_owner.await_args.args[:2] == (USER_ID, "wf-chat")


async def test_a_run_that_never_produced_anything_has_no_hit_rate_yet() -> None:
    with _world() as world:
        world.workflows = [_workflow("wf", 30)]
        world.workflow_conversation = SimpleNamespace(conversation_id="wf-chat")
        state = await _build()

    assert "hit_rate" not in state["upcoming_runs"][0]


async def test_past_waits_are_the_runs_the_judge_told_items_to_wait_for() -> None:
    waiting = _item(
        "w1",
        age_seconds=900,
        label="Digest",
        judgement={"verdict": verdict(wait_for_run="workflow:wf"), "judge_unavailable": False},
    )
    with _world() as world:
        world.waits = [waiting]
        state = await _build()

    assert state["past_waits"] == [
        {
            "run_id": "workflow:wf",
            "subject": "Digest",
            "decided_at": (NOW - timedelta(seconds=900)).isoformat().replace("+00:00", "Z"),
        }
    ]


async def test_a_source_that_exists_and_fails_fails_the_build() -> None:
    with _world() as world:
        world.repos.recent_messages.side_effect = RuntimeError("mongo down")
        with pytest.raises(RuntimeError, match="mongo down"):
            await _build()
