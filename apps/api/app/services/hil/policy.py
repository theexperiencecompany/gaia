"""What HIL should do about one tool call — before anything is asked, judged, or run.

This module answers two questions and nothing else, so the gate can stay about acting:

1. **Is this tool gated?** is_gated — the user's per-tool override, else the
   destructive classification. This set is identical in both gating modes.
2. **What happens to the gated set?** resolve_policy — ask (confirm with the
   user) or auto (let the intent judge decide). always_allow gates nothing.

Plus one guard that belongs with the policy because it *suppresses* auto-approval:
has_pausing_sibling — see its docstring for the double-execution it prevents.
"""

from collections.abc import Mapping
from typing import Any, Literal

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.tools import BaseTool

from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.constants.hil import HIL_EXEMPT_TOOLS, HIL_PAUSING_TOOLS
from app.constants.log_tags import LogTag
from app.models.hil_models import HIL_DEFAULT_MODE, HILPreferences
from app.services.hil.classification import is_tool_destructive, mcp_destructive_hint
from app.services.hil.preferences import get_hil_preferences
from app.services.hil.utils import current_tool_calls, tool_of, unpack_tool_call
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


def _argument_gate_hit(tool_name: str, args: Mapping[str, Any] | None) -> bool:
    required = ARGUMENT_GATED_TOOLS.get(tool_name)
    if not required or not args:
        return False
    return all(args.get(key) == value for key, value in required.items())


async def resolve_policy(request: ToolCallRequest, user_id: str, tool_name: str) -> GatingPolicy:
    """Resolve the user's mode plus the gated set into one decision.

    Forced-ask tools short-circuit BEFORE the preferences read, so they pause
    even when the preference store itself is unreachable (fail closed for the
    calls that must never slip through).
    """
    call = unpack_tool_call(request)
    if await _is_always_gated(tool_name) or _argument_gate_hit(tool_name, call.args):
        return "ask"
    prefs = await _preferences(user_id)
    if prefs.mode == "always_allow":
        return "allow"
    if not await is_gated(prefs, tool_name, tool_of(request)):  # args resolved above
        return "allow"
    return "auto" if prefs.mode == "auto" else "ask"


async def is_gated(
    prefs: HILPreferences,
    tool_name: str,
    tool: BaseTool | None,
    args: Mapping[str, Any] | None = None,
) -> bool:
    """Whether this tool needs approval — the set both gating modes act on.

    The forced-ask stamp and argument gate outrank everything, including a user's
    per-tool override, since they mark product invariants, not classifier opinions.
    Otherwise the user's per-tool choice wins in both directions — even over an
    MCP destructiveHint — since it is a deliberate setting on their own account.
    """
    if await _is_always_gated(tool_name):
        return True
    if _argument_gate_hit(tool_name, args):
        return True
    override = prefs.tool_overrides.get(tool_name)
    if override is not None:
        return override
    return await is_tool_destructive(
        tool_name,
        getattr(tool, "description", "") or "",
        destructive_hint=mcp_destructive_hint(tool),
    )


async def has_pausing_sibling(request: ToolCallRequest, user_id: str, tool_call_id: str) -> bool:
    """Return whether another call in this AI message can pause the run.

    A pause replays the step, so a call that already ran runs twice (one send became two):
    auto mode withholds auto-approval, and ungated calls reuse gate._run_once_across_replays.
    HIL_PAUSING_TOOLS pause by name (checked first); gated siblings are classified with their
    registry tool — a bare name under-detects and poisons the name-keyed destructive flag.
    """
    siblings = [
        call
        for call in current_tool_calls(request.state)
        if call.get("name") and call.get("id") != tool_call_id
    ]
    if not siblings:
        return False
    if any(call["name"] in HIL_PAUSING_TOOLS for call in siblings):
        return True

    # Forced-ask siblings pause even when HIL is off, since the stamp isn't
    # preference-driven — checked before the always_allow fast path below.
    registry = await _stamp_registry()
    for call in siblings:
        name = str(call["name"])
        meta = registry.get_tool_meta(name) if registry else None
        if (meta is not None and meta.always_gate) or _argument_gate_hit(
            name, call.get("args") or None
        ):
            return True

    prefs = await get_hil_preferences(user_id)
    if prefs.mode == "always_allow":
        # HIL is off, so no preference-driven gate can pause; account mutations
        # already asked in the forced-gate scan above regardless of this mode.
        return False
    for call in siblings:
        name = str(call["name"])
        if name in HIL_EXEMPT_TOOLS:
            continue
        meta = registry.get_tool_meta(name) if registry else None
        if await is_gated(prefs, name, meta.tool if meta else None, args=call.get("args") or None):
            return True
    return False


async def _preferences(user_id: str) -> HILPreferences:
    """Return the user's HIL preferences, or the default when the store is unreachable.

    Failing open here is safe only because HIL is opt-in and unlaunched: a Redis/Mongo
    blip must not gate every tool call for the overwhelmingly common HIL-off user. The
    moment the default becomes a gating mode, this re-raises and the gate fails closed.
    """
    try:
        return await get_hil_preferences(user_id)
    except Exception:
        if HIL_DEFAULT_MODE != "always_allow":
            raise
        log.error(
            f"{LogTag.HIL} Preferences unavailable; treating HIL as",
            hil_default_mode=HIL_DEFAULT_MODE,
            user_id=user_id,
        )
        return HILPreferences()
