"""Regression for GAIA-719: comms answers like an assistant, not a status report.

Run it before changing the production comms lane or the comms voice rules:
uv run pytest tests/model_onboarding/test_comms_reply_style_gaia_719.py -m model_onboarding
Needs OPENROUTER_API_KEY. One call per case to the production OpenRouter client
with the real comms prompt and tools, on a thread holding the dispatch and the
executor's report as result delivery frames it. It stops short of running the graph.
"""

from dataclasses import dataclass
import re
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables.configurable import RunnableConfigurableFields
import pytest

from app.agents.core.background.comms_narrator import _executor_report
from app.agents.core.graph_builder.build_graph import comms_tools
from app.agents.core.messages import MessageScope, construct_langchain_messages
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.agents.llm.client import init_openai_llm, init_openrouter_llm
from app.agents.llm.lane import AgentRole, ModelLane, resolve_lane
from app.agents.prompts.comms_prompts import INTERACTIVE_DELIVERY_NOTE, SILENCE_NOTE
from app.agents.tools.executor_tool import handoff_message
from app.config.settings import settings
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.llm import LLMProviderName

pytestmark = [pytest.mark.model_onboarding]

REPEATS = 3
CONV = "conv-gaia-719"

#: Process narration and the disclaimers the issue quotes: none belongs in a reply.
NARRATION = (
    "executor",
    "subagent",
    "agent",
    "tool call",
    "orchestrat",
    "in the background",
    "behind the scenes",
    "won't claim",
    "will not claim",
    "won't say it",
    "until it's done",
    "until it is done",
    "until it's confirmed",
)
#: "Almost done" hedging on work the result says finished.
HEDGES = ("almost", "still", "should be", "in progress", "working on", "not yet")
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


@dataclass(frozen=True)
class Case:
    request: str
    #: The executor's report; None is the acknowledgment turn right after the dispatch.
    report: str | None
    #: Upper bound on the reply, in characters: a status report blows through it.
    max_chars: int
    bullets: bool = False
    #: The result says the work finished, so no hedging is allowed.
    done: bool = False
    #: The result says it is blocked: the blocker and the next step, no repeated caveat.
    blocked: bool = False


CASES = {
    # The incident: a three-part ask, acknowledged with a numbered plan and disclaimers.
    "ack_after_multi_dispatch": Case(
        request=(
            "first file a linear issue about gaia refusing to add an MCP it can add itself, "
            "then add the swiggy instamart MCP, and mail aryan the browser error we hit"
        ),
        report=None,
        max_chars=160,
    ),
    "concise_bullets": Case(
        request="what's on my calendar tomorrow? concise bullet points only",
        report=(
            "Fetched tomorrow's calendar (Tue Nov 3) via GOOGLECALENDAR_EVENTS_LIST. "
            "3 events: 09:30-10:00 Standup (Google Meet); 13:00-14:00 Lunch with Priya "
            "(Blue Tokai, Bandra); 16:00-17:00 Investor call with Arjun (Zoom). "
            "No conflicts found. Checked primary calendar only."
        ),
        max_chars=400,
        bullets=True,
    ),
    "completed_action": Case(
        request="add dentist friday 3pm",
        report=(
            "Created calendar event 'Dentist' on Fri Nov 6, 15:00-16:00 on the primary "
            "calendar. event_id=evt_8f2a91c. Default reminder 30 min. Verified the "
            "event exists via GOOGLECALENDAR_FIND_EVENT."
        ),
        max_chars=160,
        done=True,
    ),
    "blocked_action": Case(
        request="transfer my appz.com listing to the GAIA v0 account",
        report=(
            "BLOCKED. Opened appz.com/claim in the browser. The page shows 'Sign in to "
            "claim your listing for GAIA v0'. A login handoff with a live view link was "
            "sent to the user. The transfer has NOT happened and cannot continue until "
            "the user signs in. No confirmation of transfer received."
        ),
        max_chars=320,
        blocked=True,
    ),
    "background_update": Case(
        request=(
            "file a linear bug for the custom MCP refusal, set up the swiggy instamart "
            "MCP, and draft the browser handoff email to aryan. give me concise bullets"
        ),
        report=(
            "Task 1: created Linear issue GAIA-731 'GAIA refuses custom MCP setup' "
            "(https://linear.app/heygaia/issue/GAIA-731). Task 2: Swiggy Instamart MCP NOT "
            "added: no public MCP endpoint URL found, need the URL from the user before "
            "adding and verifying. Task 3: drafted email to aryan@heygaia.io 'Browser "
            "handoff failure', awaiting user approval in the draft card, not sent."
        ),
        max_chars=500,
        bullets=True,
    ),
}


@pytest.fixture(autouse=True)
def _production(monkeypatch: pytest.MonkeyPatch) -> None:
    # Production's comms lane, not the OpenAI one a development key would pick.
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "workos")


def _model(lane: ModelLane) -> BaseChatModel:
    """Return the production client for the lane comms resolves, as its loader builds it."""
    if not settings.OPENROUTER_API_KEY:
        pytest.skip("OPENROUTER_API_KEY is not configured")
    loader = init_openai_llm if lane.provider is LLMProviderName.OPENAI else init_openrouter_llm
    fields = cast(RunnableConfigurableFields, loader().loader_func())
    return cast(BaseChatModel, fields.default)


async def _request(case: Case, lane: ModelLane) -> list[AnyMessage]:
    """Assemble the result turn as delivery does: the ask, its dispatch, then the framed report."""
    built = await construct_langchain_messages(query=case.request, scope=MessageScope(source="web"))
    dispatch = AIMessage(
        content="",
        tool_calls=[{"name": CALL_EXECUTOR_NAME, "args": {"task": case.request}, "id": "call-1"}],
    )
    thread: list[AnyMessage] = [
        *built,
        dispatch,
        ToolMessage(content=handoff_message("4f1c2a"), tool_call_id="call-1"),
    ]
    if case.report is not None:
        delivery = f"{INTERACTIVE_DELIVERY_NOTE}{SILENCE_NOTE}"
        thread += [AIMessage(content="on it"), _executor_report(case.report, "result", delivery)]
    config: Any = {"configurable": {"thread_id": CONV, "lane": lane.to_configurable()}}
    ordered = manage_system_prompts_node(cast(Any, {"messages": thread}), config, None)
    return cast(list[AnyMessage], ordered["messages"])


@pytest.mark.parametrize("attempt", range(REPEATS))
@pytest.mark.parametrize("case_id", sorted(CASES))
async def test_comms_replies_like_an_assistant(case_id: str, attempt: int) -> None:
    case = CASES[case_id]
    lane, _ = await resolve_lane(None, AgentRole.COMMS)
    model = _model(lane).bind_tools(list(comms_tools().values()))

    reply = cast(AIMessage, await model.ainvoke(await _request(case, lane)))

    text = reply.text.strip()
    said = text.lower()
    lines = [line for line in text.splitlines() if line.strip()]
    print(f"\n[{case_id}|{attempt}] {text!r}")
    if case.report is None and not text:
        # A reaction in place of words is the acknowledgment the prompt prefers.
        assert reply.tool_calls, reply
        return
    assert text, reply
    assert len(text) <= case.max_chars, text
    assert not [term for term in NARRATION if term in said], text
    if case.bullets:
        prose = [line for line in lines if not BULLET.match(line)]
        assert len(lines) - len(prose) >= 3, text
        assert len(prose) <= 1, text
    if case.done:
        assert not [hedge for hedge in HEDGES if hedge in said], text
    if case.blocked:
        assert len(SENTENCE_END.findall(text)) <= 3, text
