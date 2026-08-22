"""Workspace area registry — one descriptor per projected ``/workspace/`` subtree.

GAIA-as-filesystem grows one projection at a time (todos, memory, integrations,
account, …). Every area shares the same contract: a hash-gated ``sync`` that
materializes truth onto JuiceFS, and a fire-and-forget ``schedule_sync`` that
write paths call so the view never lags its source. This registry names them so
provisioning can refresh every area without hardcoding each module — a new area
registers here and is picked up everywhere.

Static docs (GUIDE.md files) are NOT part of an area: they are system files
(``system_files._STATIC_DOCS``), served from memory and symlinked once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import NamedTuple

from app.services.account_fs import schedule_account_sync, sync_account_files


class WorkspaceArea(NamedTuple):
    """One projected workspace subtree."""

    name: str
    sync: Callable[[str], Awaitable[int]]
    schedule_sync: Callable[[str], None]


_AREAS: tuple[WorkspaceArea, ...] = (
    WorkspaceArea(name="account", sync=sync_account_files, schedule_sync=schedule_account_sync),
)


def all_areas() -> tuple[WorkspaceArea, ...]:
    """Every registered area, in registration order."""
    return _AREAS


def get_area(name: str) -> WorkspaceArea | None:
    """The named area, or None."""
    return next((area for area in _AREAS if area.name == name), None)


__all__ = ["WorkspaceArea", "all_areas", "get_area"]
