"""Host-side session workspace helpers.

Split by concern:
  * :mod:`.meta` — ``.meta.json`` read/write + ``last_active`` parsing.
  * :mod:`.skills` — SKILL.md catalog + user-root INDEX/GUIDE materialization.
  * :mod:`.artifacts` — artifact / user-uploaded listing, stat, path resolve, pin.
  * :mod:`.lifecycle` — bootstrap / dirs / delete / touch / stale-scan / list.

Public API is unchanged from the pre-split ``sessions.py``; downstream callers
should keep importing from :mod:`app.services.storage` (or this package) and
let the package-level re-exports stay stable.
"""

from app.services.storage.sessions.artifacts import (
    ArtifactInfo,
    list_artifacts,
    list_user_uploaded,
    pin_session_artifact,
    resolve_session_path,
    stat_artifact,
)
from app.services.storage.sessions.lifecycle import (
    chmod_path,
    delete_session_dir,
    ensure_session_dirs,
    list_session_ids,
    list_stale_sessions,
    materialize_user_integrations,
    provision_user_workspace,
    touch_session_last_active,
)

__all__ = [
    "ArtifactInfo",
    "chmod_path",
    "delete_session_dir",
    "ensure_session_dirs",
    "list_artifacts",
    "list_session_ids",
    "list_stale_sessions",
    "list_user_uploaded",
    "materialize_user_integrations",
    "pin_session_artifact",
    "provision_user_workspace",
    "resolve_session_path",
    "stat_artifact",
    "touch_session_last_active",
]
