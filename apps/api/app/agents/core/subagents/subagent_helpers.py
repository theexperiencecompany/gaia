"""Resolution of a subagent's STATIC system prompt.

The prompt is byte-identical across users so the implicit prompt cache hits on
every subagent invocation. Everything per-user — provider metadata, custom
instructions, memories — is assembled separately by ``app.agents.context`` and
delivered in its own messages, deliberately not in this string.
"""

from langchain_core.messages import SystemMessage

from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.prompts.custom_mcp_prompts import CUSTOM_MCP_SUBAGENT_PROMPT
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


async def build_subagent_system_prompt(
    integration_id: str,
    base_system_prompt: str | None = None,
) -> str:
    """Return the STATIC subagent system prompt."""
    subagent = get_subagent_by_id(integration_id) if integration_id else None
    if not subagent:
        # Custom or public MCP fallback — universal prompt; no per-user injection.
        if integration_id:
            return base_system_prompt or CUSTOM_MCP_SUBAGENT_PROMPT
        log.warning(f"{LogTag.AGENT} Integration not found", integration_id=integration_id)
        return base_system_prompt or ""

    return base_system_prompt or subagent.config.system_prompt or ""


async def create_subagent_system_message(
    integration_id: str,
    base_system_prompt: str | None = None,
) -> SystemMessage:
    """Return the static subagent prompt as a SystemMessage."""
    system_prompt = await build_subagent_system_prompt(
        integration_id=integration_id,
        base_system_prompt=base_system_prompt,
    )
    return SystemMessage(content=system_prompt)
