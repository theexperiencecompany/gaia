"""Layer 2 — bash _resolve_cwd: workspace containment + the normpath escape fix."""

from __future__ import annotations

import pytest

from app.agents.tools.coding.bash_tool import _resolve_cwd
from app.agents.workspace.paths import WORKSPACE_ROOT, session_dir

pytestmark = pytest.mark.unit


def test_empty_cwd_with_session_defaults_to_session_root() -> None:
    # `pwd` with no cwd lands in the session ROOT (/workspace/sessions/<conv>),
    # which holds artifacts/, scratch/, user-uploaded/ — NOT inside scratch.
    cwd, use_session, err = _resolve_cwd("", "conv1")
    assert err is None
    assert use_session is True
    assert cwd == session_dir("conv1")
    assert not cwd.endswith("/scratch")


def test_workspace_root_cwd_with_session_defaults_to_session_root() -> None:
    cwd, use_session, err = _resolve_cwd(WORKSPACE_ROOT, "conv1")
    assert err is None
    assert use_session is True
    assert cwd == session_dir("conv1")


def test_valid_subdir_passes_through_normalized() -> None:
    cwd, use_session, err = _resolve_cwd("/workspace/sessions/c/scratch", "c")
    assert err is None
    assert use_session is False
    assert cwd == "/workspace/sessions/c/scratch"


@pytest.mark.parametrize(
    "escape",
    [
        "/workspace/../etc/gaia",
        "/workspace/sessions/../../etc",
        "/workspace/a/../../root",
        "/etc/gaia",
    ],
)
def test_dotdot_escape_is_rejected_after_normalization(escape: str) -> None:
    # The bug: is_under_workspace("/workspace/../etc") was True on the raw
    # string (startswith "/workspace/"), then the shell resolved `..` and
    # escaped. _resolve_cwd must normpath BEFORE the containment check.
    cwd, use_session, err = _resolve_cwd(escape, "c")
    assert err is not None, f"{escape!r} must be rejected — it escapes /workspace"
    assert "must be under" in err


def test_relative_cwd_joins_to_session_dir_like_read_and_write() -> None:
    # read/write (canonical_path) join a relative path to the session dir, so
    # `cwd="scratch"` must mean the session's scratch — not be rejected. bash
    # used to error here, breaking the agent's session-relative mental model.
    cwd, use_session, err = _resolve_cwd("scratch", "conv1")
    assert err is None, f"a relative cwd must be accepted, got error: {err!r}"
    assert cwd == f"{session_dir('conv1')}/scratch"


def test_relative_cwd_without_session_joins_to_workspace_root() -> None:
    cwd, use_session, err = _resolve_cwd("sub/dir", None)
    assert err is None
    assert cwd == f"{WORKSPACE_ROOT}/sub/dir"


def test_relative_cwd_escape_still_rejected() -> None:
    # Joining must not open an escape: a relative `../` that climbs out of the
    # workspace after the join is still rejected.
    _, _, err = _resolve_cwd("../../../../etc", "conv1")
    assert err is not None and "must be under" in err


def test_no_session_no_cwd_defaults_to_workspace_root_downstream() -> None:
    # No session and no cwd: not a session-scratch case, no error; caller
    # falls back to WORKSPACE_ROOT.
    cwd, use_session, err = _resolve_cwd("", None)
    assert err is None
    assert use_session is False
