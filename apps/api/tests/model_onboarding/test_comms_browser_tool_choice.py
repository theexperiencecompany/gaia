"""Onboarding gate: does comms, at reasoning effort none, pick the right browser-task tool for what the user said?

Run it before changing COMMS_MODEL_NAME, COMMS_REASONING_EFFORT, the comms
prompt's browser rules or the three tools' descriptions:
uv run pytest tests/model_onboarding/test_comms_browser_tool_choice.py -m model_onboarding
The openai lane needs OPENAI_API_KEY; the custom lane the DEV_LLM_* settings.
One model call per case: the real comms prompt, tools and <browser_task> frame,
after a turn that started the task. It stops short of running the graph.
"""

from dataclasses import dataclass
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
import pytest

from app.agents.context.slots import BROWSER_TASK_MARKER
from app.agents.core.graph_builder.build_graph import comms_tools
from app.agents.core.messages import MessageScope, construct_langchain_messages
from app.agents.core.nodes.browser_task_status import describe_browser_tasks
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.agents.llm.dev_lane import build_custom_chat_model
from app.config.settings import settings
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.llm import (
    COMMS_MODEL_NAME,
    COMMS_REASONING_EFFORT,
    DEFAULT_LLM_TEMPERATURE,
    DEV_LLM_MAX_OUTPUT_TOKENS,
    OPENAI_MAX_OUTPUT_TOKENS,
    LLMProviderName,
    ReasoningLevel,
)
from app.schemas.browser_job import BrowserJobStatus
from app.services.browser.chat_task import ChatBrowserTasks, PausedStep
from tests.factories import make_browser_job_state

# One loop for the module: the custom lane's client is cached, and its pool is bound to the first loop.
pytestmark = [pytest.mark.model_onboarding, pytest.mark.asyncio(loop_scope="module")]

REPEATS = 5
TASK = "Star the theexperiencecompany/gaia repository on github.com"
REASON = "Sign in to github.com so I can star the repository"
#: Calls that act on a running task; a case passes only when exactly its expected one is made.
ACTING_TOOLS = frozenset(
    {"browser_step_done", "stop_browser_task", "tell_browser_task", "cancel_executor"}
)


@dataclass(frozen=True)
class Case:
    message: str
    paused: bool
    #: The one acting tool expected, or None for a reply that must leave the task alone.
    tool: str | None
    note_has: str | None = None
    redirect: bool = False


CASES = {
    "done": Case("done", paused=True, tool="browser_step_done"),
    "done_plus_photo": Case(
        "ok done, also grab the photo", paused=True, tool="browser_step_done", note_has="photo"
    ),
    "redirect": Case(
        "never mind the login, just tell me how many stars the repo has",
        paused=True,
        tool="browser_step_done",
        note_has="star",
        redirect=True,
    ),
    "stop_paused": Case("stop", paused=True, tool="stop_browser_task"),
    "one_sec": Case("one sec", paused=True, tool=None),
    "which_password": Case("which password?", paused=True, tool=None),
    "weather_paused": Case("what's the weather in london right now?", paused=True, tool=None),
    "stop_running": Case("stop", paused=False, tool="stop_browser_task"),
    "change_running": Case(
        "actually star the gaia-cli repo instead", paused=False, tool="tell_browser_task"
    ),
}


def _model(lane: str) -> BaseChatModel:
    """Build the lane's model at effort none, as comms runs in production."""
    if lane == LLMProviderName.OPENAI:
        if not settings.OPENAI_API_KEY:
            pytest.skip("OPENAI_API_KEY is not configured")
        return ChatOpenAI(
            model=COMMS_MODEL_NAME,
            reasoning_effort=COMMS_REASONING_EFFORT,
            temperature=DEFAULT_LLM_TEMPERATURE,
            max_completion_tokens=OPENAI_MAX_OUTPUT_TOKENS,
            api_key=SecretStr(settings.OPENAI_API_KEY),
        )
    if not (settings.DEV_LLM_BASE_URL and settings.DEV_LLM_API_KEY and settings.DEV_LLM_MODEL):
        pytest.skip("the DEV_LLM_* custom lane is not configured")
    return build_custom_chat_model(
        temperature=DEFAULT_LLM_TEMPERATURE,
        max_tokens=DEV_LLM_MAX_OUTPUT_TOKENS,
        reasoning=ReasoningLevel.OFF,
    )


def _started_turn() -> list[AnyMessage]:
    """Return the turn that started the task, as the comms thread holds it."""
    return [
        HumanMessage(content="star the gaia repo on github for me"),
        AIMessage(
            content="",
            tool_calls=[{"name": "call_executor", "args": {"task": TASK}, "id": "call-1"}],
        ),
        ToolMessage(content="Task accepted (task_id: 4f1c2a)", tool_call_id="call-1"),
        AIMessage(content="Opening GitHub."),
    ]


def _frame(paused: bool) -> SystemMessage:
    job = make_browser_job_state("job-1", status=BrowserJobStatus.RUNNING, task=TASK)
    step = PausedStep(handoff_id="h1", job_id="job-1", reason=REASON) if paused else None
    text = describe_browser_tasks(ChatBrowserTasks(running=[job], paused=step))
    return SystemMessage(
        content=wrap_agent_payload(AgentTag.BROWSER_TASK, text),
        additional_kwargs={BROWSER_TASK_MARKER: True},
    )


async def _request(case: Case, provider: str) -> list[AnyMessage]:
    """Assemble the request the way the comms graph does: builder, frame, then the slot order."""
    built = await construct_langchain_messages(
        messages=[{"role": "user", "content": case.message}], scope=MessageScope(source="web")
    )
    state: Any = {"messages": [*_started_turn(), *built, _frame(case.paused)]}
    ordered = manage_system_prompts_node(state, {"configurable": {"provider": provider}}, None)
    return cast(list[AnyMessage], ordered["messages"])


@pytest.mark.parametrize("attempt", range(REPEATS))
@pytest.mark.parametrize("case_id", sorted(CASES))
@pytest.mark.parametrize("lane", [LLMProviderName.OPENAI, LLMProviderName.CUSTOM])
async def test_comms_picks_the_browser_tool_the_reply_calls_for(
    lane: str, case_id: str, attempt: int
) -> None:
    case = CASES[case_id]
    model = _model(lane).bind_tools(list(comms_tools().values()))

    reply = await model.ainvoke(await _request(case, lane))

    calls = [call for call in cast(AIMessage, reply).tool_calls if call["name"] in ACTING_TOOLS]
    assert [call["name"] for call in calls] == ([case.tool] if case.tool else []), calls
    if case.tool == "browser_step_done":
        args = calls[0]["args"]
        note = (args.get("note") or "").lower()
        assert bool(args.get("redirect")) is case.redirect, args
        assert (case.note_has in note) if case.note_has else not note, args
