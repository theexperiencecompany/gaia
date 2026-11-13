"""The outbox as a user lives it: events on a clock, asserted on the ledger rows they leave.

Scenarios from the outbound-layer catalogue that need no holds: B3, B4, B8, B9, B16 and the
record-is-not-alert and one-destination rules, then the executor, workflow and tracked-todo
producers run through their real report builders (A1, A2, A8-A11, A13, B1, B15-B17, B21). Needs USE_REAL_SERVICES=1 (real Mongo for the
two outbox collections); the model, transports, thread and clock are doubled (see the harness).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import todo_run_delivery as trd
from app.agents.core.background.run_report import (
    RunOutcome,
    failed_outcome,
    finished_outcome,
    run_report,
)
from app.agents.core.background.session import ExecutorRun, RunKind, TodoRun
from app.agents.core.background.todo_run_delivery import deliver_todo_run_result
from app.agents.core.outcome_review import OutcomeReview
from app.agents.prompts.compose_prompts import OUTCOME_REPLY_SHAPES
from app.constants.agents import OutcomeState
from app.constants.outbound import OUTBOUND_TTL_SECONDS_DEFAULT, OUTBOUND_TTL_SECONDS_GREETING
from app.constants.outbox import LIVE_WATCH_WINDOW_SECONDS, OUTBOX_BATCHED_JOB_ID_SUFFIX
from app.constants.task_report import FactKind, NeedsYouKind
from app.models.chat_models import ConversationSource
from app.models.ownership_models import DeliveryPolicy, DeliveryTiming
from app.models.platform_models import PlatformLinkResult
from app.models.task_report_models import (
    FinishTaskArgs,
    ReportFact,
    ReportNeedsYou,
    ReportScope,
    TaskReport,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.schemas.outbound import OutboundAttachment
from app.services.outbox.deliver import flush_subject
from app.services.outbox.judge_models import Relevance, Sensitivity
from app.services.outbox.models import (
    ComposeResult,
    DropReason,
    Initiative,
    ItemState,
    MessageState,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
    SubjectMerge,
    UrgencyClass,
)
from app.services.outbox.transport.bot_queue import OutboundResult
from app.services.platform_link_completion import complete_platform_link
from app.services.platform_link_service import PlatformLinkService
from tests._harness.judge import verdict
from tests.e2e._harness.outbox_timeline import (
    DELIVER,
    T0,
    OutboxTimeline,
    World,
    outbox_timeline,
    prepare_collections,
)

pytestmark = pytest.mark.e2e

USER = "6812f0b3c9a14e2b7d5a91cc"


def _reminder(
    n: int = 1, *, owner: str | None = "web-1", minutes: float = 0, **overrides: object
) -> NoticeReport:
    fields: dict[str, object] = {
        "report_id": f"rem:r{n}:1",
        "recipient": USER,
        "producer": ProducerKind.REMINDER,
        "subject": Subject(
            kind=SubjectKind.REMINDER, id=f"r{n}:1", owner_conversation_id=owner, label="Standup"
        ),
        "occurred_at": T0 + timedelta(minutes=minutes),
        "initiative": Initiative.USER_SCHEDULED,
        "delivery_policy": DeliveryPolicy(timing=DeliveryTiming.AT_TIME, may_wake=True),
        "outcome": NoticeOutcome.INFO,
        "facts": ["Standup", "Join now"],
    }
    return NoticeReport.model_validate({**fields, **overrides})


def _run(
    report_id: str,
    outcome: OutcomeState,
    *,
    subject_id: str = "todo-1",
    merge: SubjectMerge = SubjectMerge.REPLACE,
    minutes: float = 0,
    initiative: Initiative = Initiative.SELF_INITIATED,
) -> RunReport:
    return RunReport(
        report_id=report_id,
        recipient=USER,
        producer=ProducerKind.TODO,
        subject=Subject(
            kind=SubjectKind.TODO_RUN,
            id=subject_id,
            owner_conversation_id="web-1",
            label="Inbox check",
            merge=merge,
        ),
        occurred_at=T0 + timedelta(minutes=minutes),
        initiative=initiative,
        report=TaskReport(outcome=outcome),
    )


@pytest.fixture
async def world(mongo_db) -> World:
    await prepare_collections(mongo_db)
    world = World(user_id=USER)
    world.link("telegram", "tg-1")
    world.link("whatsapp", "wa-1")
    world.priority = ["whatsapp", "telegram"]
    world.app_chat("web-1")
    world.dm("telegram", "tg-dm")
    world.dm("whatsapp", "wa-dm")
    return world


@pytest.fixture
async def tl(mongo_db, world: World, fake_redis) -> AsyncIterator[OutboxTimeline]:
    with outbox_timeline(mongo_db, world, fake_redis) as timeline:
        yield timeline
    for name in ("outbox_items", "outbox_messages"):
        await mongo_db[name].drop()


async def test_b3_a_reminder_at_2am_is_sent_at_its_time_as_an_interrupt(tl: OutboxTimeline) -> None:
    tl.clock.current = T0.replace(hour=2)
    await tl.submit(_reminder())
    await tl.drain()

    [message] = await tl.ledger()
    assert message.state is MessageState.SENT
    assert message.max_class is UrgencyClass.INTERRUPT
    assert message.mode.value == "interrupt"
    assert message.sent_at == tl.clock.current
    [event] = tl.sinks.analytics
    assert (event.producer, event.mode, event.max_class) == ("reminder", "interrupt", "interrupt")


async def test_b16_the_same_report_twice_is_one_message(tl: OutboxTimeline) -> None:
    tl.world.linked.clear()
    await tl.submit(_reminder())
    await tl.submit(_reminder())
    await tl.drain()
    await tl.submit(_reminder())
    await tl.drain()

    assert len(await tl.ledger()) == 1
    assert len(await tl.items()) == 1
    assert len(tl.sinks.ws) == 1


async def test_a_rerun_of_a_job_a_crash_left_queued_still_tells_the_user_once(
    tl: OutboxTimeline,
) -> None:
    report = _reminder()
    from app.workers.tasks.outbox_tasks import outbox_intake

    with pytest.MonkeyPatch.context() as mp:

        async def crash(*_: object, **__: object) -> None:
            raise RuntimeError("worker died")

        mp.setattr("app.services.outbox.intake.flush_subject", crash)
        with pytest.raises(RuntimeError):
            await outbox_intake({}, report.model_dump(mode="json"))
    [item] = await tl.items()
    assert item.state is ItemState.QUEUED

    await outbox_intake({}, report.model_dump(mode="json"))
    await outbox_intake({}, report.model_dump(mode="json"))

    assert len(await tl.ledger()) == 1
    assert [i.state for i in await tl.items()] == [ItemState.SENT]


async def test_b4_nothing_new_is_recorded_and_never_alerted(tl: OutboxTimeline) -> None:
    await tl.submit(_run("run-1", OutcomeState.NOTHING_NEW))
    await tl.drain()

    [item] = await tl.items()
    assert (item.state, item.drop_reason) == (ItemState.DROPPED, DropReason.NOTHING_NEW)
    assert await tl.ledger() == []
    assert tl.sinks.bot == [] and tl.sinks.ws == []


async def test_b8_a_newer_report_of_a_replace_subject_supersedes_the_one_not_yet_told(
    tl: OutboxTimeline, mongo_db
) -> None:
    older = _run("run-1", OutcomeState.PARTIAL, minutes=0, initiative=Initiative.ASKED)
    await _park_queued(tl, older)
    await tl.submit(_run("run-2", OutcomeState.DONE, minutes=5, initiative=Initiative.ASKED))
    await tl.drain()

    states = {i.report_id: i.state for i in await tl.items()}
    assert states == {"run-1": ItemState.SUPERSEDED, "run-2": ItemState.SENT}
    [message] = await tl.ledger()
    assert message.report_ids == ["run-2"]


async def test_an_update_nobody_asked_for_waits_out_the_batch_window_as_a_deferred_job(
    tl: OutboxTimeline,
) -> None:
    report = _run("run-1", OutcomeState.DONE, initiative=Initiative.SELF_INITIATED)
    await tl.submit(report)

    await tl.drain()
    assert await tl.ledger() == []
    assert list(tl.arq.jobs) == [f"outbox:run-1{OUTBOX_BATCHED_JOB_ID_SUFFIX}"]

    await tl.at(1)
    await tl.drain()
    assert len(await tl.ledger()) == 1


async def test_b9_accumulating_reports_of_a_subject_are_one_message(tl: OutboxTimeline) -> None:
    first = _run("run-1", OutcomeState.DONE, merge=SubjectMerge.ACCUMULATE, minutes=0)
    await _park_queued(tl, first)
    await tl.submit(_run("run-2", OutcomeState.DONE, merge=SubjectMerge.ACCUMULATE, minutes=5))
    await tl.drain()
    await tl.at(1)
    await tl.drain()

    [message] = await tl.ledger()
    assert sorted(message.report_ids) == ["run-1", "run-2"]
    assert tl.sinks.analytics[0].items_count == 2


async def test_record_is_not_alert_a_web_reminder_is_recorded_where_set_and_alerted_once_elsewhere(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_reminder(owner="web-1"))
    await tl.drain()

    [message] = await tl.ledger()
    assert message.destination == "chat_app"
    assert message.conversation_id == "tg-dm"
    assert message.recorded_in == ["tg-dm", "web-1"]
    assert [source for source, _ in tl.sinks.bot] == ["telegram"]
    assert tl.sinks.ws == []
    assert tl.world.saved.keys() == {"tg-dm", "web-1"}
    assert tl.world.unread == {"web-1"}
    assert {t for t, _, _ in tl.graph.writes} == {"tg-dm", "web-1"}


async def test_one_destination_the_active_chat_app_beats_the_priority_order(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_reminder(owner=None))
    await tl.drain()

    assert [source for source, _ in tl.sinks.bot] == ["telegram"]
    assert tl.sinks.ws == []


async def test_an_answer_goes_back_to_the_dm_that_asked_when_nobody_is_active(
    tl: OutboxTimeline,
) -> None:
    await tl.submit(_reminder(owner="tg-dm"))
    await tl.drain()

    [message] = await tl.ledger()
    assert message.destination_basis == "owner_chat"
    assert [source for source, _ in tl.sinks.bot] == ["telegram"]


async def test_an_app_alert_is_recorded_in_the_chat_and_pushed_to_open_clients(
    tl: OutboxTimeline,
) -> None:
    tl.world.linked.clear()
    await tl.active_on(ConversationSource.WEB)
    await tl.submit(_reminder(owner="web-1"))
    await tl.drain()

    [message] = await tl.ledger()
    assert (message.destination, message.recorded_in) == ("in_app", ["web-1"])
    assert tl.sinks.bot == []
    assert [c for c, _ in tl.sinks.ws] == ["web-1"]


async def test_the_composed_message_joins_the_thread_under_the_thread_lock_and_nothing_else_runs(
    tl: OutboxTimeline,
) -> None:
    tl.world.linked.clear()
    await tl.submit(_reminder(owner="web-1"))
    await tl.drain()

    [(thread, node, lock_held)] = tl.graph.writes
    assert (thread, node, lock_held) == ("web-1", "tools", True)
    [message] = tl.graph.threads["web-1"]
    assert message.type == "ai"


async def test_a_composer_that_drops_a_must_say_item_is_asked_again_once(
    tl: OutboxTimeline,
) -> None:
    tl.compose.script = [
        ComposeResult.model_validate(
            {
                "dispositions": [{"item_id": "rem:r1:1", "action": "skip", "reason": "x"}],
                "parts": [],
            }
        )
    ]
    await tl.submit(_reminder())
    await tl.drain()

    assert len(tl.compose.calls) == 2
    assert "broke a rule" in str(tl.compose.calls[1][-1].content)
    [message] = await tl.ledger()
    assert message.degraded is False


async def test_a_composer_that_breaks_the_contract_twice_gets_the_plain_render_sent(
    tl: OutboxTimeline,
) -> None:
    bad = ComposeResult.model_validate({"dispositions": [], "parts": []})
    tl.compose.script = [bad, bad]
    await tl.submit(_reminder())
    await tl.drain()

    [message] = await tl.ledger()
    assert message.degraded is True
    assert "Standup; Join now" in message.parts[0]
    assert tl.sinks.analytics[0].degraded is True


async def test_a_chat_app_that_refuses_the_message_fails_the_item_and_logs_it(
    tl: OutboxTimeline,
) -> None:
    tl.sinks.bot_result = OutboundResult.FAILED
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_reminder(owner=None))
    await tl.drain()

    [item] = await tl.items()
    assert item.state is ItemState.FAILED
    [message] = await tl.ledger()
    assert message.state is MessageState.FAILED
    assert tl.sinks.analytics == []
    assert tl.graph.writes == []


async def test_two_flushers_on_one_queued_item_send_one_message(tl: OutboxTimeline) -> None:
    await _park_queued(tl, _reminder(owner=None))

    await asyncio.gather(flush_subject(USER, "r1:1"), flush_subject(USER, "r1:1"))

    assert len(await tl.ledger()) == 1
    assert len(tl.compose.calls) == 1
    assert len(tl.sinks.bot) + len(tl.sinks.ws) == 1


def _browser_notice(
    report_id: str,
    outcome: NoticeOutcome,
    *,
    owner: str = "tg-dm",
    subject_id: str = "job-1",
    minutes: float = 0,
    **overrides: object,
) -> NoticeReport:
    fields: dict[str, object] = {
        "report_id": report_id,
        "recipient": USER,
        "producer": ProducerKind.BROWSER,
        "subject": Subject(
            kind=SubjectKind.BROWSER_JOB,
            id=subject_id,
            owner_conversation_id=owner,
            label="Browser task",
            merge=SubjectMerge.REPLACE,
        ),
        "occurred_at": T0 + timedelta(minutes=minutes),
        "initiative": Initiative.ASKED,
        "outcome": outcome,
        "facts": [f"fact of {report_id}"],
    }
    return NoticeReport.model_validate({**fields, **overrides})


def _step_photo(n: int, *, owner: str = "tg-dm") -> NoticeReport:
    photo = OutboundAttachment(
        url=f"https://cdn.example.com/{n}.jpg",
        filename=f"browser-step-{n}.jpg",
        caption=f"Step {n}",
    )
    return _browser_notice(
        f"browser:job-1:progress:{n}",
        NoticeOutcome.PROGRESS,
        owner=owner,
        minutes=n / 10,
        artifacts=[photo],
    )


async def test_b18_twelve_browser_steps_nobody_watches_leave_the_final_result_only(
    tl: OutboxTimeline,
) -> None:
    for n in range(1, 13):
        await tl.at(n / 10)
        await tl.submit(_step_photo(n))
    await tl.drain()

    items = await tl.items()
    assert {(i.state, i.drop_reason) for i in items} == {
        (ItemState.DROPPED, DropReason.NOT_WATCHING)
    }
    assert len(items) == 12
    assert await tl.ledger() == []
    assert (tl.sinks.bot, tl.sinks.files, tl.sinks.ws) == ([], [], [])

    await tl.at(3)
    await tl.submit(
        _run("final", OutcomeState.DONE, subject_id="ask-1", initiative=Initiative.ASKED)
    )
    await tl.drain()

    [message] = await tl.ledger()
    assert message.report_ids == ["final"]
    assert len(tl.sinks.bot) == 1
    assert tl.sinks.files == []


async def test_b18_a_user_watching_live_is_shown_each_step_as_a_photo_without_a_model_call(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.TELEGRAM)
    for n in range(1, 4):
        await tl.at(n / 10)
        await tl.submit(_step_photo(n))
        await tl.drain()

    assert tl.sinks.files == [
        ("telegram", f"https://cdn.example.com/{n}.jpg", f"Step {n}") for n in (1, 2, 3)
    ]
    assert tl.sinks.bot == []
    assert tl.compose.calls == []
    assert [m.parts for m in await tl.ledger()] == [[], [], []]


async def test_b18_a_user_who_stopped_watching_stops_being_shown_steps(tl: OutboxTimeline) -> None:
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.at(1)
    await tl.submit(_step_photo(1))
    await tl.drain()
    await tl.at(1 + LIVE_WATCH_WINDOW_SECONDS / 60 + 1)
    await tl.submit(_step_photo(2))
    await tl.drain()

    assert [f[1] for f in tl.sinks.files] == ["https://cdn.example.com/1.jpg"]
    states = {i.report_id: i.drop_reason for i in await tl.items()}
    assert states["browser:job-1:progress:2"] is DropReason.NOT_WATCHING


async def test_b19_a_handoff_while_the_user_is_away_is_timely_and_goes_to_the_dm_that_asked(
    tl: OutboxTimeline,
) -> None:
    handoff = _browser_notice(
        "browser:job-1:handoff:h1",
        NoticeOutcome.NEEDS_YOU,
        subject_id="job-1:handoff:h1",
        facts=["Sign in to finish.", "Open the live browser: https://live.example.com/x"],
        valid_until=T0 + timedelta(minutes=10),
    )
    await tl.submit(handoff)
    await tl.drain()

    [message] = await tl.ledger()
    assert (message.max_class, message.destination_basis) == (UrgencyClass.TIMELY, "owner_chat")
    assert [source for source, _ in tl.sinks.bot] == ["telegram"]
    assert tl.sinks.bot_ttls == [OUTBOUND_TTL_SECONDS_DEFAULT]
    assert "Open the live browser" in json.dumps(tl.compose.context)


async def test_b19_a_handoff_that_expires_before_it_can_be_told_is_recorded_not_sent(
    tl: OutboxTimeline,
) -> None:
    handoff = _browser_notice(
        "browser:job-1:handoff:h1",
        NoticeOutcome.NEEDS_YOU,
        subject_id="job-1:handoff:h1",
        valid_until=T0 + timedelta(minutes=10),
    )
    await tl.submit(handoff)
    await tl.at(11)
    await tl.drain()

    [item] = await tl.items()
    assert (item.state, item.drop_reason) == (ItemState.DROPPED, DropReason.EXPIRED)
    assert await tl.ledger() == []
    assert tl.compose.calls == []


async def test_h1_an_unsolicited_notice_for_a_user_active_in_a_group_never_goes_into_the_group(
    tl: OutboxTimeline,
) -> None:
    tl.world.conversations["tg-group"] = "telegram"
    tl.world.sessions["tg-group"] = ("telegram", "tg-1", "group-chat-9")
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_reminder(owner="tg-group", initiative=Initiative.SELF_INITIATED))
    await tl.drain()

    assert tl.sinks.bot_destinations == ["tg-1"]
    assert "tg-group" not in tl.world.saved
    assert "tg-group" not in {thread for thread, _, _ in tl.graph.writes}
    [message] = await tl.ledger()
    assert message.conversation_id == "tg-dm"


async def test_h2_a_browser_run_asked_for_in_a_group_shows_its_steps_and_handoff_only_in_the_dm(
    tl: OutboxTimeline,
) -> None:
    tl.world.conversations["tg-group"] = "telegram"
    tl.world.sessions["tg-group"] = ("telegram", "tg-1", "group-chat-9")
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_step_photo(1, owner="tg-group"))
    await tl.submit(
        _browser_notice(
            "browser:job-1:handoff:h1",
            NoticeOutcome.NEEDS_YOU,
            owner="tg-group",
            subject_id="job-1:handoff:h1",
            facts=["Open the live browser: https://live.example.com/x"],
            minutes=1,
        )
    )
    await tl.drain()

    assert tl.sinks.bot_destinations == ["tg-1"]
    assert tl.sinks.files == [("telegram", "https://cdn.example.com/1.jpg", "Step 1")]
    assert {m.conversation_id for m in await tl.ledger()} == {"tg-dm"}
    assert "tg-group" not in tl.world.saved
    assert tl.sinks.ws == []


def _artifact(path: str = "out/report.pdf", **overrides: object) -> NoticeReport:
    fields: dict[str, object] = {
        "report_id": f"artifact:tg-dm:{path}:1.0",
        "recipient": USER,
        "producer": ProducerKind.ARTIFACT,
        "subject": Subject(
            kind=SubjectKind.ASK,
            id=f"tg-dm:artifact:{path}",
            owner_conversation_id="tg-dm",
            label=path,
        ),
        "occurred_at": T0,
        "initiative": Initiative.ASKED,
        "outcome": NoticeOutcome.INFO,
        "artifacts": [
            OutboundAttachment(conversation_id="tg-dm", path=path, filename=path.rsplit("/", 1)[-1])
        ],
    }
    return NoticeReport.model_validate({**fields, **overrides})


async def test_a_file_the_agent_writes_reaches_the_bot_user_by_reference_with_no_words(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.TELEGRAM)
    await tl.submit(_artifact())
    await tl.drain()

    assert tl.sinks.files == [("telegram", "out/report.pdf", None)]
    assert (tl.sinks.bot, tl.compose.calls, tl.graph.writes) == ([], [], [])
    [message] = await tl.ledger()
    assert (message.state, message.parts) == (MessageState.SENT, [])


async def test_a_file_a_chat_app_refuses_fails_the_item_loudly(tl: OutboxTimeline) -> None:
    await tl.active_on(ConversationSource.TELEGRAM)

    async def refuse(*_: object, **__: object) -> bool:
        return False

    with patch(f"{DELIVER}.publish_outbound_file", refuse):
        await tl.submit(_artifact())
        await tl.drain()

    [item] = await tl.items()
    assert item.state is ItemState.FAILED


async def _link_discord(tl: OutboxTimeline, first_contact: list[str] | None = None) -> None:
    """Complete a discord link for the user, who is on the web, with the outbox real and only the link write doubled."""
    tl.world.link("discord", "dc-1")
    tl.world.dm("discord", "dc-dm")
    await tl.active_on(ConversationSource.WEB)
    link = PlatformLinkResult(
        status="linked",
        platform="discord",
        platform_user_id="dc-1",
        connected_at="2026-11-10T09:00:00Z",
        is_new_link=True,
    )
    with (
        patch.object(PlatformLinkService, "link_account", AsyncMock(return_value=link)),
        patch("app.services.platform_link_completion.schedule_account_sync"),
        patch("app.services.platform_link_completion.capture"),
        patch(
            "app.services.platform_link_completion.complete_onboarding_on_platform_link",
            AsyncMock(),
        ),
    ):
        await complete_platform_link(USER, "discord", "dc-1", first_contact=first_contact)
    await tl.drain()


async def test_i1_a_first_contact_after_linking_is_the_prerendered_bubbles_in_the_linked_dm(
    tl: OutboxTimeline,
) -> None:
    bubbles = ["Hey Aryan, I'm with you on Discord now.", "Tell me one thing off your plate."]
    await _link_discord(tl, bubbles)

    assert tl.sinks.bot == [("discord", bubbles)]
    assert tl.sinks.bot_destinations == ["dc-1"]
    assert tl.sinks.bot_ttls == [OUTBOUND_TTL_SECONDS_GREETING]
    assert tl.compose.calls == []
    [message] = await tl.ledger()
    assert message.destination_basis == "requested_channel"
    assert message.conversation_id == "dc-dm"
    assert [i.state for i in await tl.items()] == [ItemState.SENT]
    assert tl.world.saved["dc-dm"] == bubbles


async def test_i1_a_new_link_without_a_first_contact_is_the_connected_confirmation(
    tl: OutboxTimeline,
) -> None:
    await _link_discord(tl)

    [(platform, [text])] = tl.sinks.bot
    assert platform == "discord"
    assert "Your Discord account is linked." in text
    assert tl.compose.calls == []
    assert tl.sinks.ws == []


async def _park_queued(tl: OutboxTimeline, report: NoticeReport | RunReport) -> None:
    """Leave a report queued but untold, as a flusher that has not run yet would."""
    from app.db.repositories.outbox_items import outbox_items_repository
    from app.services.outbox.policy import decide

    stored = await outbox_items_repository.insert_if_new(
        report, expires_at=tl.clock.now() + timedelta(days=1)
    )
    assert stored.created
    decision = decide(report, None)
    await outbox_items_repository.queue(
        USER, report.report_id, urgency=decision.urgency, mode=decision.mode
    )


# ---------------------------------------------------------------------------
# Executor, workflow and tracked-todo results, reported by the real run builders
# ---------------------------------------------------------------------------


def _executor_run(
    owner: str = "web-1", *, task_id: str = "task-1", stream_id: str = "s1", **fields: Any
) -> ExecutorRun:
    return ExecutorRun(
        stream_id=stream_id,
        conversation_id=owner,
        user=AuthenticatedUser(user_id=USER),
        kind=RunKind.LIVE,
        task_id=task_id,
        user_message_id=None,
        request_excerpt="send priya the invoice",
        **fields,
    )


def _workflow_run(
    owner: str = "wf-chat", *, stream_id: str = "w1", notify: bool = True
) -> ExecutorRun:
    return _executor_run(
        owner,
        task_id=None,
        stream_id=stream_id,
        workflow_id="wf-1",
        workflow_title="Morning briefing",
        workflow_execution_id="exec-1",
        workflow_notify_on_completion=notify,
    )


def _filed(outcome: OutcomeState, *, result: str = "Invoice 42 went to Priya.", **fields: Any):
    return OutcomeReview(
        outcome,
        None,
        FinishTaskArgs(
            result=result,
            outcome=outcome,
            facts=[ReportFact(text="Sent the invoice", kind=FactKind.DID, source_call_ids=["c1"])],
            **fields,
        ),
    )


async def _report(tl: OutboxTimeline, run: ExecutorRun, outcome: RunOutcome) -> RunReport:
    report = run_report(run, outcome)
    await tl.submit(report)
    await tl.drain()
    return report


def _told(tl: OutboxTimeline) -> dict[str, Any]:
    """Return the one item the composer was shown last, as the model saw it."""
    [item] = tl.compose.context["items"]
    return item


async def test_a1_a_quick_task_on_web_is_one_message_in_the_conversation_it_was_asked_in(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.WEB)

    await _report(tl, _executor_run("web-1"), finished_outcome(_filed(OutcomeState.DONE), "x"))

    [message] = await tl.ledger()
    assert (message.destination, message.destination_basis) == ("in_app", "active_in_app")
    assert (message.conversation_id, message.recorded_in) == ("web-1", ["web-1"])
    assert (message.mode.value, message.max_class) == ("answer", UrgencyClass.ROUTINE)
    assert [c for c, _ in tl.sinks.ws] == ["web-1"] and tl.sinks.bot == []
    assert _told(tl)["result"] == "Invoice 42 went to Priya."
    assert _told(tl)["subject"] == "send priya the invoice"


async def test_a2_the_same_on_whatsapp_is_one_message_in_that_chat(tl: OutboxTimeline) -> None:
    await tl.active_on(ConversationSource.WHATSAPP)

    await _report(tl, _executor_run("wa-dm"), finished_outcome(_filed(OutcomeState.DONE), "x"))

    [message] = await tl.ledger()
    assert (message.destination, message.recorded_in) == ("chat_app", ["wa-dm"])
    assert [source for source, _ in tl.sinks.bot] == ["whatsapp"] and tl.sinks.ws == []


async def test_a8_an_executor_that_files_no_report_is_unverified_never_done(
    tl: OutboxTimeline,
) -> None:
    problem = "the run ended without a finish_task report that declares an outcome"
    await tl.active_on(ConversationSource.WEB)

    await _report(
        tl, _executor_run(), finished_outcome(OutcomeReview(None, problem), "I think it worked")
    )

    told = _told(tl)
    assert told["report"]["outcome"] == "unverified"
    assert told["review_problem"] == problem
    assert told["how_to_say"] == OUTCOME_REPLY_SHAPES[OutcomeState.UNVERIFIED]
    assert told["must_say"] is True
    [message] = await tl.ledger()
    assert message.max_class is UrgencyClass.TIMELY


async def test_a9_a_sent_email_with_no_write_behind_it_is_unverified(tl: OutboxTimeline) -> None:
    problem = "done was declared but no work call succeeded"
    review = OutcomeReview(OutcomeState.DONE, problem, _filed(OutcomeState.DONE).report)
    await tl.active_on(ConversationSource.WEB)

    await _report(tl, _executor_run(), finished_outcome(review, "x"))

    told = _told(tl)
    assert (told["report"]["outcome"], told["review_problem"]) == ("unverified", problem)
    assert told["report"]["facts"][0]["text"] == "Sent the invoice"


async def test_a10_a_conditional_task_with_nothing_to_do_is_still_told_to_the_user_who_asked(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.WEB)
    review = _filed(OutcomeState.NO_ACTION_NEEDED, result="Nothing urgent in your inbox.")

    await _report(tl, _executor_run(), finished_outcome(review, "x"))

    assert _told(tl)["must_say"] is True
    assert _told(tl)["how_to_say"] == OUTCOME_REPLY_SHAPES[OutcomeState.NO_ACTION_NEEDED]
    [message] = await tl.ledger()
    assert message.state is MessageState.SENT


async def test_a11_two_of_three_emails_sent_is_partial_and_timely(tl: OutboxTimeline) -> None:
    await tl.active_on(ConversationSource.WEB)
    review = _filed(OutcomeState.PARTIAL)
    partial = review.report.model_copy(
        update={
            "facts": [
                *review.report.facts,
                ReportFact(text="The email to Sam bounced", kind=FactKind.NOT_DONE),
            ]
        }
    )

    await _report(
        tl,
        _executor_run(),
        finished_outcome(OutcomeReview(OutcomeState.PARTIAL, None, partial), "x"),
    )

    assert [f["kind"] for f in _told(tl)["report"]["facts"]] == ["did", "not_done"]
    [message] = await tl.ledger()
    assert message.max_class is UrgencyClass.TIMELY


async def test_a_failed_run_is_told_with_its_reason_and_never_its_raw_error(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.WEB)

    await _report(tl, _executor_run(), failed_outcome("RuntimeError"))

    told = _told(tl)
    assert told["report"]["failure"] == {"reason": "crash", "recovery": "user_can_rerun"}
    assert told["result"] == ""
    assert "RuntimeError" not in json.dumps(tl.compose.context)


async def test_a13_tell_me_on_slack_when_done_asked_on_web_alerts_slack_only(
    tl: OutboxTimeline,
) -> None:
    tl.world.link("slack", "sl-1")
    tl.world.dm("slack", "sl-dm")
    await tl.active_on(ConversationSource.WEB)
    run = _executor_run(delivery_policy=DeliveryPolicy(channel=ConversationSource.SLACK))

    await _report(tl, run, finished_outcome(_filed(OutcomeState.DONE), "x"))

    [message] = await tl.ledger()
    assert (message.destination, message.destination_basis) == ("chat_app", "requested_channel")
    assert (message.conversation_id, message.recorded_in) == ("sl-dm", ["sl-dm", "web-1"])
    assert [source for source, _ in tl.sinks.bot] == ["slack"]
    assert tl.sinks.ws == []
    assert tl.world.unread == {"web-1"}
    assert "requested_channel_unavailable" not in tl.compose.context


async def test_a13_a_requested_chat_app_the_user_has_not_linked_is_said_so_and_the_user_is_told_where_they_are(
    tl: OutboxTimeline,
) -> None:
    await tl.active_on(ConversationSource.WEB)
    run = _executor_run(delivery_policy=DeliveryPolicy(channel=ConversationSource.DISCORD))

    await _report(tl, run, finished_outcome(_filed(OutcomeState.DONE), "x"))

    [message] = await tl.ledger()
    assert (message.destination, message.destination_basis) == ("in_app", "active_in_app")
    assert tl.compose.context["requested_channel_unavailable"] == "discord"


async def test_a_requested_chat_app_the_user_switched_off_is_not_used(tl: OutboxTimeline) -> None:
    tl.world.notification_channel_prefs = {"whatsapp": False}
    await tl.active_on(ConversationSource.WEB)
    run = _executor_run(delivery_policy=DeliveryPolicy(channel=ConversationSource.WHATSAPP))

    await _report(tl, run, finished_outcome(_filed(OutcomeState.DONE), "x"))

    assert tl.sinks.bot == []
    assert tl.compose.context["requested_channel_unavailable"] == "whatsapp"


async def test_b1_a_workflow_result_is_the_users_own_schedule_told_whole_where_they_are(
    tl: OutboxTimeline,
) -> None:
    tl.world.app_chat("wf-chat")
    await tl.active_on(ConversationSource.TELEGRAM)
    briefing = "Needs you\n- Priya: pitch deck, by Fri"

    await _report(
        tl,
        _workflow_run(),
        finished_outcome(_filed(OutcomeState.DONE, result=briefing), "x"),
    )

    [message] = await tl.ledger()
    assert (message.conversation_id, message.recorded_in) == ("tg-dm", ["tg-dm", "wf-chat"])
    assert tl.world.unread == {"wf-chat"}
    assert (_told(tl)["result"], _told(tl)["must_say"]) == (briefing, True)
    assert (message.mode.value, tl.sinks.analytics[0].producer) == ("answer", "workflow")


async def test_b15_a_morning_briefing_is_one_message_with_everything_in_it(
    tl: OutboxTimeline,
) -> None:
    tl.world.app_chat("wf-chat")
    tl.clock.current = T0.replace(hour=8)
    briefing = "Today: standup 9:30; dentist 3pm; invoice 42 due Friday."

    await _report(
        tl, _workflow_run(), finished_outcome(_filed(OutcomeState.DONE, result=briefing), "x")
    )

    assert len(await tl.ledger()) == 1
    assert _told(tl)["result"] == briefing


async def test_b16_a_run_reported_twice_is_one_message(tl: OutboxTimeline) -> None:
    tl.world.linked.clear()
    run = _executor_run()
    outcome = finished_outcome(_filed(OutcomeState.DONE), "x")

    await _report(tl, run, outcome)
    await _report(tl, run, outcome)

    assert len(await tl.ledger()) == 1
    assert len(await tl.items()) == 1
    assert len(tl.compose.calls) == 1


async def test_b17_a_muted_workflow_that_succeeds_is_recorded_and_not_told(
    tl: OutboxTimeline,
) -> None:
    tl.world.app_chat("wf-chat")

    await _report(tl, _workflow_run(notify=False), finished_outcome(_filed(OutcomeState.DONE), "x"))

    [item] = await tl.items()
    assert (item.state, item.drop_reason) == (ItemState.DROPPED, DropReason.USER_MUTED)


async def test_the_judge_finding_an_update_moot_records_it_and_keeps_the_why(
    tl: OutboxTimeline,
) -> None:
    report = _run("run-1", OutcomeState.DONE, initiative=Initiative.ASKED)
    tl.judge.verdicts["run-1"] = verdict(
        relevance=Relevance.ALREADY_KNOWN,
        not_worth_probability=0.97,
        reason="the user said they paid it themselves",
    )

    await tl.submit(report)
    await tl.drain()

    [item] = await tl.items()
    assert (item.state, item.drop_reason) == (ItemState.DROPPED, DropReason.ALREADY_KNOWN)
    assert item.judgement is not None and item.judgement.verdict is not None
    assert item.judgement.verdict.reason == "the user said they paid it themselves"
    assert await tl.ledger() == []
    assert tl.sinks.bot == [] and tl.sinks.ws == []


async def test_b17_a_muted_workflow_that_needs_the_user_is_told(tl: OutboxTimeline) -> None:
    tl.world.app_chat("wf-chat")
    await tl.active_on(ConversationSource.TELEGRAM)
    needs = _filed(OutcomeState.NEEDS_YOU)
    needs_you = needs.report.model_copy(
        update={
            "needs_you": ReportNeedsYou(kind=NeedsYouKind.CHOOSE, ask="Which invoice?", options=[])
        }
    )

    await _report(
        tl,
        _workflow_run(notify=False),
        finished_outcome(OutcomeReview(OutcomeState.NEEDS_YOU, None, needs_you), "x"),
    )

    [message] = await tl.ledger()
    assert message.max_class is UrgencyClass.TIMELY
    assert [source for source, _ in tl.sinks.bot] == ["telegram"]
    assert _told(tl)["report"]["needs_you"]["ask"] == "Which invoice?"


class TestATrackedTodoRunsReportsThroughTheOutbox:
    """The todo producer runs for real: its own attempts, its report, then the outbox."""

    TODO_ID = "6ab51f1ba7a1fcf0f00ab49a"

    def _todo(self) -> TodoDocument:
        return TodoDocument(
            id=self.TODO_ID,
            user_id=USER,
            title="Watch the staging deploy",
            recurrence="every_1h",
            labels=["gaia-tracked"],
        )

    async def _attempt(self, run_id: str, outcome: RunOutcome, result_type: str) -> None:
        run = ExecutorRun(
            stream_id=run_id,
            conversation_id="todo-chat",
            user=AuthenticatedUser(user_id=USER),
            kind=RunKind.LIVE,
            task_id=f"task-{run_id}",
            user_message_id=None,
        )
        repo = MagicMock(get_by_id=AsyncMock(return_value=self._todo()))
        with (
            patch.object(trd, "todo_repository", repo),
            patch.object(trd, "record_run_finished", AsyncMock()),
            patch.object(trd, "record_executor_report", AsyncMock()),
        ):
            await deliver_todo_run_result(
                run,
                TodoRun(
                    todo_id=self.TODO_ID, trigger_type=TriggerType.SCHEDULED_TODO, runs_once=True
                ),
                outcome,
                outcome.result,
                result_type,
            )

    def _done(self, result: str) -> RunOutcome:
        return finished_outcome(_filed(OutcomeState.DONE, result=result), result)

    async def test_b21_an_attempt_that_fails_and_is_retried_tells_the_user_only_the_success(
        self, tl: OutboxTimeline
    ) -> None:
        await tl.active_on(ConversationSource.TELEGRAM)

        await self._attempt("run-1", failed_outcome("RuntimeError"), "error")
        await tl.drain()
        assert tl.arq.jobs == {} and await tl.items() == []

        await self._attempt("run-2", self._done("Deploy is green."), "final")
        await tl.drain()

        [message] = await tl.ledger()
        assert message.report_ids == [f"todo:{self.TODO_ID}:run-2"]
        assert _told(tl)["report"]["outcome"] == "done"

    async def test_b4_a_check_with_nothing_new_is_recorded_and_never_alerted(
        self, tl: OutboxTimeline
    ) -> None:
        nothing = finished_outcome(
            _filed(
                OutcomeState.NOTHING_NEW, scope=ReportScope(covered="inbox", complete=True, gaps=[])
            ),
            "x",
        )

        await self._attempt("run-1", nothing, "final")
        await tl.drain()

        [item] = await tl.items()
        assert (item.state, item.drop_reason) == (ItemState.DROPPED, DropReason.NOTHING_NEW)
        assert await tl.ledger() == []

    async def test_what_earlier_runs_of_one_todo_were_told_comes_from_the_ledger(
        self, tl: OutboxTimeline
    ) -> None:
        await tl.active_on(ConversationSource.TELEGRAM)
        nothing = finished_outcome(
            _filed(
                OutcomeState.NOTHING_NEW, scope=ReportScope(covered="inbox", complete=True, gaps=[])
            ),
            "x",
        )
        await tl.at(0)
        await self._attempt("run-1", self._done("Deploy failed on migration 42."), "final")
        await tl.drain()
        await tl.at(60)
        await self._attempt("run-2", nothing, "final")
        await tl.drain()

        await tl.at(120)
        await self._attempt("run-3", self._done("Deploy is green."), "final")
        await tl.drain()

        earlier = tl.compose.context["earlier_runs"][f"todo:{self.TODO_ID}:run-3"]
        assert [line.split(": ", 1)[1] for line in earlier] == [
            "told them: Watch the staging deploy: said",
            "kept quiet (nothing_new)",
        ]


async def test_a_requested_chat_app_outranks_the_dm_the_answer_would_go_back_to(
    tl: OutboxTimeline,
) -> None:
    tl.world.link("slack", "sl-1")
    tl.world.dm("slack", "sl-dm")
    run = _executor_run("wa-dm", delivery_policy=DeliveryPolicy(channel=ConversationSource.SLACK))

    await _report(tl, run, finished_outcome(_filed(OutcomeState.DONE), "x"))

    [message] = await tl.ledger()
    assert (message.destination_basis, message.conversation_id) == ("requested_channel", "sl-dm")
    assert [source for source, _ in tl.sinks.bot] == ["slack"]


async def test_a_judged_update_is_told_and_its_verdict_is_on_the_item(tl: OutboxTimeline) -> None:
    tl.judge.verdicts["rem:r1:1"] = verdict(
        urgency=UrgencyClass.INTERRUPT, sensitivity=Sensitivity.FINANCE
    )

    await tl.submit(_reminder())
    await tl.drain()

    [item] = await tl.items()
    assert item.state is ItemState.SENT
    assert item.judgement is not None
    assert (item.judgement.sensitivity, item.judgement.judge_unavailable) == (
        Sensitivity.FINANCE,
        False,
    )
    assert len(await tl.ledger()) == 1


async def test_when_the_judge_is_unavailable_the_reminder_is_still_told_and_tagged(
    tl: OutboxTimeline,
) -> None:
    tl.judge.verdicts["rem:r1:1"] = None

    await tl.submit(_reminder())
    await tl.drain()

    [item] = await tl.items()
    assert item.state is ItemState.SENT and item.urgency is UrgencyClass.INTERRUPT
    assert item.judgement is not None and item.judgement.judge_unavailable is True
    assert len(await tl.ledger()) == 1
