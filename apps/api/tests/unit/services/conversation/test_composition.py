"""The production ports' process-wide pieces: the running steps, their drain, and turn analytics."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.runnables import RunnableBinding
import pytest

from app.constants.chat import ConversationSource
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import EntryUpdatedFrame
from app.models.conversation_log_models import LoggedEntry, Reaction, Reply
from app.models.jev_models import JevDecisionsResponse
from app.services.conversation import ack, composition
from app.services.conversation.comms_runner import CommsGraphRunner
from app.services.conversation.composition import (
    PostHogTurnAnalytics,
    RuntimeEffects,
    drain_conversation_steps,
    running_steps,
)
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.chat import ChatTurnReacted
from shared.py.analytics.context import AnalyticsContext, current_analytics_context
from tests.helpers import WideEventRecorder, captured_wide_event, reaction_answers
from tests.unit.services.conversation.log_helpers import EMPTY, logged, user

USER_ID = "6af8ad62a1e833e183aa7a4d"


PORTS = MagicMock()
advanced: list[tuple[object, ...]] = []


def _effects() -> RuntimeEffects:
    return RuntimeEffects(MagicMock(), MagicMock(), lambda: PORTS)


def _held_steps(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    release = asyncio.Event()
    advanced.clear()

    async def advance(*args: object) -> None:
        advanced.append(args)
        await release.wait()

    monkeypatch.setattr(composition, "advance", advance)
    return release


async def test_a_kick_runs_a_step_that_leaves_the_running_set_when_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _held_steps(monkeypatch)
    await _effects().kick("c1", USER_ID)
    (step,) = running_steps()
    await asyncio.sleep(0)
    assert (step.get_name(), advanced) == ("conversation_step", [(PORTS, "c1", USER_ID)])
    release.set()
    await step
    await asyncio.sleep(0)
    assert running_steps() == ()


async def test_a_drain_with_nothing_running_cuts_off_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(composition._steps, "draining", composition._steps.draining)
    assert await drain_conversation_steps(grace_seconds=0) == 0


async def test_a_step_still_running_past_the_grace_is_cut_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(composition._steps, "draining", composition._steps.draining)
    _held_steps(monkeypatch)
    await _effects().kick("c1", USER_ID)
    (step,) = running_steps()
    assert await drain_conversation_steps(grace_seconds=0.01) == 1
    await asyncio.sleep(0)
    assert step.cancelled()


async def test_a_drained_process_starts_no_step_and_waits_for_the_running_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(composition._steps, "draining", composition._steps.draining)
    release = _held_steps(monkeypatch)
    await _effects().kick("c1", USER_ID)
    (step,) = running_steps()
    asyncio.get_running_loop().call_later(0.01, release.set)
    assert await drain_conversation_steps(grace_seconds=5) == 0
    assert step.done()
    await _effects().kick("c2", USER_ID)
    assert running_steps() == ()


async def test_a_turn_event_is_captured_under_its_messages_context_and_dedupe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[object, ...]] = []

    def capture(*args: object) -> None:
        captured.append((*args, current_analytics_context()))

    monkeypatch.setattr(composition, "capture", capture)
    context = AnalyticsContext(
        attribution=Attribution(
            actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB
        )
    )
    dedupe = Dedupe(key="reacted:u1:x", occurred_at=datetime(2026, 11, 1, tzinfo=UTC))
    event = ChatTurnReacted(emoji="\U0001f44d")
    PostHogTurnAnalytics().capture(USER_ID, event, context, dedupe)
    assert captured == [(UserId(USER_ID), event, dedupe, context)]


async def test_a_drain_logs_how_many_steps_ran_and_how_many_it_cut_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(composition._steps, "draining", composition._steps.draining)
    _held_steps(monkeypatch)
    await _effects().kick("c1", USER_ID)
    async with captured_wide_event() as event:
        await drain_conversation_steps(grace_seconds=0.01)
    assert event["conversation_drain"] == {"running": 1, "cut_off": 1}


async def test_the_instant_reaction_lands_on_the_message_and_reaches_every_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    said = user("u1")
    earlier = Reply(id="o0", reply_id="r0", attempt_id="a0", text="How was the trip?")
    reacted = said.model_copy(update={"reaction": Reaction(emoji="\U0001f44d", by=ReactionBy.JEV)})
    log = MagicMock()
    log.state = AsyncMock(return_value=EMPTY.model_copy(update={"head": 2}))
    log.read_after = AsyncMock(return_value=[logged(1, earlier), logged(2, said)])
    log.react_once = AsyncMock(return_value=logged(2, reacted))
    frames = MagicMock(publish=AsyncMock())
    decide = AsyncMock(return_value=MagicMock(emoji="\U0001f44d"))
    monkeypatch.setattr(composition, "decide_reaction", decide)
    await RuntimeEffects(log, frames, lambda: PORTS)._react("c1", USER_ID, "u1")
    log.state.assert_awaited_once_with("c1", USER_ID)
    log.read_after.assert_awaited_once_with("c1", USER_ID, 0)
    decide.assert_awaited_once_with("text of u1", "How was the trip?", ConversationSource.WEB)
    log.react_once.assert_awaited_once_with(
        "c1", USER_ID, "u1", Reaction(emoji="\U0001f44d", by=ReactionBy.JEV)
    )
    frames.publish.assert_awaited_once_with("c1", EntryUpdatedFrame(seq=2, entry=reacted))


def _reacting_log(head: int, recent: list[LoggedEntry]) -> MagicMock:
    log = MagicMock()
    log.state = AsyncMock(return_value=EMPTY.model_copy(update={"head": head}))
    log.read_after = AsyncMock(return_value=recent)
    log.react_once = AsyncMock(return_value=None)
    return log


async def test_the_reaction_reads_only_the_entries_just_before_the_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _reacting_log(45, [logged(45, user("u1"))])
    monkeypatch.setattr(
        composition, "decide_reaction", AsyncMock(return_value=MagicMock(emoji=None))
    )
    await RuntimeEffects(log, MagicMock(), lambda: PORTS)._react("c1", USER_ID, "u1")
    log.read_after.assert_awaited_once_with("c1", USER_ID, 25)


async def test_the_reaction_reads_the_named_message_and_the_last_reply_before_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = Reply(id="o0", reply_id="r0", attempt_id="a0", text="How was the trip?")
    blank = Reply(id="o1", reply_id="r1", attempt_id="a1", text="")
    after = Reply(id="o2", reply_id="r2", attempt_id="a2", text="Glad to hear it")
    recent = [logged(1, before), logged(2, user("u0")), logged(3, blank)]
    recent += [logged(4, user("u1")), logged(5, after)]
    decide = AsyncMock(return_value=MagicMock(emoji=None))
    monkeypatch.setattr(composition, "decide_reaction", decide)
    log = _reacting_log(5, recent)
    await RuntimeEffects(log, MagicMock(), lambda: PORTS)._react("c1", USER_ID, "u1")
    decide.assert_awaited_once_with("text of u1", "How was the trip?", ConversationSource.WEB)
    log.react_once.assert_not_awaited()


async def test_a_message_that_opens_the_conversation_reacts_with_no_previous_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decide = AsyncMock(return_value=MagicMock(emoji=None))
    monkeypatch.setattr(composition, "decide_reaction", decide)
    log = _reacting_log(1, [logged(1, user("u1"))])
    await RuntimeEffects(log, MagicMock(), lambda: PORTS)._react("c1", USER_ID, "u1")
    decide.assert_awaited_once_with("text of u1", "", ConversationSource.WEB)


async def test_the_instant_reaction_emits_its_decision_and_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = JevDecisionsResponse.model_validate(reaction_answers(task=0.0, emoji="\U0001f44d"))
    monkeypatch.setattr(ack, "post_decisions", AsyncMock(return_value=answer))
    log = _reacting_log(1, [logged(1, user("u1"))])
    recorder = WideEventRecorder()
    with patch("shared.py.wide_events._loguru", recorder):
        before = asyncio.all_tasks()
        await RuntimeEffects(log, MagicMock(), lambda: PORTS).start_ack("c1", USER_ID, "u1")
        await asyncio.gather(*(asyncio.all_tasks() - before))
    log.state.assert_awaited_once_with("c1", USER_ID)
    event = recorder.event("conversation_instant_reaction")
    assert event["conversation_id"] == "c1"
    reaction = event["reaction_ack"]
    assert reaction["reason"] == "needs_words"
    assert isinstance(reaction["latency_ms"], int)


async def test_a_message_no_longer_in_the_recent_entries_gets_no_reaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decide = AsyncMock()
    monkeypatch.setattr(composition, "decide_reaction", decide)
    log = _reacting_log(1, [logged(1, user("u0"))])
    await RuntimeEffects(log, MagicMock(), lambda: PORTS)._react("c1", USER_ID, "u1")
    decide.assert_not_awaited()
    log.react_once.assert_not_awaited()


def test_a_fresh_self_host_boots_with_no_llm_and_folds_with_the_one_saved_later() -> None:
    """Regression: a fresh self-host saves its LLM key in setup, after the API booted."""
    with patch("app.agents.llm.client._get_available_providers", return_value={}):
        ports = composition.build_runtime_ports()
    saved_later = GenericFakeChatModel(messages=iter([]))
    assert isinstance(ports.runner, CommsGraphRunner)
    with patch.object(composition, "init_llm", return_value=saved_later):
        fold_model = ports.runner._fold().model
    assert isinstance(fold_model, RunnableBinding)
    assert fold_model.bound is saved_later
