"""What HIL should do about one tool call — before anything is asked, judged, or run.

This module answers two questions and nothing else, so the gate can stay about acting:

1. **Is this tool gated?** ``is_gated`` — the user's per-tool override, else the
   destructive classification. This set is identical in both gating modes.
2. **What happens to the gated set?** ``resolve_policy`` — ``ask`` (confirm with the
   user) or ``auto`` (let the intent judge decide). ``always_allow`` gates nothing.

Plus one guard that belongs with the policy because it *suppresses* auto-approval:
``has_pausing_sibling`` — see its docstring for the double-execution it prevents.
"""

from typing import Literal

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.tools import BaseTool

from app.agents.tools.core.registry import get_tool_registry
from app.constants.hil import HIL_EXEMPT_TOOLS, HIL_PAUSING_TOOLS
from app.constants.log_tags import LogTag
from app.models.hil_models import HIL_DEFAULT_MODE, HILPreferences
from app.services.hil.classification import is_tool_destructive, mcp_destructive_hint
from app.services.hil.preferences import get_hil_preferences
from app.services.hil.utils import current_tool_calls, tool_of
from shared.py.wide_events import log

# What the gate does with one call:
#   allow — run it without asking
#   ask   — pause and put it to the user
#   auto  — let the intent judge choose between the two
GatingPolicy = Literal["allow", "ask", "auto"]


async def resolve_policy(request: ToolCallRequest, user_id: str, tool_name: str) -> GatingPolicy:
    """The user's mode plus the gated set, resolved into one decision."""
    prefs = await _preferences(user_id)
    if prefs.mode == "always_allow":
        return "allow"
    if not await is_gated(prefs, tool_name, tool_of(request)):
        return "allow"
    return "auto" if prefs.mode == "auto" else "ask"


async def is_gated(prefs: HILPreferences, tool_name: str, tool: BaseTool | None) -> bool:
    """Whether this tool needs approval — the set both gating modes act on.

    A user's explicit per-tool choice wins over the classifier in both directions — even
    over an MCP destructiveHint — since it is a deliberate setting on their own account.
    """
    override = prefs.tool_overrides.get(tool_name)
    if override is not None:
        return override
    return await is_tool_destructive(
        tool_name,
        getattr(tool, "description", "") or "",
        destructive_hint=mcp_destructive_hint(tool),
    )


async def has_pausing_sibling(request: ToolCallRequest, user_id: str, tool_call_id: str) -> bool:
    """Whether another call in this same AI message can pause the run.

    If one can, this call cannot simply run and be done with it. The sibling will
    ``interrupt()``, and LangGraph discards the writes of every task in that step and
    replays them on resume — so a handler that ran before the pause runs a second time
    (verified: one send became two). Two callers act on that:

    * **auto mode** does not auto-approve, because a call it approved would run before
      the pause and then again on the replay. Auto-approval therefore applies only when
      a call is the turn's only pausing action; several destructive actions in one turn
      are confirmed together, which is the behaviour worth having anyway.
    * **an ungated call** remembers its result under its tool_call_id, so the replay
      reuses it rather than repeating the work (``gate._run_once_across_replays``).

    A sibling pauses in one of two ways. It is **gated**, and pauses at its own gate:
    siblings arrive as bare tool-call dicts, so each one's tool object is resolved from
    the registry, because classifying it must use the same description and MCP
    ``destructiveHint`` its own gate will use. Classifying without them (a bare name, an
    empty description) both under-detects the sibling — defeating the double-run guard
    this exists for — and poisons the registry's name-keyed ``destructive`` flag, since an
    unclassified tool's verdict is written back there for every later gate check to read.

    Or it is **exempt but pausing** (``HIL_PAUSING_TOOLS``) — ``handoff`` bubbles up its
    subagent's gate interrupt, ``wait_for_subagents`` interrupts for the parked-approval
    batch. Neither is ever gated, so skipping them as exempt would leave exactly the
    double-run this guard exists to prevent. Checked first, and by name alone, so the
    common case costs no preference or registry lookup.
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

    prefs = await get_hil_preferences(user_id)
    if prefs.mode == "always_allow":
        # HIL is off for this user, so no sibling gate can pause. Answered before the
        # per-sibling classification below because every ungated call now asks this
        # (see gate._run_once_across_replays) and that is ~100% of traffic.
        return False
    registry = await get_tool_registry()
    for call in siblings:
        name = str(call["name"])
        if name in HIL_EXEMPT_TOOLS:
            continue
        meta = registry.get_tool_meta(name)
        if await is_gated(prefs, name, meta.tool if meta else None):
            return True
    return False


async def _preferences(user_id: str) -> HILPreferences:
    """The user's HIL preferences, or the default when the store is unreachable.

    Failing open here is safe only because HIL is opt-in and unlaunched: a Redis/Mongo
    blip must not gate every tool call for the overwhelmingly common HIL-off user. The
    moment the default becomes a gating mode, this re-raises and the gate fails closed.
    """
    try:
        return await get_hil_preferences(user_id)
    except Exception:
        if HIL_DEFAULT_MODE != "always_allow":
            raise
        log.error(f"{LogTag.HIL} Preferences unavailable; treating HIL as {HIL_DEFAULT_MODE}")
        return HILPreferences()
