"""The <browser_task> frame: comms learns each turn what the chat's browser task is doing, and only on the user's turns."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage
import pytest

from app.agents.context.slots import BROWSER_TASK_MARKER, PromptSlot, slot_of
from app.agents.core.nodes import browser_task_status
from app.agents.core.nodes.browser_task_status import browser_task_status_hook
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.schemas.browser import NewHandoff
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser.handoff import bot_chat_address, create_pending_handoff
from app.services.browser.jobs import put_job_state, set_latest_job

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

USER = "user-1"
CONVERSATION = "conv-1"


def _config(**extra: Any) -> dict[str, Any]:
    return {"configurable": {"thread_id": CONVERSATION, "user_id": USER, **extra}}


async def _running(
    job_id: str, task: str, status: BrowserJobStatus = BrowserJobStatus.RUNNING
) -> None:
    await set_latest_job(CONVERSATION, job_id)
    await put_job_state(BrowserJobState(job_id=job_id, status=status, task=task))


async def _frame(config: dict[str, Any]) -> list[Any]:
    state = {"messages": [HumanMessage(content="done")]}
    out = await browser_task_status_hook(state, config, MagicMock())
    return out["messages"][len(state["messages"]) :]


async def test_a_running_task_is_framed_in_its_own_slot() -> None:
    await _running("job-1", "book a table for two")

    [frame] = await _frame(_config())

    assert frame.additional_kwargs.get(BROWSER_TASK_MARKER) is True
    assert slot_of(frame) is PromptSlot.BROWSER_TASK
    assert frame.content == "<browser_task>\nRunning. Task: book a table for two\n</browser_task>\n"


async def test_a_state_with_no_messages_still_gets_the_frame() -> None:
    await _running("job-1", "book a table for two")

    out = await browser_task_status_hook({}, _config(), MagicMock())

    assert [slot_of(message) for message in out["messages"]] == [PromptSlot.BROWSER_TASK]


async def test_a_failed_read_leaves_the_turn_as_it_was_and_says_why() -> None:
    state = {"messages": [HumanMessage(content="done")]}
    with (
        patch.object(browser_task_status, "log") as log,
        patch.object(
            browser_task_status,
            "chat_browser_tasks",
            AsyncMock(side_effect=ConnectionError("redis down")),
        ),
    ):
        out = await browser_task_status_hook(state, _config(), MagicMock())

    assert out is state
    log.error.assert_called_once_with(
        f"{LogTag.AGENT} browser_task_status_hook failed", error_type="ConnectionError"
    )


async def test_a_paused_task_says_what_it_waits_on() -> None:
    await _running("job-1", "book a table for two")
    await create_pending_handoff(
        "h1",
        NewHandoff(
            job_id="job-1",
            user_id=USER,
            conversation_id=CONVERSATION,
            reason="Sign in to opentable.com",
            reply_to=CONVERSATION,
        ),
    )

    [frame] = await _frame(_config())

    assert "Paused" in frame.content
    assert "Sign in to opentable.com" in frame.content
    assert "Running" not in frame.content


async def test_an_ended_task_leaves_no_frame() -> None:
    await _running("job-1", "book a table for two", BrowserJobStatus.DONE)

    assert await _frame(_config()) == []


@pytest.mark.parametrize(
    "extra",
    [{"is_result_narration": True}, {"execution_mode": "background"}],
    ids=["narration", "background"],
)
async def test_a_turn_with_no_user_message_gets_no_frame(extra: dict[str, Any]) -> None:
    await _running("job-1", "book a table for two")

    assert await _frame(_config(**extra)) == []


async def test_a_paused_run_a_newer_run_displaced_from_the_bot_chat_is_still_framed() -> None:
    """The user's bot chat is shared by the runs they start from any chat; the newer one takes its latest key."""
    dm = bot_chat_address(ConversationSource.TELEGRAM, USER)
    for job_id, task in (("job-old", "book a table"), ("job-new", "buy a lamp")):
        await set_latest_job(dm, job_id)
        await put_job_state(
            BrowserJobState(job_id=job_id, status=BrowserJobStatus.RUNNING, task=task)
        )
    await create_pending_handoff(
        "h-old",
        NewHandoff(
            job_id="job-old",
            user_id=USER,
            conversation_id="conv-group",
            reason="Sign in to opentable.com",
            reply_to=dm,
        ),
    )

    [frame] = await _frame(
        {
            "configurable": {
                "thread_id": "conv-dm",
                "user_id": USER,
                "conversation_source": "telegram",
            }
        }
    )

    assert frame.content.splitlines()[1:-1] == [
        "Running. Task: buy a lamp",
        "Paused, waiting for the user to finish a step in the live view: "
        "Sign in to opentable.com. Task: book a table",
    ]
