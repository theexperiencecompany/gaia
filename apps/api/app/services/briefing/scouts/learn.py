"""A scout's learn run: a cheap read-only agent finds what needs the user, then its calls freeze.

The run is bounded by steps and wall clock. Its report names the calls that answered and
where their results hold items; those calls are checked by the playbook validator against
the run's own record, then replayed once with no model so a freeze is known to work.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from app.agents.llm.client import resolve_model
from app.agents.middleware.factory import (
    AccountingOptions,
    ContextOptions,
    SubagentStackOptions,
    create_middleware_stack,
)
from app.agents.prompts.scout_prompts import SCOUT_LEARN_PROMPT
from app.constants.llm import ModelUse
from app.constants.scouts import (
    SCOUT_AGENT_NAME,
    SCOUT_LEARN_RECURSION_LIMIT,
    SCOUT_LEARN_TIMEOUT,
    SCOUT_MAX_BOUND_TOOLS,
    SCOUT_RESULT_BRIEF,
    SCOUT_SIGNAL_CEILING,
)
from app.models.agent_config import AgentConfigurable
from app.models.playbook_models import PlaybookBody, ask_slots
from app.models.scout_models import ScoutDocument, ScoutReport, ScoutStatus, Signal
from app.override.langgraph_bigtool.agent_config import AgentConfig, ToolRetrievalConfig
from app.override.langgraph_bigtool.create_agent import create_agent
from app.override.langgraph_bigtool.utils import State
from app.services.briefing.scouts.tools import ScoutIntegration, ScoutTools
from app.services.briefing.scouts.watch import FrozenWatch, read_only_space, watch
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.parser import RunResults, run_results, validate_playbook
from app.utils.errors import AppError
from app.utils.markdown_utils import json_blocks
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class Learned:
    """What a learn run found today, and the scout it froze (None when nothing would freeze)."""

    signals: list[Signal]
    scout: ScoutDocument | None
    freeze_problem: str | None = None


def _bound(tools: dict[str, BaseTool]) -> dict[str, BaseTool]:
    return dict(list(tools.items())[:SCOUT_MAX_BOUND_TOOLS])


async def _run_agent(
    user_id: str, integration: ScoutIntegration, tools: dict[str, BaseTool], prompt: str
) -> tuple[str, RunResults]:
    """Run the read-only agent; return its final text and the calls it made."""
    graph = create_agent(
        resolve_model(ModelUse.HELPER),
        tools,
        tools_config=ToolRetrievalConfig(disable_retrieve_tools=True, initial_tool_ids=list(tools)),
        agent_config=AgentConfig(
            agent_name=SCOUT_AGENT_NAME,
            middleware=create_middleware_stack(
                agent_name=SCOUT_AGENT_NAME,
                accounting=AccountingOptions(recursion_limit=SCOUT_LEARN_RECURSION_LIMIT),
                context=ContextOptions(summarize=False),
                subagent=SubagentStackOptions(enabled=False),
            ),
        ),
    ).compile()
    configurable: AgentConfigurable = {
        "stream_id": f"scout_{uuid4().hex}",
        "user_id": user_id,
        "conversation_id": f"scout-{integration.integration_id}-{user_id}-{uuid4().hex[:6]}",
        "execution_mode": "background",
    }
    async with asyncio.timeout(SCOUT_LEARN_TIMEOUT.total_seconds()):
        state: State = cast(
            State,
            await graph.ainvoke(
                cast(State, {"messages": [HumanMessage(content=prompt)], "todos": []}),
                config=cast(
                    RunnableConfig,
                    {
                        "configurable": configurable,
                        "metadata": {"user_id": user_id},
                        "recursion_limit": SCOUT_LEARN_RECURSION_LIMIT,
                    },
                ),
            ),
        )
    final = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
    text = final.content if final is not None and isinstance(final.content, str) else ""
    return text, run_results(state) or []


def _parse_report(text: str, integration: ScoutIntegration) -> ScoutReport:
    for block in json_blocks(text):
        try:
            return ScoutReport.model_validate_json(block)
        except ValueError:
            continue
    raise AppError(
        message=f"the {integration.integration_id} scout wrote no valid report",
        why=f"its final message did not hold a ScoutReport (first 200 chars): {text[:200]!r}",
        fix="the scout learns again on the next brief",
    )


def _body(report: ScoutReport) -> PlaybookBody | None:
    if not report.steps:
        return None
    return PlaybookBody(
        description=report.watching,
        steps=[step.to_step() for step in report.steps],
        result_brief=SCOUT_RESULT_BRIEF,
    )


@dataclass(frozen=True, slots=True)
class _Freeze:
    """A learn run's report and the record its calls are checked against."""

    report: ScoutReport
    body: PlaybookBody
    tools: dict[str, BaseTool]
    results: RunResults


async def _freeze_problem(
    user: PlaybookUser, user_id: str, integration: ScoutIntegration, freeze: _Freeze
) -> str | None:
    """Return why the report's calls cannot be frozen, or None when a model-free replay works."""
    if ask_slots(freeze.body.steps):
        return "a scout replays with no model, so its calls cannot carry an $ask slot"
    step_ids = {step.id for step in freeze.body.steps}
    unknown = [s.step_id for s in freeze.report.sources if s.step_id not in step_ids]
    if unknown:
        return f"sources read steps that were not frozen: {', '.join(unknown)}"
    validation = await validate_playbook(
        freeze.body,
        user_id,
        freeze.results,
        space=read_only_space(freeze.tools),
        empty_is_data=True,
    )
    if not validation.valid:
        return "; ".join(f"{issue.where}: {issue.problem}" for issue in validation.issues)
    try:
        await watch(
            user,
            user_id,
            FrozenWatch(integration, freeze.body, freeze.report.sources),
            freeze.tools,
            datetime.now(UTC),
        )
    except AppError as exc:
        return f"the frozen calls did not replay: {exc}"
    return None


async def learn_scout(
    user: PlaybookUser, user_id: str, integration: ScoutIntegration, tools: ScoutTools
) -> Learned:
    """Run the learn agent for one integration; raise when it could not report at all."""
    bound = _bound(tools.read_only)
    now = datetime.now(UTC)
    prompt = SCOUT_LEARN_PROMPT.format(
        app=integration.name, today=now.date().isoformat(), timezone=user.timezone
    )
    text, results = await _run_agent(user_id, integration, bound, prompt)
    report = _parse_report(text, integration)
    signals = [
        Signal(integration_id=integration.integration_id, app=integration.name, **s.model_dump())
        for s in report.signals[:SCOUT_SIGNAL_CEILING]
    ]
    if report.nothing_to_watch:
        scout = ScoutDocument(
            user_id=user_id,
            integration_id=integration.integration_id,
            status=ScoutStatus.NOTHING_TO_WATCH,
            tool_fingerprint=tools.fingerprint,
            learned_at=now,
        )
        return Learned(signals=[], scout=scout)
    body = _body(report)
    problem = (
        "the report froze no calls"
        if body is None
        else await _freeze_problem(
            user, user_id, integration, _Freeze(report, body, bound, results)
        )
    )
    if body is None or problem is not None:
        log.warning(
            "briefing.scout_not_frozen",
            integration_id=integration.integration_id,
            problem=problem,
        )
        return Learned(signals=signals, scout=None, freeze_problem=problem)
    scout = ScoutDocument(
        user_id=user_id,
        integration_id=integration.integration_id,
        status=ScoutStatus.WATCHING,
        tool_fingerprint=tools.fingerprint,
        playbook=body,
        sources=report.sources,
        learned_at=now,
    )
    return Learned(signals=signals, scout=scout)
