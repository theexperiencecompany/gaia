"""Project uploads and their summaries into the session's JuiceFS workspace.

These writes are always best-effort: Cloudinary is the durable copy and Mongo
holds the authoritative metadata, so a missing mount (native dev) or any write
failure must never fail the upload. The agent reads files from the returned
/workspace/... paths.
"""

import asyncio
import contextlib

from app.agents.workspace.paths import USER_UPLOADED_DIRNAME
from app.services.artifact_events import publish_artifact_event, remove_event, upload_event
from app.services.storage import (
    FsOps,
    JuiceFSUnavailable,
    chmod_path,
    fs_timer,
    sandbox_session_path,
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
    """Mirror an upload into the session's read-only user-uploaded/ dir.

    Returns the /workspace/... path the agent can read, or None when JuiceFS
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
        log.warning(
            "[files] juicefs unavailable; not mirroring upload",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return None
    except Exception as e:
        log.error(
            "[files] failed to mirror upload to sandbox",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
            exc_info=True,
        )
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
    log.info("[files] mirrored upload to", sandbox_path=sandbox_path)
    return sandbox_path


async def write_summary_sidecar(
    user_id: str,
    conversation_id: str,
    safe_filename: str,
    summary_md: str,
) -> None:
    """Write a file's full summary to its <file>.summary.md sidecar.

    Best-effort, mirroring mirror_upload: the inline summary in the agent
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
        log.info("[files] wrote summary sidecar for", safe_filename=safe_filename)
    except JuiceFSUnavailable:
        return
    except Exception as e:
        log.warning(
            "[files] failed to write summary sidecar for",
            safe_filename=safe_filename,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )


__all__ = ["mirror_upload", "write_summary_sidecar"]


async def rename_upload(
    user_id: str,
    conversation_id: str,
    old_name: str,
    new_name: str,
    *,
    content_type: str,
    size_bytes: int,
) -> str | None:
    """Rename an upload and its summary sidecar in the workspace.

    Returns the new /workspace path, or None when the source is missing or the
    mount is unavailable. Best-effort like mirror_upload: a missing copy never
    fails the metadata update.
    """
    base = session_root(user_id, conversation_id)
    old_host = base / USER_UPLOADED_DIRNAME / old_name
    new_host = base / USER_UPLOADED_DIRNAME / new_name
    try:
        async with fs_timer(FsOps.UPLOAD_PERSIST_SANDBOX):
            if not await asyncio.to_thread(old_host.exists):
                return None
            await chmod_path(old_host, _WRITABLE)
            await asyncio.to_thread(old_host.replace, new_host)
            await chmod_path(new_host, _READ_ONLY)

            old_sidecar = old_host.with_name(f"{old_host.name}.summary.md")
            if await asyncio.to_thread(old_sidecar.exists):
                new_sidecar = new_host.with_name(f"{new_host.name}.summary.md")
                await chmod_path(old_sidecar, _WRITABLE)
                await asyncio.to_thread(old_sidecar.replace, new_sidecar)
                await chmod_path(new_sidecar, _READ_ONLY)
    except JuiceFSUnavailable as e:
        log.warning(
            "[files] juicefs unavailable; not renaming upload",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return None
    except Exception as e:
        log.error(
            "[files] failed to rename upload in sandbox",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
            exc_info=True,
        )
        return None

    await publish_artifact_event(user_id, remove_event(conversation_id, old_name))
    await publish_artifact_event(
        user_id,
        upload_event(
            conversation_id,
            new_name,
            size_bytes=size_bytes,
            content_type=content_type,
        ),
    )
    new_path = f"{sandbox_session_path(conversation_id)}/{USER_UPLOADED_DIRNAME}/{new_name}"
    log.info("[files] renamed upload in sandbox", sandbox_path=new_path)
    return new_path


async def delete_upload(
    user_id: str,
    conversation_id: str,
    name: str,
) -> bool:
    """Remove an upload and its summary sidecar from the workspace.

    Returns whether anything was removed. Best-effort: the Mongo row is already
    gone, so a missing mount only leaves an orphan, never a failed delete.
    """
    base = session_root(user_id, conversation_id) / USER_UPLOADED_DIRNAME
    removed = False
    try:
        async with fs_timer(FsOps.UPLOAD_PERSIST_SANDBOX):
            for target in (base / name, base / f"{name}.summary.md"):
                if not await asyncio.to_thread(target.exists):
                    continue
                await chmod_path(target, _WRITABLE)
                await asyncio.to_thread(target.unlink)
                removed = True
    except JuiceFSUnavailable as e:
        log.warning(
            "[files] juicefs unavailable; not deleting upload",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return False
    except Exception as e:
        log.error(
            "[files] failed to delete upload from sandbox",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
            exc_info=True,
        )
        return False

    if removed:
        await publish_artifact_event(user_id, remove_event(conversation_id, name))
    return removed
