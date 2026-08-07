"""Project uploads and their summaries into the session's JuiceFS workspace.

These writes are always best-effort: Cloudinary is the durable copy and Mongo
holds the authoritative metadata, so a missing mount (native dev) or any write
failure must never fail the upload. The agent reads files from the returned
`/workspace/...` paths.
"""

import contextlib

from app.agents.workspace.paths import USER_UPLOADED_DIRNAME
from app.services.artifact_events import publish_artifact_event, upload_event
from app.services.storage import (
    FsOps,
    JuiceFSUnavailable,
    chmod_path,
    fs_timer,
    session_root,
    write_session_file,
)
from shared.py.wide_events import log

_READ_ONLY = 0o444
_WRITABLE = 0o644


async def _overwrite_read_only(user_id: str, conversation_id: str, relative_path: str) -> None:
    """Make a prior read-only copy writable so a re-upload (last-writer-wins) can replace it."""
    prior = session_root(user_id, conversation_id) / relative_path
    with contextlib.suppress(Exception):
        if prior.exists():
            await chmod_path(prior, _WRITABLE)


async def mirror_upload(
    user_id: str,
    conversation_id: str,
    safe_filename: str,
    content: bytes,
    content_type: str,
) -> str | None:
    """Mirror an upload into the session's read-only `user-uploaded/` dir.

    Returns the `/workspace/...` path the agent can read, or None when JuiceFS
    is unavailable / the write fails.
    """
    relative_path = f"{USER_UPLOADED_DIRNAME}/{safe_filename}"
    try:
        async with fs_timer(FsOps.UPLOAD_PERSIST_SANDBOX):
            await _overwrite_read_only(user_id, conversation_id, relative_path)
            host_path, sandbox_path = await write_session_file(
                user_id=user_id,
                conversation_id=conversation_id,
                relative_path=relative_path,
                content=content,
            )
            await chmod_path(host_path, _READ_ONLY)
    except JuiceFSUnavailable as e:
        log.warning(f"[files] juicefs unavailable; not mirroring upload: {e}")
        return None
    except Exception as e:
        log.error(f"[files] failed to mirror upload to sandbox: {e!s}", exc_info=True)
        return None

    # Cross-mount host writes may not reach the sandbox watcher; publish the
    # artifact event directly so the chat UI sees the upload immediately.
    await publish_artifact_event(
        user_id,
        upload_event(
            conversation_id,
            safe_filename,
            size_bytes=len(content),
            content_type=content_type,
        ),
    )
    log.info(f"[files] mirrored upload to {sandbox_path}")
    return sandbox_path


async def write_summary_sidecar(
    user_id: str,
    conversation_id: str,
    safe_filename: str,
    summary_md: str,
) -> None:
    """Write a file's full summary to its `<file>.summary.md` sidecar.

    Best-effort, mirroring `mirror_upload`: the inline summary in the agent
    context comes from Mongo independently, so a failure here is non-fatal.
    """
    relative_path = f"{USER_UPLOADED_DIRNAME}/{safe_filename}.summary.md"
    try:
        await _overwrite_read_only(user_id, conversation_id, relative_path)
        host_path, _ = await write_session_file(
            user_id=user_id,
            conversation_id=conversation_id,
            relative_path=relative_path,
            content=summary_md.encode("utf-8"),
        )
        await chmod_path(host_path, _READ_ONLY)
        log.info(f"[files] wrote summary sidecar for {safe_filename}")
    except JuiceFSUnavailable:
        return
    except Exception as e:
        log.warning(f"[files] failed to write summary sidecar for {safe_filename}: {e!s}")


__all__ = ["mirror_upload", "write_summary_sidecar"]
