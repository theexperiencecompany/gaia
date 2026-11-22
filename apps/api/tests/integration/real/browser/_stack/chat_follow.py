"""A woken bot conversation, read the way the bot's follower reads it: its events stream until idle.

The bot hears a conversation only through its follower (libs/shared/ts/src/bots/conversation):
a wake on the outbound queue names it, and the follower renders the server's screen items
to the chat. This follows the same stream, through the same wire models, and records what
the follower sends: each settled reply's bubbles and each notice in the chat, and a browser
run's session note, step photos, hand-off and recap in the requester's own chat. Approvals,
reactions, usage-limit lines and files are not recorded: no browser scenario reads them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import time
from typing import Annotated

import httpx
from pydantic import Field, TypeAdapter
from scripts.evals.core.live_chat import SSE_DATA_PREFIX

from app.constants.browser import BROWSER_TASK_EVENT
from app.models.conversation_frame_models import StateFrame
from app.models.conversation_log_models import DisplayState
from app.models.conversation_screen_models import (
    NoticeItem,
    ScreenFrame,
    ScreenInsertFrame,
    ScreenItem,
    ScreenUpdateFrame,
    WorkItem,
)
from app.models.conversation_send_models import ActiveBotConversation, ConversationEvent
from app.schemas.browser import (
    BrowserCardSnapshot,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from shared.py.conversation_wire import ReplyItem
from tests.integration.real.browser._stack.transcript import Delivery

#: How long opening the events stream may take; reading it is bounded by the scenario.
_STREAM_CONNECT_SECONDS = 30.0
#: The bot's lines for a browser run, worded as browser-progress.ts words them.
_LIVE_LINK_LINE = "Open the live browser: {url}"
_RECAP_LINE = "📽 Here's a recap of the run: {url}"
_BLANK_TAB_PREFIX = "about:"
_NEW_TAB_URL = "chrome://newtab/"
_BROWSER_CARD: TypeAdapter[BrowserCardSnapshot] = TypeAdapter(
    Annotated[BrowserCardSnapshot, Field(discriminator="kind")]
)

#: The headers the bot sends as one platform user.
BotHeaders = Callable[[str], dict[str, str]]


def _is_blank_tab(url: str | None) -> bool:
    return not url or url.startswith(_BLANK_TAB_PREFIX) or url == _NEW_TAB_URL


def _step_caption(shown: int, goal: str) -> str:
    label = goal.strip().removesuffix(".")
    return f"Step {shown} · {label}" if label else f"Step {shown}"


def _browser_cards(item: WorkItem) -> list[BrowserCardSnapshot]:
    return [
        _BROWSER_CARD.validate_python(card["data"])
        for card in item.tool_data
        if card["tool_name"] == BROWSER_TASK_EVENT
    ]


@dataclass
class _BrowserRun:
    """One run's progress in the chat: how many of its cards were shown, and the last step's frame."""

    seen: int = 0
    steps_shown: int = 0
    last_frame: str | None = None


@dataclass
class ChatFollow:
    """One conversation as the bot renders it, kept across follows so each item is sent once."""

    conversation: ActiveBotConversation
    send: Callable[[Delivery], None]
    #: Messages posted into the conversation: a follow stays until each is answered.
    expected: set[int] = field(default_factory=set)
    _replies: set[str] = field(default_factory=set)
    _notices: set[str] = field(default_factory=set)
    _runs: dict[str, _BrowserRun] = field(default_factory=dict)

    async def follow(self, api_url: str, headers: BotHeaders) -> None:
        """Read the events stream from the conversation's cursor until it is idle with every message answered."""
        conversation = self.conversation
        opened = False
        async with (
            httpx.AsyncClient(
                base_url=api_url,
                headers=headers(conversation.platform_user_id),
                timeout=httpx.Timeout(_STREAM_CONNECT_SECONDS, read=None),
            ) as client,
            client.stream(
                "GET",
                f"/api/v1/conversations/{conversation.conversation_id}/events",
                params={"after": str(conversation.after_seq)},
            ) as response,
        ):
            if response.status_code != 200:
                await response.aread()
                raise AssertionError(
                    f"events of {conversation.conversation_id} answered "
                    f"{response.status_code}: {response.text[:300]}"
                )
            async for line in response.aiter_lines():
                if not line.startswith(SSE_DATA_PREFIX):
                    continue
                match ConversationEvent.model_validate_json(
                    line.removeprefix(SSE_DATA_PREFIX)
                ).frame:
                    case ScreenFrame(items=items):
                        self._render(items if opened else self._opening(items))
                        opened = True
                    case ScreenInsertFrame(item=item) | ScreenUpdateFrame(item=item):
                        self._render([item])
                    case StateFrame() as state if opened and self._finished(state):
                        return
                    case _:
                        pass
        raise AssertionError(
            f"the events of {conversation.conversation_id} closed before it was idle"
        )

    def _finished(self, state: StateFrame) -> bool:
        return state.display is DisplayState.IDLE and all(
            seq <= state.head for seq in self.expected
        )

    def _opening(self, items: Iterable[ScreenItem]) -> list[ScreenItem]:
        """Take the items at or below the cursor as delivered before; return the rest."""
        floor = self.conversation.after_seq
        fresh: list[ScreenItem] = []
        for item in items:
            if item.seq > floor:
                fresh.append(item)
                continue
            match item:
                case ReplyItem(outcome=outcome) if outcome is not None:
                    self._replies.add(item.id)
                case NoticeItem():
                    self._notices.add(item.id)
                case WorkItem():
                    self._run(item.id).seen = len(_browser_cards(item))
                case _:
                    pass
        return fresh

    def _render(self, items: Iterable[ScreenItem]) -> None:
        for item in items:
            match item:
                case ReplyItem(outcome=outcome) if (
                    outcome is not None and item.id not in self._replies
                ):
                    self._replies.add(item.id)
                    self._tell(self._chat, [*item.bubbles, item.failure_line or ""])
                case NoticeItem() if item.id not in self._notices:
                    self._notices.add(item.id)
                    self._tell(self._chat, item.bubbles)
                case WorkItem():
                    self._render_run(item)
                case _:
                    pass

    @property
    def _chat(self) -> tuple[str, bool]:
        channel = self.conversation.channel_id
        return (
            (channel, True) if channel is not None else (self.conversation.platform_user_id, False)
        )

    @property
    def _requester(self) -> tuple[str, bool]:
        """A run's progress goes to the requester's own chat, even for a run asked in a group."""
        return (self.conversation.platform_user_id, False)

    def _run(self, item_id: str) -> _BrowserRun:
        return self._runs.setdefault(item_id, _BrowserRun())

    def _render_run(self, item: WorkItem) -> None:
        run = self._run(item.id)
        cards = _browser_cards(item)
        fresh, run.seen = cards[run.seen :], len(cards)
        for card in fresh:
            match card:
                case BrowserSessionSnapshot(detail=detail) if detail:
                    self._tell(self._requester, [detail])
                case BrowserStepSnapshot():
                    self._render_step(run, card)
                case BrowserHandoffSnapshot(status="pending", live_view_url=live_view_url):
                    # The user may change the page in the live view: the next step shows whatever it looks like.
                    run.last_frame = None
                    link = [_LIVE_LINK_LINE.format(url=live_view_url)] if live_view_url else []
                    self._tell(self._requester, [card.reason, *link])
                case BrowserResultSnapshot(replay_url=replay_url) if replay_url:
                    self._tell(self._requester, [_RECAP_LINE.format(url=replay_url)])
                case _:
                    pass

    def _render_step(self, run: _BrowserRun, step: BrowserStepSnapshot) -> None:
        if _is_blank_tab(step.url):
            if step.goal.strip():
                run.steps_shown += 1
                self._tell(self._requester, [_step_caption(run.steps_shown, step.goal)])
            return
        frame = f"{step.url} {step.frame_digest}" if step.frame_digest else None
        if frame is not None and frame == run.last_frame:
            return
        run.last_frame = frame
        run.steps_shown += 1
        caption = _step_caption(run.steps_shown, step.goal)
        if not step.screenshot:
            self._tell(self._requester, [caption])
            return
        destination, is_channel = self._requester
        self.send(Delivery(destination, is_channel, "", step.screenshot, caption, time.monotonic()))

    def _tell(self, to: tuple[str, bool], lines: Iterable[str]) -> None:
        destination, is_channel = to
        for line in lines:
            if line:
                self.send(Delivery(destination, is_channel, line, None, None, time.monotonic()))
