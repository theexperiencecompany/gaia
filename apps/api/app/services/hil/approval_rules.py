"""The user's approval rules, set from chat: when one tool or a whole integration asks.

Writes the same per-tool overrides the settings page does, one per tool. An explicit ask
is always stored, since it outranks the mode; a "don't ask" is stored only where the tool
would otherwise ask, so the page shows exactly what was said.
"""

from app.agents.tools.core.registry import get_tool_registry
from app.constants.hil import ALWAYS_ASK_TOOLS, ApprovalRule
from app.services.hil.preferences import set_tool_override
from app.services.hil.tool_key import hil_tool_key, mcp_tool_identity
from app.services.tools.tools_service import get_integration_tool_list
from app.utils.errors import AppError

_RULE_PHRASES = {
    ApprovalRule.ASK: "will ask before running",
    ApprovalRule.DONT_ASK: "will run without asking",
    ApprovalRule.DEFAULT: "is back to GAIA's default",
}


async def set_approval_rule(
    user_id: str, *, rule: ApprovalRule, integration: str | None = None, tool: str | None = None
) -> str:
    """Apply rule to every tool of integration, or to tool alone; return what changed."""
    if (integration is None) == (tool is None):
        raise AppError(
            message="Name exactly one of integration or tool",
            fix="Pass integration (e.g. 'notion') for all its tools, or tool for one",
            status_code=400,
        )
    targets = await _integration_targets(integration) if integration else await _tool_target(tool)
    for key, destructive in targets:
        await set_tool_override(user_id, key, _override(rule, destructive=destructive))
    subject = f"{integration} ({len(targets)} tools)" if integration else str(tool)
    return f"Approval rule saved: {subject} {_RULE_PHRASES[rule]}."


def _override(rule: ApprovalRule, *, destructive: bool | None) -> bool | None:
    """Return the override to store; None clears it.

    ASK is never cleared, even on a tool that asks by default: with no override stored,
    always_allow runs it and auto lets the judge run it.
    """
    match rule:
        case ApprovalRule.ASK:
            return True
        case ApprovalRule.DONT_ASK:
            return None if destructive is False else False
        case ApprovalRule.DEFAULT:
            return None


async def _integration_targets(integration: str) -> list[tuple[str, bool | None]]:
    tools = await get_integration_tool_list(integration)
    if not tools:
        raise AppError(
            message=f"No tools found for integration '{integration}'",
            fix="Use the integration's id as listed in the user's connected integrations",
            status_code=404,
        )
    return [(t.approval_key, t.destructive) for t in tools if t.name not in ALWAYS_ASK_TOOLS]


async def _tool_target(name: str | None) -> list[tuple[str, bool | None]]:
    if name in ALWAYS_ASK_TOOLS:
        raise AppError(
            message=f"{name} always asks; no rule can change that",
            why="it changes the user's account or rules, so it always needs their yes",
            status_code=400,
        )
    meta = (await get_tool_registry()).get_tool_meta(name or "")
    if meta is None:
        raise AppError(message=f"Unknown tool '{name}'", status_code=404)
    return [(hil_tool_key(meta.name, mcp_tool_identity(meta.tool)), meta.destructive)]
