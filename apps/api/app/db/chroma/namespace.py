"""Per-worktree isolation for ChromaDB collection names.

Every worktree's API points at the same local ChromaDB, and the tool/trigger
stores index by diffing the live collection against their own registry — so
whichever API booted last DELETES the rows it doesn't recognise, and a branch's
tools (e.g. ``browser_task``) silently vanish for the other branch. Suffixing the
collection name with a per-worktree namespace gives each worktree its own
collections, so they stop overwriting each other.

Empty in production (one API, one dedicated Chroma), so prod collection names are
unchanged; ``mise run wt:env`` sets the namespace for a non-main worktree.
"""

from __future__ import annotations

from app.config.settings import get_settings

_SEPARATOR = "__"


def namespaced_collection(name: str) -> str:
    """``name`` suffixed with the configured worktree namespace, or unchanged."""
    namespace = get_settings().CHROMA_COLLECTION_NAMESPACE
    return f"{name}{_SEPARATOR}{namespace}" if namespace else name
