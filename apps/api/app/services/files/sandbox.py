"""Mirror uploads and their summaries into the session's JuiceFS workspace.

Best-effort: Cloudinary is durable and Mongo is authoritative, so a missing
mount or a write failure never fails the caller. The agent reads files from the
returned /workspace/... paths.
"""

import asyncio
import contextlib
from dataclasses import dataclass

from app.agents.workspace.paths import USER_UPLOADED_DIRNAME, safe_upload_filename
from app.models.files_models import PageWiseSummary
from app.services.artifact_events import publish_artifact_event, remove_event, upload_event
from app.services.files.summaries import render_summary_markdown
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


@dataclass(frozen=True, slots=True)
class UploadMirror:
    """The file fields needed to project one upload into the workspace."""

    file_id: str
    filename: str
    content: bytes
    content_type: str
    description: str | None
    page_wise_summary: PageWiseSummary


def workspace_upload_name(file_id: str, filename: str) -> str:
    """Return a collision-free name for an upload inside user-uploaded/.

    Two distinct files can share a display name (image.png), so prefixing the
    file id keeps their workspace paths distinct: one can never overwrite the
    other. The suffix is capped so the full component stays under 255 bytes.
    """
    safe = safe_upload_filename(filename)
    return f"{file_id}_{safe[: 255 - len(file_id) - 1]}"


async def _overwrite_read_only(user_id: str, conversation_id: str, relative_path: str) -> None:
    """Make a prior read-only copy writable so a re-mirror can replace it."""
    prior = session_root(user_id, conversation_id) / relative_path
    with contextlib.suppress(Exception):
        if prior.exists():
            await chmod_path(prior, _WRITABLE)


async def mirror_upload(
    user_id: str,
    conversation_id: str,
    upload: UploadMirror,
) -> str | None:
    """Mirror an upload and its summary sidecar into the session workspace.

    Returns the /workspace/... path the agent can read, or None when the
    filename is unsafe or JuiceFS is unavailable.
    """
    try:
        safe_filename = workspace_upload_name(upload.file_id, upload.filename)
    except ValueError as e:
        log.warning(
            "[files] skipping sandbox mirror, unsafe filename",
            filename=upload.filename,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return None

    relative_path = f"{USER_UPLOADED_DIRNAME}/{safe_filename}"
    try:
        async with fs_timer(FsOps.UPLOAD_PERSIST_SANDBOX):
            await _overwrite_read_only(user_id, conversation_id, relative_path)
            host_path, sandbox_path = await write_session_file(
                user_id=user_id,
                conversation_id=conversation_id,
                relative_path=relative_path,
                content=upload.content,
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

    if upload.description or upload.page_wise_summary:
        await write_summary_sidecar(
            user_id=user_id,
            conversation_id=conversation_id,
            safe_filename=safe_filename,
            summary_md=render_summary_markdown(
                filename=upload.filename,
                content_type=upload.content_type,
                description=upload.description,
                page_wise_summary=upload.page_wise_summary,
            ),
        )

    # Cross-mount host writes may not reach the sandbox watcher; publish the
    # artifact event directly so the chat UI sees the upload immediately.
    await publish_artifact_event(
        user_id,
        upload_event(
            conversation_id,
            safe_filename,
            size_bytes=len(upload.content),
            content_type=upload.content_type,
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
            content=summary_md.encode(),
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
