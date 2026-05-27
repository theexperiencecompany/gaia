"""
Subagent Helper Functions

Reusable utilities for working with subagents.

Design note: the subagent's STATIC system prompt must be byte-identical across
users so the LLM's implicit prompt cache hits. Per-user provider metadata
(GitHub login, Gmail address, etc.) therefore lives in the DYNAMIC context
message emitted alongside the static prompt — not inside the static prompt.
"""

import asyncio
import re

from langchain_core.messages import SystemMessage

from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.prompts.custom_mcp_prompts import CUSTOM_MCP_SUBAGENT_PROMPT
from app.agents.skills.discovery import get_available_skills_text
from app.config.oauth_config import get_integration_by_id
from app.helpers.message_helpers import (
    BACKGROUND_EXECUTION_BANNER,
    DYNAMIC_CONTEXT_MARKER,
    _build_active_todo_banner,
)
from app.services.memory_service import memory_service
from app.services.provider_metadata_service import get_provider_metadata
from shared.py.wide_events import log


async def build_subagent_system_prompt(
    integration_id: str,
    user_id: str | None = None,
    base_system_prompt: str | None = None,
) -> str:
    """Return the STATIC subagent system prompt.

    Per-user provider metadata (username, email, etc.) is NOT injected here —
    it lives in the dynamic-context message built alongside by
    `create_agent_context_message`. Keeping this string independent of user_id
    is what lets the implicit prompt cache hit on subagent invocations.

    The ``user_id`` parameter is accepted for back-compat with existing
    callers; it is intentionally unused.
    """
    del user_id  # retained for signature compat; metadata flows via dynamic context

    subagent = get_subagent_by_id(integration_id) if integration_id else None
    if not subagent:
        # Custom or public MCP fallback — universal prompt; no per-user injection.
        if integration_id:
            return base_system_prompt or CUSTOM_MCP_SUBAGENT_PROMPT
        log.warning(f"Integration {integration_id} not found")
        return base_system_prompt or ""

    return base_system_prompt or subagent.config.system_prompt or ""


async def create_subagent_system_message(
    integration_id: str,
    agent_name: str,
    user_id: str | None = None,
    base_system_prompt: str | None = None,
) -> SystemMessage:
    """Return the static subagent prompt as a SystemMessage.

    ``user_id`` is intentionally unused here; provider metadata for this user
    is carried on the dynamic-context SystemMessage emitted beside this one.
    """
    system_prompt = await build_subagent_system_prompt(
        integration_id=integration_id,
        user_id=user_id,
        base_system_prompt=base_system_prompt,
    )
    return SystemMessage(content=system_prompt)


def _mark_dynamic(msg: SystemMessage) -> SystemMessage:
    msg.additional_kwargs[DYNAMIC_CONTEXT_MARKER] = True
    msg.additional_kwargs.setdefault("memory_message", True)  # back-compat marker
    return msg


async def _fetch_provider_metadata_block(integration_id: str | None, user_id: str | None) -> str:
    """Return the provider-metadata lines for the dynamic context, or ''."""
    if not (integration_id and user_id):
        return ""
    integration = get_integration_by_id(integration_id)
    if not integration or not integration.provider:
        return ""
    try:
        metadata = await get_provider_metadata(user_id, integration.provider)
    except Exception as e:
        log.warning(f"Failed to fetch provider metadata for {integration.provider}: {e}")
        return ""
    if not metadata:
        return ""
    lines = [f"- {k}: {v}" for k, v in metadata.items()]
    return f"\n\nUSER CONTEXT FOR {integration.name.upper()}:\n" + "\n".join(lines) + "\n"


async def create_agent_context_message(
    configurable: dict,
    user_id: str | None = None,
    query: str | None = None,
    subagent_id: str | None = None,
    integration_id: str | None = None,
    memories_text: str | None = None,
    skills_text: str | None = None,
) -> SystemMessage:
    """Build the dynamic-context system message for executor/subagent runs.

    Carries everything that varies per request: user name, current time,
    memories, installable skills, and (for subagents) provider metadata. This
    is the message `manage_system_prompts_node` keeps only the latest of.

    Args:
        configurable: The config["configurable"] dict from RunnableConfig.
        user_id: Optional override; otherwise taken from configurable.
        query: Search query for memory retrieval.
        subagent_id: Subagent ID for skill retrieval (e.g. "twitter", "github").
        integration_id: When invoking a subagent, the underlying integration
            ID — used to look up provider metadata (GitHub login, etc.).
        memories_text: Pre-fetched memories section; if provided, skips
            ChromaDB lookup. Memory fetched by the caller is passed through
            the handoff payload so subagents don't re-run the same search.
        skills_text: Pre-fetched skills section; same rationale as memories.
    """
    parts: list[str] = []

    user_id = user_id or configurable.get("user_id")
    user_name = configurable.get("user_name")
    user_time_str = configurable.get("user_time", "")
    execution_mode = configurable.get("execution_mode") or "interactive"
    active_todo_id = configurable.get("active_todo_id")

    # Background-execution banner — must lead so executor never asks
    # clarifying questions when no human is on the other end.
    if execution_mode == "background":
        parts.append(BACKGROUND_EXECUTION_BANNER)

    # Active-todo banner — pins canvas as default write target for this run.
    if active_todo_id and user_id:
        banner = await _build_active_todo_banner(user_id, active_todo_id)
        if banner:
            parts.append(banner)

    if user_name:
        parts.append(f"User Name: {user_name}")

    # Clock is NOT embedded here any more — it lives in a HumanMessage built
    # alongside by ``build_initial_messages`` so the system_instruction stays
    # stable across minute ticks. Only the user's static timezone offset
    # (byte-stable across turns) stays in system_instruction.
    if user_time_str:
        try:
            tz_match = re.search(r"([+-]\d{2}:\d{2}|Z)$", user_time_str)
            if tz_match:
                tz_offset = tz_match.group(1)
                if tz_offset == "Z":
                    tz_offset = "+00:00"
                parts.append(f"User Timezone Offset: {tz_offset}")
        except Exception as e:
            log.warning(f"Error parsing user_time: {e}")

    async def _fetch_memories() -> str:
        if memories_text is not None:
            return memories_text
        if not (user_id and query):
            return ""
        try:
            results = await memory_service.search_memories(query=query, user_id=user_id, limit=5)
            if results and (memories := getattr(results, "memories", None)):
                log.info(f"Added {len(memories)} memories to subagent context")
                return "\n\nBased on our previous conversations:\n" + "\n".join(
                    f"- {mem.content}" for mem in memories
                )
        except Exception as e:
            log.warning(f"Error retrieving memories for subagent: {e}")
        return ""

    async def _fetch_skills() -> str:
        from app.agents.workspace.system_docs import integration_skills_block

        block = ""
        if skills_text is not None:
            block = skills_text or ""
        elif user_id:
            try:
                agent_for_skills = subagent_id or "executor"
                text = await get_available_skills_text(user_id=user_id, agent_name=agent_for_skills)
                if text:
                    log.info(f"Injected installable skills for {agent_for_skills}")
                    block = text
            except Exception as e:
                log.warning(f"Error injecting installable skills: {e}")

        if subagent_id:
            integration_block = integration_skills_block(subagent_id)
            if integration_block:
                block = f"{block}\n\n{integration_block}" if block else integration_block

        return f"\n\n{block}" if block else ""

    memories_section, skills_section, metadata_section = await asyncio.gather(
        _fetch_memories(),
        _fetch_skills(),
        _fetch_provider_metadata_block(integration_id, user_id),
    )

    content = "\n".join(parts) + memories_section + skills_section + metadata_section
    return _mark_dynamic(SystemMessage(content=content))
