"""The browser tasks a chat controls, as the turn answering the user's message reads and steers them.

Comms is the one reader of what the user says to a browser task: a frame
tells it what runs or waits (nodes/browser_task_status.py) and its tools act
on it (tools/browser_chat_tools.py). Every job here is found from the turn
itself, never from an id the model wrote.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.constants.browser import BROWSER_STOP_REPORTS, BrowserStopOutcome, HandoffStatus
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable
from app.schemas.browser_job import BrowserJobState
from app.services.browser.handoff import (
    get_handoff,
    get_pending_handoff_for_reply,
    reply_address,
)
from app.services.browser.job_stop import RequesterChat, requester_chat, running_chat_jobs
from app.services.browser.jobs import get_job_state
from shared.py.wide_events import log


@dataclass(frozen=True)
class ChatTurn:
    """The user's own message being answered, in the chat it arrived in."""

    conversation_id: str
    user_id: str
    source: ConversationSource | None

    @property
    def reply_address(self) -> str:
        """Where a reply to this user's paused step arrives (handoff.reply_address)."""
        return reply_address(self.conversation_id, self.user_id, self.source)

    @property
    def requester(self) -> RequesterChat | None:
        """The user's own bot chat, whose runs this chat also controls."""
        return requester_chat(self.user_id, self.source)


@dataclass(frozen=True)
class PausedStep:
    """A step the user's browser task is waiting for them to finish in the live view."""

    handoff_id: str
    job_id: str
    reason: str


@dataclass(frozen=True)
class ChatBrowserTasks:
    """The browser tasks this chat controls that have not ended, and the step one of them waits on."""

    running: list[BrowserJobState]
    paused: PausedStep | None


def user_message_turn(configurable: AgentConfigurable) -> ChatTurn | None:
    """Return the turn when it answers the user's own message; None for a narration or background run.

    A narration re-voices a result and a background run has nobody typing, so
    neither may read the user's word into their browser task.
    """
    conversation_id = configurable.get("thread_id")
    user_id = configurable.get("user_id")
    if (
        configurable.get("is_result_narration")
        or configurable.get("execution_mode") == "background"
        or not conversation_id
        or not user_id
    ):
        return None
    return ChatTurn(
        conversation_id=conversation_id,
        user_id=user_id,
        source=ConversationSource.coerce(configurable.get("conversation_source")),
    )


async def paused_step(turn: ChatTurn) -> PausedStep | None:
    """Return the user's step a reply in this chat answers; None when no task of theirs waits on one."""
    handoff_id = await get_pending_handoff_for_reply(turn.reply_address)
    if not handoff_id:
        return None
    record = await get_handoff(handoff_id)
    if record is None or record.status is not HandoffStatus.PENDING:
        return None
    if record.user_id != turn.user_id:
        log.warning(
            f"{LogTag.BROWSER} Paused step ignored: the handoff belongs to another user",
            browser={"handoff_id": handoff_id},
            user_id=turn.user_id,
        )
        return None
    return PausedStep(handoff_id=handoff_id, job_id=record.job_id, reason=record.reason)


async def chat_browser_tasks(turn: ChatTurn) -> ChatBrowserTasks:
    """Return the browser tasks this chat controls that have not ended, and the step one is paused on.

    The paused task joins them even when a newer run took its chat's latest
    slot: the user's bot chat is shared by the runs they start from any chat.
    """
    running = await running_chat_jobs(turn.conversation_id, turn.requester)
    paused = await paused_step(turn)
    if paused is not None and paused.job_id not in {job.job_id for job in running}:
        state = await get_job_state(paused.job_id)
        if state is not None:
            running.append(state)
    return ChatBrowserTasks(running=running, paused=paused)


def stop_report(outcomes: Iterable[BrowserStopOutcome]) -> str:
    """Say what stopping a chat's browser tasks came to: stopped when any stop won."""
    stopped = BrowserStopOutcome.STOPPED in set(outcomes)
    return BROWSER_STOP_REPORTS[
        BrowserStopOutcome.STOPPED if stopped else BrowserStopOutcome.ALREADY_ENDED
    ]
