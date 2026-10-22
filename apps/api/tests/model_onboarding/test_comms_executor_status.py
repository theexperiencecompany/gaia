"""Onboarding gate: does comms act on the live background-work status instead of guessing from history?

Run it before changing COMMS_MODEL_NAME, the comms prompt's "Tasks in flight"
rules or the executor status frame:
uv run pytest tests/model_onboarding/test_comms_executor_status.py -m model_onboarding
Needs OPENAI_API_KEY. One model call per case: the real comms prompt and tools,
and the frame the real executor_status_hook writes for a lock state set up in
fakeredis. It stops short of running the graph, so the executor never runs.
"""

from dataclasses import dataclass
import os
from typing import Any, cast
from unittest.mock import MagicMock

import fakeredis.aioredis
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
import pytest

from app.agents.core.background.executor_progress import ProgressRecorder
from app.agents.core.background.executor_queue import build_lock_value, hold_run_alive
from app.agents.core.graph_builder.build_graph import comms_tools
from app.agents.core.messages import MessageScope, construct_langchain_messages
from app.agents.core.nodes.executor_status import executor_status_hook
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.agents.llm.lane import ModelLane
from app.agents.tools.executor_tool import handoff_message
from app.config.settings import settings
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS,
)
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.llm import (
    COMMS_MODEL_NAME,
    COMMS_REASONING_EFFORT,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    OPENAI_MAX_OUTPUT_TOKENS,
    LLMProviderName,
)

pytestmark = [pytest.mark.model_onboarding]

REPEATS = 5
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CONV = "conv-status"
TASK_ID = "4f1c2a"
REQUEST = "archive all the promo emails in my inbox from this week"


@dataclass(frozen=True)
class Case:
    #: idle, running or dead: what the busy lock says right now.
    lock: str
    #: The user's new message; None means the turn right after this turn's own dispatch.
    message: str | None
    #: True: must call call_executor. False: must not. None: either is right.
    dispatches: bool | None
    #: Phrases a reply without a dispatch must not use: claims the evidence contradicts.
    must_not_claim: tuple[str, ...] = ()


#: What a reply about work that has ended must never say: it is not running, and a
#: reply saying it checks without a call did not check.
ENDED_CLAIMS = ("still", "in progress", "already", "checking", "on it")

CASES = {
    # The incident: an error on screen, the user retries, nothing is running.
    "retry_after_error_idle": Case("idle", REQUEST, dispatches=True),
    "try_again_idle": Case("idle", "that errored, try again", dispatches=True),
    # Ended, but its result never arrived: the executor's history knows, so ask it.
    "did_it_go_through_idle": Case("idle", "did that go through?", dispatches=True),
    # The run died with its process: its result will never come on its own.
    # Died mid-run: nothing was recorded, so a plain "it stopped" is right; "still going" is not.
    "did_it_go_through_dead": Case(
        "dead", "did that go through?", dispatches=None, must_not_claim=ENDED_CLAIMS
    ),
    "retry_dead": Case("dead", REQUEST, dispatches=True),
    # A resend while the run is live joins it, and asking is safe; replying is too.
    "retry_running": Case("running", REQUEST, dispatches=None),
    "status_running": Case("running", "is it done yet?", dispatches=None),
    # Something new for the running work still reaches it.
    "add_while_running": Case("running", "oh and archive the newsletter ones too", dispatches=True),
    # The acknowledgment of this turn's own dispatch must never dispatch again.
    "ack_after_dispatch": Case("running", None, dispatches=False),
    "chat_while_running": Case("running", "lol thanks", dispatches=False),
    # Mid-run progress comes from the status note's record, not a call.
    "progress_running": Case("running", "how's it going?", dispatches=False),
}

#: What the running executor has done so far, as its stream writer records it.
PROGRESS_FRAMES: list[dict[str, object]] = [
    {
        "todo_progress": {
            "source": "executor",
            "todos": [
                {"id": "1", "content": "Find this week's promo emails", "status": "completed"},
                {"id": "2", "content": "Archive them", "status": "in_progress"},
            ],
        }
    },
    {
        "tool_data": {
            "tool_name": "tool_calls_data",
            "data": {
                "tool_name": "GMAIL_FETCH_EMAILS",
                "message": "Fetch emails",
                "inputs": {"query": "category:promotions newer_than:7d"},
            },
        }
    },
]


def _model() -> ChatOpenAI:
    """Comms' model at effort none: direct on OpenAI, or the same model through OpenRouter.

    COMMS_EVAL_VIA_OPENROUTER=1 routes it through OpenRouter, for when only that key
    works; same model and slot order, a different transport than production.
    """
    if os.environ.get("COMMS_EVAL_VIA_OPENROUTER") == "1":
        if not settings.OPENROUTER_API_KEY:
            pytest.skip("OPENROUTER_API_KEY is not configured")
        return ChatOpenAI(
            model=f"openai/{COMMS_MODEL_NAME}",
            base_url=OPENROUTER_BASE_URL,
            extra_body={"reasoning": {"effort": COMMS_REASONING_EFFORT}},
            temperature=DEFAULT_LLM_TEMPERATURE,
            max_completion_tokens=OPENAI_MAX_OUTPUT_TOKENS,
            api_key=SecretStr(settings.OPENROUTER_API_KEY),
        )
    if not settings.OPENAI_API_KEY:
        pytest.skip("OPENAI_API_KEY is not configured")
    return ChatOpenAI(
        model=COMMS_MODEL_NAME,
        reasoning_effort=COMMS_REASONING_EFFORT,
        temperature=DEFAULT_LLM_TEMPERATURE,
        max_completion_tokens=OPENAI_MAX_OUTPUT_TOKENS,
        api_key=SecretStr(settings.OPENAI_API_KEY),
    )


def _config() -> Any:
    """Comms' configurable on its OpenAI lane: the lane picks the slot order the request is sent in."""
    lane = ModelLane(
        provider=LLMProviderName.OPENAI,
        model=COMMS_MODEL_NAME,
        reasoning=None,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )
    return {"configurable": {"thread_id": CONV, "lane": lane.to_configurable()}}


async def _set_lock(client: fakeredis.aioredis.FakeRedis, lock: str) -> None:
    value = build_lock_value("stream-1", TASK_ID)
    key = f"{EXECUTOR_BUSY_PREFIX}{CONV}"
    if lock == "running":
        await client.set(key, value, ex=EXECUTOR_BUSY_TTL)
        await hold_run_alive(CONV, value)
        recorder = ProgressRecorder(CONV, value)
        writer = recorder.wrap(lambda _frame: None)
        for frame in PROGRESS_FRAMES:
            writer(frame)
        await recorder.settle()
    elif lock == "dead":
        age = EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS + 5
        await client.set(key, value, ex=EXECUTOR_BUSY_TTL - age)


async def _own_dispatch(model: Runnable[Any, BaseMessage]) -> list[AnyMessage]:
    """Return the model's own first call_executor for REQUEST and the real hand-off result.

    A hand-written dispatch read as a sloppy brief (the request verbatim, one
    criterion) and the model "fixed" it with a second call, a fixture artifact.
    """
    built = await construct_langchain_messages(query=REQUEST, scope=MessageScope(source="web"))
    ordered = manage_system_prompts_node(cast(Any, {"messages": built}), _config(), None)
    first = cast(AIMessage, await model.ainvoke(ordered["messages"]))
    calls = [call for call in first.tool_calls if call["name"] == CALL_EXECUTOR_NAME]
    if not calls:
        pytest.fail(f"the model did not dispatch the request: {first.content!r}")
    dispatch = AIMessage(content="", tool_calls=[calls[0]])
    return [
        *built,
        dispatch,
        ToolMessage(content=handoff_message(TASK_ID), tool_call_id=calls[0]["id"]),
    ]


async def _request(case: Case, dispatched: list[AnyMessage]) -> list[AnyMessage]:
    """Assemble the request as the comms graph does: thread, builder, status hook, slot order."""
    if case.message is None:
        thread: list[AnyMessage] = dispatched
    else:
        built = await construct_langchain_messages(
            query=case.message, scope=MessageScope(source="web")
        )
        # The earlier dispatch's ack, then the error the user saw, then their new message.
        thread = [*dispatched, AIMessage(content="on it"), *built]
    config = _config()
    framed = await executor_status_hook(cast(Any, {"messages": thread}), config, MagicMock())
    ordered = manage_system_prompts_node(framed, config, None)
    return cast(list[AnyMessage], ordered["messages"])


@pytest.mark.parametrize("attempt", range(REPEATS))
@pytest.mark.parametrize("case_id", sorted(CASES))
async def test_comms_acts_on_the_live_status(
    fake_redis: fakeredis.aioredis.FakeRedis, case_id: str, attempt: int
) -> None:
    case = CASES[case_id]
    model = _model().bind_tools(list(comms_tools().values()))
    thread = await _own_dispatch(model)
    await _set_lock(fake_redis, case.lock)

    reply = cast(AIMessage, await model.ainvoke(await _request(case, thread)))

    dispatched = any(call["name"] == CALL_EXECUTOR_NAME for call in reply.tool_calls)
    print(f"\n[{case_id}|{attempt}] dispatched={dispatched} text={reply.content!r}")
    if case.dispatches is not None:
        assert dispatched is case.dispatches, (reply.tool_calls, reply.content)
    if not dispatched:
        said = str(reply.content).lower()
        assert not [claim for claim in case.must_not_claim if claim in said], reply.content
