"""Compact ground-truth hint for the workflow assistant.

The workflow assistant authors prompts that name integrations and trigger slugs.
To stay anchored to what the user actually has, it gets ONE compact line of their
connected integrations up front, then calls the discovery tools
(search_integrations, search_integration_tools, search_triggers) for exact ids,
capabilities, and trigger config on demand. This keeps the per-run context small
and the names accurate, instead of injecting the whole catalog every run.
"""

from app.services.integrations.my_integrations import get_my_integrations


async def build_connected_integrations_hint(user_id: str) -> str:
    """Return a compact block naming THIS user's connected integrations."""
    mine = (await get_my_integrations(user_id)).integrations
    connected = [i for i in mine if i.status == "connected"]

    names = ", ".join(f"{i.name} (`{i.id}`)" for i in connected) if connected else "(none yet)"

    return (
        "# Connected integrations (ground truth for THIS user)\n"
        f"{names}\n\n"
        "Build the workflow around what is connected. For exact integration ids, "
        "tool capabilities, or triggers, call search_integrations, "
        "search_integration_tools, and search_triggers; never guess them. Suggest "
        "connecting a not-connected integration only when the user named it and the "
        "workflow cannot run without it."
    )
