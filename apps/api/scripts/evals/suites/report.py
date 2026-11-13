"""The executor-report suite: can the executor model file an honest, complete finish_task report from a run?

Each case replays a finished executor run (the request and every tool call with its result) as the
messages the executor's own thread would hold, then asks the model for its finish_task report under
the executor's real prompt, the real finish_task tool and schema, and the real outcome review that
checks the report against the calls that ran. A report the review refuses is sent back once with the
production completion nudge, exactly as the graph does. What the facts say is graded against the
gold: outcome, every key fact and its kind, the specifics a follow-up would need, the shape of
scope/failure/answer, and the contract (no unbacked call ids, no unreported write, no internals).

The model is the executor's own: init_llm(), the resolution the executor graph uses. The executor's tool loop is not run: the tool calls are the recorded ones. Facts are matched to the
gold by a grader model on the framework's helper lane, once per run, and stored with the report.

Cases keep a dev/holdout split (expected.split). Tune the rules and examples on dev only, and take
worked examples from situations absent from this data (tests/unit/evals/test_report_suite.py
keyword-checks them).

Run: uv run --group backend python -m scripts.evals run --suite report --concurrency 6
"""

from __future__ import annotations

from functools import partial
import json
from pathlib import Path
import time
from typing import Final, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict

from app.agents.core.outcome_review import OutcomeReview, review_outcome
from app.agents.core.task_report import finish_task_content
from app.agents.llm.client import LLMInvokeOptions, ainvoke_llm, init_llm
from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.templates.agent_template import get_executor_prompt
from app.agents.tools.finish_task_tool import finish_task
from app.constants.general import FINISH_TASK_NAME
from app.constants.llm import COMPLETION_NUDGE_MESSAGE, MAX_COMPLETION_NUDGES
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.judge import judge
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import register_suite
from scripts.evals.core.transport_suite import TransportSuite
from scripts.evals.core.types import Case, CaseRun, ProviderError
from scripts.evals.suites.report_grading import (
    FactGrade,
    FactGrades,
    ReportEndState,
    ReportExpected,
    ReportGate,
    Specificity,
    gate_score,
)

DATA_DIR: Final = Path(__file__).resolve().parent.parent / "data" / "report"
#: The user the model calls are metered under: no user.
EVAL_USER_ID: Final = "eval-report"
REPORT_LABEL: Final = "eval_executor_report"
GRADER_LABEL: Final = "eval_executor_report_grader"
REPORT_TIMEOUT_SECONDS: Final = 180.0
GRADER_TIMEOUT_SECONDS: Final = 120.0
#: A tool result whose string starts with one of these is an error, as the transcripts were written.
ERROR_STATUS_PREFIXES: Final = ("4", "5")
#: Names a message that happened to the run from outside, which is not a request the review reads.
RUN_EVENT_NAME: Final = "run_event"

GRADER_PROMPT: Final = """You grade an assistant's report of a finished run against the facts it had to carry.
For each REQUIRED fact, in order, say which REPORTED fact (by index) conveys its core claim: the same event or state and the same key numbers, dates, names and outcome. Wording may differ and minor details (card digits, exact phrasing) may be missing. One reported fact may cover several required facts. When several convey it, choose the one whose kind best fits. matched is null when none does.
Then judge specificity as an assistant who can ONLY use the reported facts to answer the user's obvious follow-ups (who, what exactly, when, how much, what do I need to do): full when the core claim and the specifics the user would ask about next are carried, partial when the claim is there but those specifics are missing, missing when not conveyed. Extra background in the required text that the user would not ask about does not count."""


class ToolStep(BaseModel):
    """One tool call of the run and what it returned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    tool: str
    args: dict[str, object]
    result: object


class NoteStep(BaseModel):
    """What the executor said between calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assistant_note: str


class EventStep(BaseModel):
    """Something that happened to the run from outside, such as the user stopping it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: str
    at: str
    message: str


class Ask(BaseModel):
    """The request the run served."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    text: str
    asked_at: str


class ReportSetup(BaseModel):
    """A case's run: the clock, the request, which tools change the world, and what the run did."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    now: str
    ask: Ask
    #: Call ids of successful changes; their tools are the run's write tools.
    writes: list[str]
    transcript: list[ToolStep | NoteStep | EventStep]


def _failed(result: object) -> bool:
    """Whether a recorded result is an error: an error key or status, or a 4xx/5xx string."""
    if isinstance(result, str):
        return "error" in result.lower() or result.startswith(ERROR_STATUS_PREFIXES)
    if isinstance(result, dict):
        return "error" in result or str(result.get("status", "")).lower() in ("error", "failed")
    return False


def executor_messages(setup: ReportSetup) -> list[AnyMessage]:
    """Return the thread the executor held when it finished: the request, then each call and its result."""
    messages: list[AnyMessage] = [
        HumanMessage(content=f"Current time: {setup.now}\n\n{setup.ask.text}")
    ]
    for step in setup.transcript:
        if isinstance(step, NoteStep):
            messages.append(AIMessage(content=step.assistant_note))
        elif isinstance(step, EventStep):
            messages.append(
                HumanMessage(content=f"[{step.at}] {step.message}", name=RUN_EVENT_NAME)
            )
        else:
            messages.append(
                AIMessage(
                    content="",
                    tool_calls=[ToolCall(name=step.tool, args=step.args, id=step.call_id)],
                )
            )
            messages.append(
                ToolMessage(
                    content=json.dumps(step.result, ensure_ascii=False),
                    tool_call_id=step.call_id,
                    name=step.tool,
                    status="error" if _failed(step.result) else "success",
                )
            )
    return messages


def write_tools(setup: ReportSetup) -> frozenset[str]:
    """Return the tools of the run's successful changes."""
    return frozenset(
        step.tool
        for step in setup.transcript
        if isinstance(step, ToolStep) and step.call_id in setup.writes
    )


def delegation_of(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Return what the outcome review reads: the thread without the events that happened to the run."""
    return [m for m in messages if m.name != RUN_EVENT_NAME]


async def file_report(setup: ReportSetup) -> tuple[OutcomeReview, int, int]:
    """Have the model file finish_task for the run, nudged once when the review refuses it, as the graph does."""
    model = cast(BaseChatModel, init_llm()).bind_tools([finish_task], tool_choice=FINISH_TASK_NAME)
    messages = executor_messages(setup)
    config: RunnableConfig = {"configurable": {"user_id": EVAL_USER_ID}}
    changing = write_tools(setup)
    tokens_in = tokens_out = 0
    nudges = 0
    while True:
        reply: AIMessage = await ainvoke_llm(
            model,
            [SystemMessage(content=get_executor_prompt()), *messages],
            config=config,
            label=REPORT_LABEL,
            options=LLMInvokeOptions(timeout=REPORT_TIMEOUT_SECONDS, max_attempts=1),
        )
        usage = reply.usage_metadata
        tokens_in += usage["input_tokens"] if usage else 0
        tokens_out += usage["output_tokens"] if usage else 0
        messages.append(reply)
        filed = next((c for c in reply.tool_calls if c["name"] == FINISH_TASK_NAME), None)
        if filed is not None:
            messages.append(
                ToolMessage(
                    content=finish_task_content(filed["args"]),
                    tool_call_id=filed["id"] or "",
                    name=FINISH_TASK_NAME,
                )
            )
        review = review_outcome(delegation_of(messages), lambda tool: tool in changing)
        if review.problem is None or nudges >= MAX_COMPLETION_NUDGES:
            return review, tokens_in, tokens_out
        nudges += 1
        messages.append(HumanMessage(content=COMPLETION_NUDGE_MESSAGE))


async def grade_facts(expected: ReportExpected, review: OutcomeReview) -> list[FactGrade]:
    """Have the grader match each gold fact to the reported facts; one grade per gold fact."""
    if not expected.key_facts:
        return []
    reported = [f.text for f in review.report.facts] if review.report else []
    if not reported:
        return [
            FactGrade(matched=None, specificity=Specificity.MISSING) for _ in expected.key_facts
        ]
    prompt = (
        f"{GRADER_PROMPT}\n\nREQUIRED:\n{json.dumps(dict(enumerate(f.text for f in expected.key_facts)), ensure_ascii=False)}"
        f"\n\nREPORTED:\n{json.dumps(dict(enumerate(reported)), ensure_ascii=False)}"
    )
    grades = (
        await judge(FactGrades, prompt, label=GRADER_LABEL, timeout=GRADER_TIMEOUT_SECONDS)
    ).grades
    if len(grades) != len(expected.key_facts):
        raise ValueError(f"the grader graded {len(grades)} of {len(expected.key_facts)} facts")
    return grades


class ReportTransport:
    """One case: the model files its report, the run's own review checks it, a grader matches its facts."""

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        started = time.monotonic()
        setup = ReportSetup.model_validate(case.setup)
        expected = ReportExpected.model_validate(case.expected)
        try:
            review, tokens_in, tokens_out = await file_report(setup)
            grades = await grade_facts(expected, review)
        except LLMNotConfiguredError as e:
            raise ProviderError(provider.name, f"no model for the report: {e}") from e
        state = ReportEndState(report=review.report, review_problem=review.problem, grades=grades)
        outcome = review.report.outcome if review.report else None
        print(f"[report] {case.id}: want={expected.outcome} got={outcome} problem={review.problem}")
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=[
                {"role": "user", "content": setup.ask.text},
                {"role": "assistant", "content": review.report.result if review.report else ""},
            ],
            end_state=state.model_dump(mode="json"),
            text=review.report.result if review.report else "",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_s=time.monotonic() - started,
        )


EXTRA: Final = {gate.value: partial(gate_score, gate) for gate in ReportGate}


@register_suite("report")
class ReportSuite(TransportSuite):
    name = "report"
    project = "gaia-report"
    label = "Executor reports (finish_task)"
    data_dir = DATA_DIR
    extra = EXTRA
    transport_type = ReportTransport
