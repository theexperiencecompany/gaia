"""Agent tools for reading and updating the user's standing instructions.

One pair for every scope: "global" (every conversation) or a connected integration's
id (that integration's work). Writes go through the same service as the settings
page, so the prompt, the projections and the editor all see the same record.
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.core.mutations import user_id_from_config
from app.models.user_instructions_models import GLOBAL_INSTRUCTIONS_SCOPE, InstructionsEditor
from app.services.account_fs import schedule_account_sync
from app.services.user_instructions_service import get_instructions, write_instructions
from app.utils.errors import AppError
from shared.py.wide_events import log

_SCOPE_DESCRIPTION = (
    f"'{GLOBAL_INSTRUCTIONS_SCOPE}' for instructions that apply to every conversation, or a "
    "connected integration's id (e.g. 'slack', 'github', 'linear') for that integration only."
)


@tool
async def get_user_instructions(
    config: RunnableConfig,
    scope: Annotated[str, _SCOPE_DESCRIPTION],
) -> str:
    """Read the user's current standing instructions for one scope.

    Call this before update_user_instructions when amending, so existing guidance is
    kept. Not needed for a scope whose block is already in your context.
    """
    user_id = user_id_from_config(config)
    if not user_id:
        return "Error: user_id not found in config"
    content = await get_instructions(user_id, scope)
    return content or f"No standing instructions set for '{scope}'."


@tool
async def update_user_instructions(
    config: RunnableConfig,
    scope: Annotated[str, _SCOPE_DESCRIPTION],
    content: Annotated[
        str,
        "The FULL new instructions (replaces the existing text, does not append). "
        "Read the current instructions first when amending. An empty string clears them.",
    ],
) -> str:
    """Save a STABLE preference for how GAIA should behave, for every conversation or one integration.

    Use for lasting preferences ("always reply in Spanish", "for Slack only watch #eng").
    Never for one-off corrections, facts about the user (memory), or ongoing work (tracked todos).
    """
    user_id = user_id_from_config(config)
    if not user_id:
        return "Error: user_id not found in config"
    log.set(tool={"name": "update_user_instructions"})
    try:
        saved = await write_instructions(
            user_id, scope, content, updated_by=InstructionsEditor.AGENT
        )
    except AppError as e:
        return f"Error: {e.message}. {e.fix}".strip()
    if scope == GLOBAL_INSTRUCTIONS_SCOPE:
        schedule_account_sync(user_id)
    if not saved.content:
        return f"Cleared the standing instructions for '{scope}'."
    return (
        f"Saved the standing instructions for '{scope}'. They apply from the next turn "
        "and the user can see and edit them in settings."
    )


tools = [get_user_instructions, update_user_instructions]
