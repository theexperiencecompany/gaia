"""Workspace layout — session-aware path model for the agent sandbox.

`/workspace` inside every E2B sandbox is a bind-mount of the user's JuiceFS
prefix. This package owns the single source of truth for the directory
convention (sessions, scratch, uploads, artifacts artifacts, runtime logs)
so tools, the upload pipeline, the artifact watcher, and HTTP endpoints all
agree on where things live.
"""

from app.agents.workspace.paths import (
    ARTIFACTS_DIRNAME,
    GAIA_RUNTIME_DIRNAME,
    PINNED_DIRNAME,
    RUNS_DIRNAME,
    SCRATCH_DIRNAME,
    SESSIONS_DIRNAME,
    SETTINGS_DIRNAME,
    SKILLS_DIRNAME,
    USER_UPLOADED_DIRNAME,
    WORKSPACE_ROOT,
    MountRole,
    classify,
    detect_content_type,
    is_under_workspace,
    runs_log_dir,
    session_artifacts,
    session_dir,
    session_scratch,
    session_user_uploaded,
)

__all__ = [
    "GAIA_RUNTIME_DIRNAME",
    "PINNED_DIRNAME",
    "RUNS_DIRNAME",
    "SCRATCH_DIRNAME",
    "SESSIONS_DIRNAME",
    "SETTINGS_DIRNAME",
    "SKILLS_DIRNAME",
    "USER_UPLOADED_DIRNAME",
    "ARTIFACTS_DIRNAME",
    "WORKSPACE_ROOT",
    "MountRole",
    "classify",
    "detect_content_type",
    "is_under_workspace",
    "runs_log_dir",
    "session_dir",
    "session_scratch",
    "session_user_uploaded",
    "session_artifacts",
]
