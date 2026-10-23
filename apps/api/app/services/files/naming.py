"""Workspace names for uploaded files."""

from app.agents.workspace.paths import safe_upload_filename


def workspace_upload_name(file_id: str, filename: str) -> str:
    """Return a collision-free name for an upload inside user-uploaded/.

    Two distinct files can share a display name (image.png), so prefixing the
    file id keeps their workspace paths distinct: one can never overwrite the
    other. The suffix is capped so the full component stays under 255 bytes.
    """
    safe = safe_upload_filename(filename)
    return f"{file_id}_{safe[: 255 - len(file_id) - 1]}"
