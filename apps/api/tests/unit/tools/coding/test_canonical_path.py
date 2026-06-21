"""Layer 2 — canonical_path: the workspace-containment security gate.

read/write/edit all route the LLM-supplied path through canonical_path before
touching the filesystem. A path that escapes /workspace must be rejected; a
relative path joins to the session.
"""

from __future__ import annotations

import pytest

from app.agents.tools.coding._context import canonical_path
from app.agents.workspace.paths import WORKSPACE_ROOT, session_dir

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "escape",
    [
        "../../../etc/passwd",  # climbs out of /workspace
        "/etc/gaia/mount.sh",  # absolute host path
        "/etc/passwd",
        "/workspace/../etc/shadow",  # slips past a naive startswith check
        "/",  # the root, not under /workspace
    ],
)
def test_paths_escaping_workspace_are_rejected(escape: str) -> None:
    with pytest.raises(ValueError, match="escapes"):
        canonical_path(escape, session_id="c1")


def test_containment_is_workspace_wide_not_session_scoped() -> None:
    # BY DESIGN, the gate enforces /workspace, NOT the session: the sandbox is
    # per-USER, and a user reaches their own cross-session dirs (user-uploaded/,
    # pinned/, .system/, other conversations) — the same access bash cwd already
    # has. So `..` resolving up to /workspace/sessions is valid, not a leak.
    # This test exists so that behavior isn't later "fixed" as a vulnerability.
    up, _, _ = canonical_path("..", session_id="c1")
    assert up == "/workspace/sessions"
    other, _, conv = canonical_path("../other/scratch/x", session_id="c1")
    assert other == "/workspace/sessions/other/scratch/x"
    assert conv == "other"  # cross-session within the same user is allowed


def test_relative_path_joins_to_session_dir() -> None:
    abs_path, _, _ = canonical_path("scratch/out.txt", session_id="c1")
    assert abs_path == f"{session_dir('c1')}/scratch/out.txt"


def test_relative_path_without_session_joins_to_workspace_root() -> None:
    abs_path, _, _ = canonical_path("notes.md", session_id=None)
    assert abs_path == f"{WORKSPACE_ROOT}/notes.md"


def test_intra_workspace_dotdot_normalizes_without_escaping() -> None:
    # `foo/../bar` resolves WITHIN the workspace — allowed, normalized.
    abs_path, _, _ = canonical_path("foo/../bar.txt", session_id="c1")
    assert abs_path == f"{session_dir('c1')}/bar.txt"
    assert abs_path.startswith(WORKSPACE_ROOT)


def test_empty_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="required"):
        canonical_path("", session_id="c1")
