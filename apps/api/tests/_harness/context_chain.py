"""The message array a tier's model actually receives, produced in-process.

Seeding a thread is only half of what reaches the LLM: pre-model hooks rewrite
the array before every call, and the hook output — not the seed — is the
request. Asserting on the seed therefore cannot see a mis-slotted message, which
is exactly the class of defect this harness exists to catch.

``execute_hooks`` is a plain async function over a plain dict, so the whole chain
runs with no compiled graph, no checkpointer, no LLM and no network:

    messages = await effective_context(
        AgentTier.PROVIDER_SUBAGENT, ContextSeed(query="...")
    )

Every external read the sections perform is pinned by ``fake_context_sources``
and the clients beneath them are fenced, so a section that grows a new read
fails loudly instead of quietly reaching a real store.
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import patch

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.memory import InMemoryStore
import time_machine

from app.agents.context.assemble import assemble_context
from app.agents.context.section_context import SectionContext
from app.agents.context.slots import PromptSlot, slot_of
from app.agents.context.tiers import AgentTier
from app.agents.core.messages import construct_langchain_messages
from app.agents.core.nodes.pre_model_hooks import (
    comms_pre_model_hooks,
    worker_pre_model_hooks,
)
from app.agents.core.subagents.subagent_helpers import create_subagent_system_message
from app.agents.core.subagents.subagent_runner import ThreadSeed, build_initial_messages
from app.agents.prompts.subagent_prompts import WORKFLOW_AGENT_SYSTEM_PROMPT
from app.agents.templates.agent_template import EXECUTOR_PROMPT_TEMPLATE
from app.agents.tools.todo_tools import create_todo_pre_model_hook
from app.config.settings import settings
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentThread,
    AgentTurn,
    build_agent_config,
)
from app.helpers.message_helpers import build_current_time_message
from app.models.agent_models import AgentConfigurable, AgentUserContext, agent_configurable
from app.models.message_models import MessageDict
from app.models.user_models import AuthenticatedUser
from app.override.langgraph_bigtool.hooks import HookType, execute_hooks
from app.override.langgraph_bigtool.utils import State
from app.services.workflow import workflow_subagent
from tests._harness.context_sources import ContextSources, fake_context_sources

#: A fixed instant so ``build_current_time_message`` renders the same bytes on
#: every run. Deliberately mid-month and mid-afternoon UTC so no timezone offset
#: rolls the local date and turns a stable assertion into a flaky one.
FIXED_NOW = datetime(2026, 3, 17, 14, 30, tzinfo=UTC)

#: The public backend host the artifact-URL banner renders. Pinned for the same
#: reason as the clock: ``settings.HOST`` is read straight into the seeded text,
#: so an unpinned one bakes whatever ``apps/api/.env`` sets on the machine that
#: recorded a snapshot into the file — green in CI (no .env, so the default) and
#: red on every developer machine, or the reverse once re-recorded there.
FIXED_HOST = "https://api.heygaia.io"

#: The spawned-subagent tier builds its static prompt from the spawning caller's
#: text rather than a template, so the harness supplies a stable stand-in.
SPAWN_SYSTEM_PROMPT = "You are a spawned worker subagent."

#: A real, registered integration, so ``get_integration_by_id`` resolves and the
#: provider-metadata and custom-instructions sections are genuinely reachable
#: rather than short-circuiting on an unknown id.
PROVIDER_INTEGRATION_ID = "gmail"
PROVIDER_AGENT_NAME = "gmail_agent"

#: The agent name each tier runs under. Only affects visibility metadata and the
#: skills lookup key, but both are real inputs to what the tier ends up seeing.
_AGENT_NAMES = {
    AgentTier.COMMS: "comms_agent",
    AgentTier.EXECUTOR: "executor_agent",
    AgentTier.PROVIDER_SUBAGENT: PROVIDER_AGENT_NAME,
    AgentTier.SPAWN: "spawn_agent",
    AgentTier.WORKFLOW_AUTHORING: "workflow_agent",
}


@dataclass(frozen=True)
class HarnessUser:
    """The per-user facts every tier's context is built from."""

    user_id: str = "user-alpha"
    name: str = "Ada"
    email: str = "ada@example.com"
    timezone: str = "Asia/Kolkata"
    preferences: dict[str, Any] = field(default_factory=dict)
    writing_style: dict[str, Any] = field(default_factory=dict)


def slots_of(messages: list[AnyMessage]) -> list[PromptSlot]:
    """The slot sequence of an array.

    Assertions read as slot sequences rather than message indices: an index
    shifts whenever any unrelated message is added, so an index-based assertion
    breaks for reasons that have nothing to do with what it claims to pin.
    """
    return [slot_of(message) for message in messages]


def message_in_slot(messages: list[AnyMessage], slot: PromptSlot) -> AnyMessage | None:
    """The single message occupying ``slot``, or ``None``.

    Raises when a singleton slot holds more than one message — that is the
    collapse invariant failing, and silently returning the first would hide it.
    """
    found = [message for message in messages if slot_of(message) is slot]
    if len(found) > 1:
        raise AssertionError(f"{slot.name} is a singleton slot but holds {len(found)} messages")
    return found[0] if found else None


def text_of(message: AnyMessage | None) -> str:
    if message is None:
        return ""
    return message.content if isinstance(message.content, str) else str(message.content)


def request_bytes(messages: list[AnyMessage]) -> str:
    """The array as the byte sequence a provider's prefix cache matches on.

    An approximation of the wire request, not a reproduction of it — providers
    add their own framing. What it reproduces faithfully is the part that
    matters: message order and content, concatenated, so a byte that moves in
    the array moves here too.
    """
    return "\n".join(f"{message.type}:{text_of(message)}" for message in messages)


def common_prefix_len(first: str, second: str) -> int:
    """How many leading bytes two requests share — what the cache can reuse."""
    limit = min(len(first), len(second))
    for index in range(limit):
        if first[index] != second[index]:
            return index
    return limit


def hooks_for(tier: AgentTier) -> list[HookType]:
    """That tier's real pre-model hook chain, from the builders the graphs use."""
    if tier is AgentTier.COMMS:
        return comms_pre_model_hooks()
    if tier in (AgentTier.SPAWN, AgentTier.WORKFLOW_AUTHORING):
        # A spawn owns no todo list; the workflow author is authoring-only and
        # must not plan or execute. Neither wires the todo hook.
        return worker_pre_model_hooks()
    source = "executor" if tier is AgentTier.EXECUTOR else PROVIDER_INTEGRATION_ID
    return worker_pre_model_hooks(cast(HookType, create_todo_pre_model_hook(source=source)))


async def build_configurable(
    tier: AgentTier,
    user: HarnessUser,
    overrides: AgentConfigurable | None = None,
) -> tuple[RunnableConfig, AgentConfigurable]:
    """The run config a tier would carry, with ``overrides`` applied last.

    Overrides land on the finished bag rather than riding in as a parent
    configurable, so a test can also *remove* a key (``{"vfs_session_id": None}``)
    — inheritance only ever fills blanks and could not express that.

    Passes ``user_preferences``/``writing_style`` straight into
    ``build_agent_config`` the way every real root call site does (comms,
    background narration, the dev direct-invoke entrypoint) — the harness
    always builds as if it IS that root, so it must feed the same data a real
    one would rather than leaving worker tiers looking blind to it.
    """
    agent_user: AgentUserContext = {
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "timezone": user.timezone,
    }
    config = await build_agent_config(
        identity=AgentIdentity(
            conversation_id="conv-1",
            user=agent_user,
            agent_name=_AGENT_NAMES[tier],
        ),
        thread=AgentThread(
            thread_id=f"{tier.value}-thread",
            subagent_id=_AGENT_NAMES[tier],
            vfs_session_id="conv-1",
        ),
        turn=AgentTurn(
            user_preferences=user.preferences or None,
            writing_style=user.writing_style or None,
        ),
    )
    configurable: AgentConfigurable = {**agent_configurable(config), **(overrides or {})}
    runnable = cast(RunnableConfig, {**config, "configurable": configurable})
    return runnable, configurable


async def seed_context(
    tier: AgentTier,
    *,
    user: HarnessUser,
    query: str,
    configurable: AgentConfigurable,
) -> list[AnyMessage]:
    """The array a tier hands LangGraph, before any hook has run.

    Each branch mirrors its production call site's arguments — a divergence here
    would make every downstream assertion describe a tier that does not exist.
    """
    if tier is AgentTier.COMMS:
        return await _seed_comms(user=user, query=query, configurable=configurable)

    if tier is AgentTier.EXECUTOR:
        return await build_initial_messages(
            system_message=SystemMessage(content=EXECUTOR_PROMPT_TEMPLATE),
            agent_name="executor_agent",
            task=query,
            seed=ThreadSeed(
                tier=AgentTier.EXECUTOR, configurable=configurable, user_id=user.user_id
            ),
        )

    if tier is AgentTier.PROVIDER_SUBAGENT:
        return await build_initial_messages(
            system_message=await create_subagent_system_message(
                integration_id=PROVIDER_INTEGRATION_ID
            ),
            agent_name=PROVIDER_AGENT_NAME,
            task=query,
            seed=ThreadSeed(
                tier=AgentTier.PROVIDER_SUBAGENT,
                configurable=configurable,
                user_id=user.user_id,
                subagent_id=PROVIDER_AGENT_NAME,
                integration_id=PROVIDER_INTEGRATION_ID,
            ),
        )

    if tier is AgentTier.SPAWN:
        return await build_initial_messages(
            system_message=SystemMessage(content=SPAWN_SYSTEM_PROMPT),
            agent_name="spawn_agent",
            task=f"Task:\n{query}",
            seed=ThreadSeed(
                tier=AgentTier.SPAWN,
                configurable=configurable,
                user_id=user.user_id,
                retrieval_query=query,
            ),
        )

    return await _seed_workflow(user=user, query=query, configurable=configurable)


async def _seed_comms(
    *, user: HarnessUser, query: str, configurable: AgentConfigurable
) -> list[AnyMessage]:
    history: list[MessageDict] = [cast(MessageDict, {"role": "user", "content": query})]
    user_dict = cast(
        AuthenticatedUser,
        {
            "timezone": user.timezone,
            "onboarding": {
                "preferences": user.preferences,
                "writing_style": user.writing_style,
            },
        },
    )
    return await construct_langchain_messages(
        messages=history,
        user_id=user.user_id,
        user_name=user.name,
        user_dict=user_dict,
        query=query,
        conversation_id="conv-1",
        source=configurable.get("conversation_source"),
        active_todo_id=configurable.get("active_todo_id"),
        execution_mode=configurable.get("execution_mode") or "interactive",
    )


async def _seed_workflow(
    *, user: HarnessUser, query: str, configurable: AgentConfigurable
) -> list[AnyMessage]:
    """Mirrors the seed built inside ``WorkflowSubagentRunner.execute``."""
    system_message = SystemMessage(
        content=WORKFLOW_AGENT_SYSTEM_PROMPT,
        additional_kwargs={"visible_to": {"workflow_agent"}},
    )
    assembled = await assemble_context(
        SectionContext.from_configurable(
            AgentTier.WORKFLOW_AUTHORING,
            configurable,
            query=query,
            user_id=user.user_id,
        )
    )
    # Through the module so the harness sees the same patched binding production
    # does, rather than a second reference resolved at import time.
    hint = await workflow_subagent.build_connected_integrations_hint(user.user_id)
    human_message = HumanMessage(
        content=f"{hint}\n\n---\n\nRequest: {query}",
        additional_kwargs={"visible_to": {"workflow_agent"}},
    )
    time_message = build_current_time_message(user_timezone=user.timezone)
    return [system_message, *assembled.messages(), human_message, time_message]


def _with_onboarding(sources: ContextSources, prompt: str | None) -> ContextSources:
    return sources if prompt is None else replace(sources, onboarding_prompt=prompt)


@dataclass(frozen=True)
class ContextSeed:
    """What a tier's context is seeded from, beyond the tier itself."""

    user: HarnessUser | None = None
    query: str = "what is on my plate today?"
    sources: ContextSources | None = None
    configurable_overrides: AgentConfigurable | None = None
    now: datetime = FIXED_NOW
    prior_messages: list[AnyMessage] | None = None
    onboarding_prompt: str | None = None


async def effective_context(tier: AgentTier, seed: ContextSeed | None = None) -> list[AnyMessage]:
    """Seed ``tier`` and run it through that tier's real pre-model hooks.

    ``ContextSeed.prior_messages`` are prepended to the seed to model a
    checkpointed thread — the multi-turn shape, where stale copies of each slot
    accumulate and the hook chain has to collapse them.
    """
    spec = seed or ContextSeed()
    resolved_user = spec.user or HarnessUser()
    resolved_sources = _with_onboarding(spec.sources or ContextSources(), spec.onboarding_prompt)

    with (
        time_machine.travel(spec.now, tick=False),
        patch.object(settings, "HOST", FIXED_HOST),
        fake_context_sources(resolved_sources),
    ):
        config, configurable = await build_configurable(
            tier, resolved_user, spec.configurable_overrides
        )
        seed_messages = await seed_context(
            tier, user=resolved_user, query=spec.query, configurable=configurable
        )
        state = cast(
            State, {"messages": [*(spec.prior_messages or []), *seed_messages], "todos": []}
        )
        result = await execute_hooks(hooks_for(tier), state, config, InMemoryStore())
    return list(result["messages"])


async def seed_only(
    tier: AgentTier,
    *,
    user: HarnessUser | None = None,
    query: str = "what is on my plate today?",
    sources: ContextSources | None = None,
    configurable_overrides: AgentConfigurable | None = None,
    now: datetime = FIXED_NOW,
) -> list[AnyMessage]:
    """The pre-hook seed, for the invariants that are about what a tier *emits*."""
    resolved_user = user or HarnessUser()
    with (
        time_machine.travel(now, tick=False),
        patch.object(settings, "HOST", FIXED_HOST),
        fake_context_sources(sources or ContextSources()),
    ):
        _, configurable = await build_configurable(tier, resolved_user, configurable_overrides)
        return await seed_context(tier, user=resolved_user, query=query, configurable=configurable)
