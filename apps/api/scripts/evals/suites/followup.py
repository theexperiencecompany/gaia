"""The follow-up suite: asked what GAIA did, comms reads the work record instead of running the work again.

A user who asks "what exactly did you send her?" or "are you sure it went through?" must be answered
from what the background run recorded. Each case seeds a finished run through the production trace
recorder (its calls, their inputs and outputs), then puts the user's question to the comms persona
with the two tools that decide it: the real read_work_record, executed against the seeded record, and
the real call_executor, which is never executed: calling it is the re-run this suite exists to catch.

Contrast cases keep the suite honest: a genuinely new ask and a request for fresh data must still go
to the executor, and thanks needs no tool, so "always read the record" cannot pass.

Gates are mechanical: the tool calls made, specifics that exist only in the record (so reading it is
the only way to say them), claims that must not be made, and GAIA's machinery never named.

The comms agent's other tools and its work-state block are not part of the turn: this tests the
decision and the honesty of the answer, not the whole comms graph (the comms suite does that live).

Cases keep a dev/holdout split (expected.split); tune the comms prompt on dev only.

Run: uv run --group backend python -m scripts.evals run --suite followup --concurrency 4
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import time
from typing import Final, Literal
from uuid import uuid4

from bson import ObjectId
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from app.agents.llm.client import LLMInvokeOptions, ainvoke_llm, resolve_model
from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.templates.agent_template import get_comms_static_prompt
from app.agents.tools.executor_tool import call_executor
from app.agents.tools.work_record_tool import read_work_record
from app.constants.chat import ConversationSource
from app.constants.llm import ModelUse
from app.models.run_trace_models import RunState
from app.services.executor_trace.recorder import (
    RunOwner,
    TracedCall,
    begin_run,
    end_run,
    record_call,
)
from scripts.evals.core.app_boot import ensure_app_registered
from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.gates import ExtraGates
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import register_suite
from scripts.evals.core.split import Split
from scripts.evals.core.transport_suite import TransportSuite
from scripts.evals.core.types import Case, CaseRun, ProviderError

DATA_DIR: Final = Path(__file__).resolve().parent.parent / "data" / "followup"
EVAL_USER_LABEL: Final = "eval_followup"
TURN_TIMEOUT_SECONDS: Final = 120.0
#: Model turns one case may take: read the list, read a call, answer, with room for one retry.
MAX_STEPS: Final = 4
#: The gap between seeded calls, so the record reads in order.
CALL_SPACING: Final = timedelta(seconds=20)
NEUTRAL_EXECUTOR_RECORD: Final = "A background run was started."


class Turn(BaseModel):
    """One earlier message of the thread."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["user", "assistant"]
    content: str


class WorkCall(BaseModel):
    """One tool call of the run the thread's work left behind."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    args: dict[str, object]
    output: str
    failed: bool = False


class FollowupSetup(BaseModel):
    """A case's thread: what was said, what the background run did, and the question."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: ConversationSource = ConversationSource.WEB
    history: list[Turn] = Field(default_factory=list)
    work: list[WorkCall] = Field(default_factory=list)
    question: str


class FollowupExpected(BaseModel):
    """The case's gold: its split, and the category the report groups it under."""

    model_config = ConfigDict(extra="allow", frozen=True)

    category: str
    split: Split


async def seed_work_record(user_id: str, conversation_id: str, work: list[WorkCall]) -> None:
    """Write the run through the production recorder, so the record is exactly what a real run leaves."""
    if not work:
        return
    owner = RunOwner(user_id, conversation_id, uuid4().hex)
    started = datetime.now(UTC) - CALL_SPACING * (len(work) + 1)
    await begin_run(owner)
    for index, call in enumerate(work):
        at = started + CALL_SPACING * index
        await record_call(
            owner,
            TracedCall(
                tool_name=call.tool,
                tool_call_id=None,
                args=call.args,
                output_text=call.output,
                failed=call.failed,
                started_at=at,
                finished_at=at + CALL_SPACING / 2,
            ),
        )
    await end_run(owner, RunState.FINISHED)


def thread_messages(setup: FollowupSetup) -> list[BaseMessage]:
    """Return the thread as comms holds it: the persona, what was said, then the question."""
    turns: list[BaseMessage] = [
        HumanMessage(content=t.content) if t.role == "user" else AIMessage(content=t.content)
        for t in setup.history
    ]
    return [
        SystemMessage(content=get_comms_static_prompt(setup.source.value)),
        *turns,
        HumanMessage(content=setup.question),
    ]


async def answer(
    setup: FollowupSetup, user_id: str, conversation_id: str
) -> tuple[str, list[dict[str, object]], int, int]:
    """Run the turn: reads of the record are executed, a call to the executor ends it as the re-run it is."""
    model = resolve_model(ModelUse.HELPER).bind_tools([read_work_record, call_executor])
    config: RunnableConfig = {"configurable": {"user_id": user_id, "thread_id": conversation_id}}
    messages = thread_messages(setup)
    calls: list[dict[str, object]] = []
    tokens_in = tokens_out = 0
    for _ in range(MAX_STEPS):
        reply: AIMessage = await ainvoke_llm(
            model,
            messages,
            config=config,
            label=EVAL_USER_LABEL,
            options=LLMInvokeOptions(timeout=TURN_TIMEOUT_SECONDS, max_attempts=1),
        )
        usage = reply.usage_metadata
        tokens_in += usage["input_tokens"] if usage else 0
        tokens_out += usage["output_tokens"] if usage else 0
        messages.append(reply)
        if not reply.tool_calls:
            return str(reply.content), calls, tokens_in, tokens_out
        reran = False
        for call in reply.tool_calls:
            calls.append({"name": call["name"], "args": call["args"]})
            if call["name"] == read_work_record.name:
                content = await read_work_record.ainvoke(call["args"], config=config)
            else:
                reran = reran or call["name"] == call_executor.name
                content = NEUTRAL_EXECUTOR_RECORD
            messages.append(
                ToolMessage(content=content, tool_call_id=call["id"] or "", name=call["name"])
            )
        if reran:
            return str(reply.content), calls, tokens_in, tokens_out
    raise ValueError(f"the turn did not settle within {MAX_STEPS} model calls")


class FollowupTransport:
    """One case: seed the record, ask the question, journal the tools it used and what it said."""

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        started = time.monotonic()
        await ensure_app_registered()
        setup = FollowupSetup.model_validate(case.setup)
        user_id, conversation_id = str(ObjectId()), str(ObjectId())
        await seed_work_record(user_id, conversation_id, setup.work)
        try:
            text, calls, tokens_in, tokens_out = await answer(setup, user_id, conversation_id)
        except LLMNotConfiguredError as e:
            raise ProviderError(provider.name, f"no model for the turn: {e}") from e
        print(f"[followup] {case.id}: tools={[c['name'] for c in calls]}")
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=[
                *({"role": t.role, "content": t.content} for t in setup.history),
                {"role": "user", "content": setup.question},
                {"role": "assistant", "content": text},
            ],
            tool_calls=calls,
            final_turn_tool_calls=calls,
            end_state={"told": text, "tools": json.dumps([c["name"] for c in calls])},
            text=text,
            tokens_in=tokens_in or estimate_tokens(setup.question),
            tokens_out=tokens_out or estimate_tokens(text),
            duration_s=time.monotonic() - started,
        )


#: Every gate this suite scores is a shared one: tool calls made and not made, what is said and not said.
EXTRA: Final[ExtraGates] = {}


@register_suite("followup")
class FollowupSuite(TransportSuite):
    name = "followup"
    project = "gaia-followup"
    label = "Follow-up (answer from the work record)"
    data_dir = DATA_DIR
    extra = EXTRA
    transport_type = FollowupTransport
