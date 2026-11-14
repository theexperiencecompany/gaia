"""What HIL should do about one tool call — before anything is asked, judged, or run.

This module answers two questions and nothing else, so the gate can stay about acting:

1. **Is this tool gated?** is_gated — the user's per-tool override, else the
   destructive classification. This set is identical in both gating modes.
2. **What happens to the gated set?** resolve_policy — ask (confirm with the
   user) or auto (let the intent judge decide). always_allow gates nothing.
"""

from collections.abc import Mapping
from typing import Literal

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.tools import BaseTool

from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.agents.tools.execute.resolver import resolve_tool
from app.constants.log_tags import LogTag
from app.models.hil_models import HILPreferences
from app.services.hil.classification import is_tool_destructive, mcp_destructive_hint
from app.services.hil.preferences import get_hil_preferences
from app.services.hil.tool_key import hil_tool_key, mcp_tool_identity
from app.services.hil.utils import raw_tool_call, tool_of, unpack_tool_call
from shared.py.wide_events import log

# What the gate does with one call: allow it, ask (pause for the user), or auto
# (let the intent judge choose between the two).
GatingPolicy = Literal["allow", "ask", "auto"]

# Tools whose gate depends on an argument value, not just the name: a hit on
# every listed (arg → value) pair forces the ask. ``manage_linked_account``
# mints link URLs freely but disconnecting an account always confirms.
ARGUMENT_GATED_TOOLS: dict[str, dict[str, object]] = {
    "manage_linked_account": {"action": "disconnect"},
}


async def _stamp_registry() -> ToolRegistry | None:
    """Return the registry the forced-ask stamp is read from, or None when unreachable.

    The stamp only escalates, never clears, so an unreachable registry just means
    "no stamp read" — the rest of the policy still decides. Raising instead took
    the whole gate down: decide_tool_call fails closed on ANY exception, so an
    unregistered provider silently refused every gated tool instead of asking.
    """
    try:
        return await get_tool_registry()
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} tool registry unavailable; reading no forced-ask stamp",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


async def _is_always_gated(tool_name: str) -> bool:
    """Read the registry's forced-ask stamp, checked before any preference lookup."""
    registry = await _stamp_registry()
    if registry is None:
        return False
    meta = registry.get_tool_meta(tool_name)
    return meta is not None and meta.always_gate


def _argument_gate_hit(tool_name: str, args: Mapping[str, object] | None) -> bool:
    required = ARGUMENT_GATED_TOOLS.get(tool_name)
    if not required or not args:
        return False
    return all(args.get(key) == value for key, value in required.items())


async def asks_every_time(tool_name: str, args: Mapping[str, object] | None) -> bool:
    """Whether this call asks in every mode, beyond any per-tool override's reach."""
    return await _is_always_gated(tool_name) or _argument_gate_hit(tool_name, args)


async def gated_tool_object(
    request: ToolCallRequest, user_id: str, tool_name: str
) -> BaseTool | None:
    """Resolve the real BaseTool a classification should read, not the proxy.

    A direct call's request.tool is the tool; an execute-proxied call carries the
    proxy, so the real one is resolved by unwrapped name through dispatch's own
    resolver. Registry-only resolution missed MCP tools and un-materialized
    catalog slugs, letting the classifier guess from a bare name and un-gate it.
    """
    if raw_tool_call(request).name == tool_name:
        return tool_of(request)
    return await _real_tool(user_id, tool_name)


async def _real_tool(user_id: str, tool_name: str) -> BaseTool | None:
    """Return the live tool behind a name, or None when it cannot be resolved.

    Same resilience contract as _stamp_registry: a resolver failure means "no
    tool object read", and classification still decides by name and fails closed.
    decide_tool_call denies the call outright on any exception.
    """
    try:
        resolved = await resolve_tool(user_id, tool_name)
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} tool resolution failed; classifying by name alone",
            tool_name=tool_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
    return resolved.tool if resolved else None


async def gated_tool_key(request: ToolCallRequest, user_id: str, tool_name: str) -> str:
    """Return the HIL key of the real tool behind a gated call (see tool_key)."""
    tool = await gated_tool_object(request, user_id, tool_name)
    return hil_tool_key(tool_name, mcp_tool_identity(tool))


async def resolved_tool_key(user_id: str, tool_name: str) -> str:
    """Return the HIL key of the live tool a name resolves to, for callers without a request."""
    return hil_tool_key(tool_name, mcp_tool_identity(await _real_tool(user_id, tool_name)))


async def resolve_policy(request: ToolCallRequest, user_id: str, tool_name: str) -> GatingPolicy:
    """Resolve the user's mode plus the gated set into one decision.

    Forced-ask tools short-circuit BEFORE the preferences read, so they pause
    even when the preference store itself is unreachable (fail closed for the
    calls that must never slip through).
    """
    call = unpack_tool_call(request)
    if await asks_every_time(tool_name, call.args):
        return "ask"
    prefs = await _preferences(user_id)
    if prefs.mode == "always_allow":
        return "allow"
    tool = await gated_tool_object(request, user_id, tool_name)
    if not await is_gated(prefs, tool_name, tool):  # args resolved above
        return "allow"
    return "auto" if prefs.mode == "auto" else "ask"


async def is_gated(
    prefs: HILPreferences,
    tool_name: str,
    tool: BaseTool | None,
    args: Mapping[str, object] | None = None,
) -> bool:
    """Whether this tool needs approval — the set both gating modes act on.

    The forced-ask stamp and argument gate outrank everything, including a user's
    per-tool override, since they mark product invariants, not classifier opinions.
    Otherwise the user's per-tool choice wins in both directions — even over an
    MCP destructiveHint — since it is a deliberate setting on their own account.
    """
    if await asks_every_time(tool_name, args):
        return True
    mcp_tool = mcp_tool_identity(tool)
    override = prefs.tool_overrides.get(hil_tool_key(tool_name, mcp_tool))
    if override is not None:
        return override
    return await is_tool_destructive(
        tool_name,
        getattr(tool, "description", "") or "",
        destructive_hint=mcp_destructive_hint(tool),
        mcp_tool=mcp_tool,
    )


async def _preferences(user_id: str) -> HILPreferences:
    """Return the user's HIL preferences, or always_ask when they cannot be read.

    Fails closed: an unreadable store must never run a destructive call unasked.
    """
    try:
        return await get_hil_preferences(user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} Preferences unavailable; requiring approval",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return HILPreferences(mode="always_ask")
