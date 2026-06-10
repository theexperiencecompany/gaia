"""Per-session host paths.

Internal-to-the-``sessions`` package. The two helpers here are split out so
every sub-module (lifecycle, artifacts, skills) can derive paths from the
JuiceFS mount without re-importing the underscore-prefixed primitives from
``app.services.storage.juicefs`` themselves. Both go through
``session_root`` / ``_mount_root`` so the safety contract (mount-required +
id-validated) is enforced exactly once.
"""

from __future__ import annotations

from pathlib import Path

from app.services.storage.juicefs import (
    _mount_root,
    _require_mount,
    session_root,
)


def session_base(user_id: str, conv_id: str) -> Path:
    """Validated session path; raises ``JuiceFSUnavailable`` if unmounted."""
    _require_mount()
    return session_root(user_id, conv_id)


def user_root(user_id: str) -> Path:
    """Host path for a user's workspace root, without mount-readiness check."""
    return _mount_root() / "users" / user_id
