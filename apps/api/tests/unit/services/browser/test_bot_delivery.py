"""Regression: bot step updates were unbounded, one per step.

A real shopping task runs 20+ steps, so the bot sent ~20 photos into the
conversation the user also reads replies in. The live-view link (sent up front)
and the recap (sent at the end) already carry the visuals, so the per-step
stream only needs to show that work is happening.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.chat_models import ConversationSource
from app.schemas.browser import BrowserStepSnapshot
from app.services.browser import bot_delivery as delivery_mod
from app.services.browser.bot_delivery import _MAX_STEP_UPDATES, BotProgressDelivery


def _step(index: int) -> BrowserStepSnapshot:
    return BrowserStepSnapshot(
        index=index,
        goal=f"Doing step {index}",
        url="https://example.com/search",
        screenshot=f"https://cdn.example.com/step_{index}.png",
    )


@pytest.fixture
def photo(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(delivery_mod, "publish_outbound_photo", sender)
    monkeypatch.setattr(delivery_mod, "publish_outbound_message", AsyncMock(return_value=True))
    return sender


def _delivery() -> BotProgressDelivery:
    return BotProgressDelivery(
        platform=ConversationSource.TELEGRAM,
        user_id="user-1",
        conversation_id="conv-1",
        stream_screenshots=True,
    )


@pytest.mark.unit
@pytest.mark.regression
async def test_step_updates_are_capped_on_a_long_task(photo: AsyncMock) -> None:
    bot = _delivery()

    for index in range(1, 21):
        await bot.step(_step(index))

    assert photo.await_count == _MAX_STEP_UPDATES


@pytest.mark.unit
async def test_short_task_still_sends_every_step(photo: AsyncMock) -> None:
    """The cap must not suppress progress on a task that fits well inside it."""
    bot = _delivery()

    for index in range(1, 4):
        await bot.step(_step(index))

    assert photo.await_count == 3
