"""Integration → workspace VFS sync glue.

Re-materializes a user's SKILL.md / instructions catalog when their connected
integration set changes (connect or disconnect). Mirrors the gaia-tasks and
user-todos glue modules: a fire-and-forget, hash-gated scheduler keyed on
``user_id`` (see :func:`app.services._vfs_scheduler.make_scheduler`).

Wired into the integration status chokepoints (``update_user_integration_status``
on connect, ``disconnect_integration`` on disconnect) so the workspace reflects
integrations the moment they change — not on the next chat turn.
"""

from __future__ import annotations

from app.services._vfs_scheduler import make_scheduler
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.storage import materialize_user_integrations


async def sync_user_integrations(user_id: str) -> int:
    """Re-materialize the user's integration catalog from the current connected set."""
    await materialize_user_integrations(user_id, await get_connected_integration_ids(user_id))
    return 0


# Fire-and-forget wrapper for the connect/disconnect write paths.
schedule_user_integrations_sync = make_scheduler(
    sync_user_integrations, log_name="integrations_vfs"
)
