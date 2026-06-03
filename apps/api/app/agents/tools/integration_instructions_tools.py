"""Agent tools for reading and updating per-integration custom instructions.

These let the agent persist a user's durable preferences for an integration
("for Slack, focus on #eng, #design, #pm") so they survive across sessions.
Writes go through the MongoDB source of truth exactly like
``update_tracked_todo_canvas`` writes a todo's canvas — the read-only VFS
projection and the subagent's context block both re-derive from it.

Available to the executor and to every subagent. A subagent already has its own
instructions injected into context, so it can call ``update_integration_instructions``
directly; the executor should ``get_integration_instructions`` first when it
intends to edit an existing block rather than replace it wholesale.
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.models.integration_instructions_models import InstructionsEditor
from app.services.integration_instructions_service import (
    get_instructions,
    upsert_instructions,
)
from app.services.integrations.user_integrations import check_user_has_integration
from app.services.storage.juicefs import ensure_safe_path_id
from shared.py.wide_events import log


@tool
async def get_integration_instructions(
    config: RunnableConfig,
    integration_id: Annotated[
        str,
        "Integration id whose instructions to read (e.g. 'slack', 'github', 'linear').",
    ],
) -> str:
    """Read the user's current custom instructions for one integration.

    Call this before update_integration_instructions when you intend to amend
    existing guidance (so you preserve what's already there). A subagent does
    NOT need this for its own integration — its instructions are already in
    context.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    content = await get_instructions(user_id, integration_id)
    if not content:
        return f"No custom instructions set for '{integration_id}'."
    return content


@tool
async def update_integration_instructions(
    config: RunnableConfig,
    integration_id: Annotated[
        str,
        "Integration id to update (e.g. 'slack', 'github', 'linear'). For a "
        "subagent, this is your own integration.",
    ],
    content: Annotated[
        str,
        "The FULL new instructions markdown (this replaces the existing content, "
        "it does not append). Read the current instructions first if you are "
        "amending rather than rewriting.",
    ],
) -> str:
    """Persist the user's durable preferences for how an integration should be used.

    Use when the user expresses a STABLE preference — focus areas, default
    targets, conventions ("always cc me", "default to the Backend project").
    Do NOT use for one-off, task-specific corrections; those belong in the
    current turn, not in persistent instructions.

    The content is the full replacement body. It is saved to the user's account,
    surfaced to the matching subagent on every future turn, and mirrored to
    integrations/<id>/agent/instructions.md.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    if not integration_id:
        return "Error: integration_id is required."

    try:
        ensure_safe_path_id(integration_id, label="integration_id")
    except ValueError:
        return (
            f"Error: invalid integration_id '{integration_id}'. Use a connected "
            "integration's id (letters, numbers, hyphens, and underscores only)."
        )

    if not await check_user_has_integration(user_id, integration_id):
        return (
            f"Error: '{integration_id}' is not one of this user's connected integrations, "
            "so it has no instructions to update. Only set instructions for an integration "
            "the user has actually added."
        )

    log.set(tool={"name": "update_integration_instructions"}, integration={"id": integration_id})
    await upsert_instructions(
        user_id=user_id,
        integration_id=integration_id,
        content=content,
        updated_by=InstructionsEditor.AGENT,
    )
    return (
        f"Saved custom instructions for '{integration_id}'. They will guide every "
        f"future {integration_id} task and are visible to the user on the integration page."
    )


tools = [get_integration_instructions, update_integration_instructions]
