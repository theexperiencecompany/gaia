"""Per-turn workspace upkeep.

:func:`schedule_last_active_touch` is the only workspace work a chat turn does —
a fire-and-forget bump of the session's ``last_active`` so the daily idle-prune
doesn't reap an actively-used conversation. The heavy per-user materialization
(system files, skill/instruction catalog, integration tree) is event-driven
elsewhere: registration, integration connect/disconnect, and startup. Session
dirs are created at conversation creation
(:func:`app.services.chat.persistence.initialize_new_conversation`).

Artifact-event forwarding lives in :mod:`app.services.chat.artifact_forwarder`.
"""

import asyncio

from app.constants.log_tags import LogTag
from app.services.storage import JuiceFSUnavailable, touch_session_last_active
from shared.py.wide_events import log

_last_active_tasks: set[asyncio.Task[None]] = set()


def schedule_last_active_touch(user_id: str, conversation_id: str) -> None:
    """Fire-and-forget bump of the session's ``last_active`` for idle-prune.

    Non-blocking; soft-fails when JuiceFS is unmounted (dev).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _touch() -> None:
        try:
            await touch_session_last_active(user_id, conversation_id)
        except JuiceFSUnavailable:
            return  # dev mode — no mount, nothing to touch
        except Exception as e:  # noqa: BLE001 — last_active bump must not affect chat
            log.warning(f"{LogTag.CHAT} last_active touch failed: {e}")

    task = loop.create_task(_touch())
    _last_active_tasks.add(task)
    task.add_done_callback(_last_active_tasks.discard)
