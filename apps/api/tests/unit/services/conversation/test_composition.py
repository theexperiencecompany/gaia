"""The production ports' process-wide pieces: the running steps, their drain, and turn analytics."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.services.conversation import composition
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
