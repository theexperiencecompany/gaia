"""FileService — the single entry point for user-uploaded-file operations.

Each public method orchestrates the concern-specific helpers (store, sandbox,
summaries) into one readable flow. Durable storage (Cloudinary) and metadata
(Mongo) are authoritative; vector indexing and the sandbox mirror are best-effort.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import uuid

from fastapi import HTTPException, UploadFile
import httpx

from app.agents.workspace.paths import USER_UPLOADED_DIRNAME
from app.constants.cache import FILES_CACHE_PATTERN
from app.constants.files import FILE_SEED_DOWNLOAD_TIMEOUT_SECONDS
from app.db.repositories.files import file_repository
from app.decorators.caching import CacheInvalidator
from app.models.files_models import FileDocument, FileUpdate, PageWiseSummary
from app.models.message_models import FileData as MessageFileData
from app.schemas.file import FileDeletedResponse, UpdateFileRequest
from app.services.analytics_service import capture
from app.services.files.naming import workspace_upload_name
from app.services.files.sandbox import (
    delete_upload,
    mirror_upload,
    rename_upload,
    write_summary_sidecar,
)
from app.services.files.store import (
    delete_from_index,
    destroy_in_cloudinary,
    index_file,
    insert_metadata,
    reindex_file,
    upload_to_cloudinary,
)
from app.services.files.summaries import (
    process_summary,
    render_summary_markdown,
)
from app.services.storage import session_root
from app.utils.file_utils import generate_file_summary
from app.utils.upload_validation import validate_upload
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import ChatFileUploaded
from shared.py.wide_events import FileContext, log


@dataclass(frozen=True, slots=True)
class _PreparedUpload:
    """Validated bytes + identity for one upload, derived once and threaded through the flow."""

    file_id: str
    filename: str
    content: bytes
    content_type: str
    resource_type: str

    @property
    def size_bytes(self) -> int:
        return len(self.content)

    @property
    def public_id(self) -> str:
        return f"file_{self.file_id}_{self.filename.replace(' ', '_')}"


def _page_count(page_wise_summary: PageWiseSummary) -> int:
    if isinstance(page_wise_summary, list):
        return len(page_wise_summary)
    return 1 if page_wise_summary else 0


@dataclass
class _UploadSummary:
    """AI summary for one upload: a short description plus per-page details."""

    description: str | None
    page_wise_summary: PageWiseSummary


def _log_upload_context(
    upload: _PreparedUpload,
    conversation_id: str | None,
    summary: _UploadSummary,
) -> None:
    log.set(
        file=FileContext(
            operation="upload",
            file_id=upload.file_id,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            conversation_id=conversation_id or "",
            has_summary=bool(summary.description),
            page_count=_page_count(summary.page_wise_summary),
        )
    )


def _build_file_metadata(
    upload: _PreparedUpload,
    *,
    user_id: str,
    url: str,
    summary: _UploadSummary,
    sandbox_path: str | None,
    conversation_id: str | None,
) -> FileDocument:
    """Assemble the authoritative Mongo document for an uploaded file."""
    now = datetime.now(UTC)
    return FileDocument(
        file_id=upload.file_id,
        filename=upload.filename,
        type=upload.content_type,
        size=upload.size_bytes,
        url=url,
        public_id=upload.public_id,
        user_id=user_id,
        description=summary.description,
        page_wise_summary=summary.page_wise_summary,
        sandbox_path=sandbox_path,
        conversation_id=conversation_id,
        created_at=now,
        updated_at=now,
    )


@dataclass(frozen=True, slots=True)
class _WorkspaceProjection:
    """The file fields the workspace mirror and its summary sidecar need."""

    file_id: str
    filename: str
    content: bytes
    content_type: str
    description: str | None
    page_wise_summary: PageWiseSummary


class FileService:
    """Lifecycle of user-uploaded files: upload, summarize, index, search context, delete, update."""

    @staticmethod
    @CacheInvalidator(key_patterns=[FILES_CACHE_PATTERN])
    async def upload(
        file: UploadFile,
        user_id: str,
        conversation_id: str | None = None,
        content_length: int | None = None,
    ) -> FileDocument:
        """Validate, store, summarize, and mirror an upload into the session.

        Cloudinary (blob) + Mongo (metadata) always persist. The summary, the
        vector index, and the sandbox copy + .summary.md sidecar are layered on
        top; the latter two need JuiceFS and degrade gracefully without it.
        """
        content, content_type, resource_type = await validate_upload(
            file=file, content_length=content_length
        )
        upload = _PreparedUpload(
            file_id=str(uuid.uuid4()),
            # validate_upload() guarantees a filename; narrow the type without an assert (bandit B101).
            filename=file.filename or "",
            content=content,
            content_type=content_type,
            resource_type=resource_type,
        )
        log.info(
            "[files] upload start",
            file_id=upload.file_id,
            filename=upload.filename,
            content_type=content_type,
        )

        try:
            # 1. Durable blob + AI content summary, in parallel.
            blob_url, generated_summary = await asyncio.gather(
                upload_to_cloudinary(upload.content, resource_type, upload.public_id),
                generate_file_summary(
                    file_content=upload.content,
                    content_type=content_type,
                    filename=upload.filename,
                    user_id=user_id,
                ),
            )
            description, page_wise_summary = process_summary(generated_summary)
            summary = _UploadSummary(description=description, page_wise_summary=page_wise_summary)
            _log_upload_context(upload, conversation_id, summary)

            # 2. Mirror into the session workspace + summary sidecar (best-effort; needs JuiceFS).
            sandbox_path = (
                await FileService._project_to_workspace(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    projection=_WorkspaceProjection(
                        file_id=upload.file_id,
                        filename=upload.filename,
                        content=upload.content,
                        content_type=content_type,
                        description=description,
                        page_wise_summary=page_wise_summary,
                    ),
                )
                if conversation_id
                else None
            )

            # 3. Persist authoritative metadata (Mongo) + vector index (Chroma).
            metadata = _build_file_metadata(
                upload,
                user_id=user_id,
                url=blob_url,
                summary=summary,
                sandbox_path=sandbox_path,
                conversation_id=conversation_id,
            )
            await asyncio.gather(
                insert_metadata(metadata),
                index_file(
                    file_id=upload.file_id,
                    user_id=user_id,
                    filename=upload.filename,
                    content_type=content_type,
                    summary=generated_summary,
                    conversation_id=conversation_id,
                ),
            )
            log.info("[files] upload complete file_id", file_id=upload.file_id)

            capture(
                UserId(user_id),
                ChatFileUploaded(
                    size_bytes=upload.size_bytes,
                    resource_type=upload.resource_type,
                    content_type=upload.content_type,
                ),
            )

            return metadata
        except HTTPException:
            raise
        except Exception as e:
            log.error(
                "[files] upload failed file_id",
                file_id=upload.file_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                conversation_id=conversation_id,
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {e!s}") from e

    @staticmethod
    async def get_uploads(
        file_ids: list[str], user_id: str, conversation_id: str | None
    ) -> list[MessageFileData]:
        """Return this turn's uploads as server-owned context, in request order.

        Mongo is authoritative here: filename, summary, mimetype and workspace
        path all come from the stored document, never from the inbound payload.
        Files the user does not own, or that belong to another conversation,
        are omitted.
        """
        if not file_ids:
            return []

        documents = await file_repository.find_by_ids_for_user(file_ids, user_id)
        by_id = {document.file_id: document for document in documents}
        return [
            MessageFileData(
                fileId=document.file_id,
                url=document.url,
                filename=document.filename,
                type=document.type,
                description=document.description,
                sandbox_path=document.sandbox_path,
            )
            for file_id in dict.fromkeys(file_ids)
            if (document := by_id.get(file_id)) is not None
            and document.conversation_id in (None, conversation_id)
        ]

    @staticmethod
    async def list_conversation_files(conversation_id: str, user_id: str) -> list[MessageFileData]:
        """Every file uploaded in a conversation, as FileData carrying its summary.

        Lets the executor surface the conversation's uploads from only the
        conversation id (it never sees the request payload).
        """
        documents = await file_repository.find_for_conversation(conversation_id, user_id)
        return [
            MessageFileData(
                fileId=document.file_id,
                url=document.url,
                filename=document.filename,
                type=document.type,
                description=document.description,
                sandbox_path=document.sandbox_path,
            )
            for document in documents
        ]

    @staticmethod
    @CacheInvalidator(key_patterns=[FILES_CACHE_PATTERN])
    async def delete(file_id: str, user_id: str | None) -> FileDeletedResponse:
        """Delete a file from Mongo, Cloudinary, and the vector index."""
        log.info("[files] delete start file_id", file_id=file_id)
        if user_id is None:
            raise HTTPException(status_code=400, detail="User ID is required")
        log.set(file=FileContext(operation="delete", file_id=file_id))

        file_data = await file_repository.get_by_file_id(file_id, user_id)
        if not file_data:
            log.warning("[files] delete: file not found for user", file_id=file_id, user_id=user_id)
            raise HTTPException(status_code=404, detail="File not found")

        if not await file_repository.delete_by_file_id(file_id, user_id):
            raise HTTPException(status_code=404, detail="File not found")

        public_id = file_data.public_id
        if public_id:
            destroy_in_cloudinary(public_id)
        else:
            log.warning(
                "[files] delete: file has no public_id; skipping blob delete",
                file_id=file_id,
                user_id=user_id,
            )

        await delete_from_index(file_id)
        if file_data.sandbox_path and file_data.conversation_id:
            await delete_upload(
                user_id=user_id,
                conversation_id=file_data.conversation_id,
                name=file_data.sandbox_path.rsplit("/", 1)[-1],
            )
        log.info("[files] delete complete file_id", file_id=file_id)

        return FileDeletedResponse(
            message="File deleted successfully",
            file_id=file_id,
            filename=file_data.filename,
        )

    @staticmethod
    @CacheInvalidator(key_patterns=[FILES_CACHE_PATTERN])
    async def update(
        file_id: str,
        user_id: str,
        update_data: UpdateFileRequest,
        file_content: bytes | None = None,
        conversation_id: str | None = None,
    ) -> FileDocument:
        """Update file metadata, regenerating the summary + vector index when new content is given."""
        log.info("[files] update start file_id", file_id=file_id)
        log.set(file=FileContext(operation="update", file_id=file_id))

        file_data = await file_repository.get_by_file_id(file_id, user_id)
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")

        conversation_id = conversation_id or file_data.conversation_id

        # UpdateFileRequest declares the only client-editable fields, so a client
        # can never mass-assign protected ones (user_id, …).
        update = FileUpdate.model_validate(update_data.model_dump(exclude_none=True))

        if file_content:
            try:
                generated_summary = await generate_file_summary(
                    file_content=file_content,
                    content_type=file_data.type,
                    filename=update.filename or file_data.filename,
                    user_id=user_id,
                )
                description, page_wise_summary = process_summary(generated_summary)
                update.description = description
                update.page_wise_summary = page_wise_summary
            except Exception as e:
                log.error(
                    "[files] update: summary regeneration failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    file_id=file_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    exc_info=True,
                )
                raise HTTPException(status_code=500, detail=f"Failed to process file: {e!s}") from e

        if (
            update.filename is not None
            and update.filename != file_data.filename
            and file_data.sandbox_path
            and conversation_id
        ):
            old_name = file_data.sandbox_path.rsplit("/", 1)[-1]
            new_name = workspace_upload_name(file_id, update.filename)
            if new_name != old_name:
                renamed_path = await rename_upload(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    old_name=old_name,
                    new_name=new_name,
                    content_type=file_data.type,
                    size_bytes=file_data.size,
                )
                if renamed_path is not None:
                    update.sandbox_path = renamed_path

        # updated_at is stamped by the repository.
        updated_file = await file_repository.apply_metadata_update(
            file_id, user_id=user_id, update=update
        )
        if not updated_file:
            raise HTTPException(status_code=404, detail="File not found after update")

        if (
            conversation_id
            and updated_file.sandbox_path
            and (update.filename is not None or update.description is not None)
        ):
            if updated_file.description or updated_file.page_wise_summary:
                await write_summary_sidecar(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    safe_filename=updated_file.sandbox_path.rsplit("/", 1)[-1],
                    summary_md=render_summary_markdown(
                        filename=updated_file.filename,
                        content_type=updated_file.type,
                        description=updated_file.description,
                        page_wise_summary=updated_file.page_wise_summary,
                    ),
                )

        if update.description is not None:
            await reindex_file(
                file_id=file_id,
                user_id=user_id,
                filename=updated_file.filename,
                content_type=updated_file.type,
                summary=update.description,
                conversation_id=conversation_id,
            )

        log.info("[files] update complete file_id", file_id=file_id)
        return updated_file

    @staticmethod
    async def _project_to_workspace(
        *,
        user_id: str,
        conversation_id: str,
        projection: _WorkspaceProjection,
    ) -> str | None:
        """Mirror the bytes and summary sidecar into the session workspace.

        The one projection path for both upload and attach. Best-effort: a
        missing mount or write failure returns None, never fails the caller.
        """
        try:
            safe_name = workspace_upload_name(projection.file_id, projection.filename)
        except ValueError as e:
            log.warning(
                "[files] skipping sandbox mirror, unsafe filename",
                filename=projection.filename,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return None

        sandbox_path = await mirror_upload(
            user_id=user_id,
            conversation_id=conversation_id,
            safe_filename=safe_name,
            content=projection.content,
            content_type=projection.content_type,
        )
        if sandbox_path is not None and (projection.description or projection.page_wise_summary):
            await write_summary_sidecar(
                user_id=user_id,
                conversation_id=conversation_id,
                safe_filename=safe_name,
                summary_md=render_summary_markdown(
                    filename=projection.filename,
                    content_type=projection.content_type,
                    description=projection.description,
                    page_wise_summary=projection.page_wise_summary,
                ),
            )
        return sandbox_path

    @staticmethod
    async def attach_uploads(
        file_ids: Sequence[str],
        user_id: str,
        conversation_id: str,
    ) -> None:
        """Scope this turn's uploads to the conversation and mirror them on disk.

        Idempotent: a file already scoped and present is untouched. The URL
        comes from Mongo, never the request, so a client cannot choose what
        the server fetches.
        """
        unique_ids = list(dict.fromkeys(file_ids))
        if not unique_ids:
            return

        log.info(
            "[files] attaching upload(s) to conversation",
            file_count=len(unique_ids),
            conversation_id=conversation_id,
        )
        async with httpx.AsyncClient(timeout=FILE_SEED_DOWNLOAD_TIMEOUT_SECONDS) as client:
            await asyncio.gather(
                *(
                    FileService._attach_one(client, file_id, user_id, conversation_id)
                    for file_id in unique_ids
                )
            )

    @staticmethod
    async def _attach_one(
        client: httpx.AsyncClient,
        file_id: str,
        user_id: str,
        conversation_id: str,
    ) -> None:
        """Attach one uploaded file to its conversation (see attach_uploads)."""
        document = await file_repository.get_by_file_id(file_id, user_id)
        if document is None:
            log.warning(
                "[files] attach: file not found for user",
                file_id=file_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return

        if document.conversation_id not in (None, conversation_id):
            log.warning(
                "[files] attach: file belongs to another conversation",
                file_id=file_id,
                file_conversation_id=document.conversation_id,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            return

        try:
            safe_name = workspace_upload_name(file_id, document.filename)
        except ValueError as e:
            log.warning(
                "[files] attach: skipping file, unsafe filename",
                file_id=file_id,
                filename=document.filename,
                error=str(e),
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return

        relative_path = f"{USER_UPLOADED_DIRNAME}/{safe_name}"
        if document.conversation_id == conversation_id and document.sandbox_path:
            if (session_root(user_id, conversation_id) / relative_path).exists():
                return

        # Starts with sandbox_path unset (the model default) so a stale
        # /workspace path is cleared unless this attempt mirrors the file.
        update = FileUpdate(conversation_id=conversation_id)
        try:
            response = await client.get(document.url)
            response.raise_for_status()
        except Exception as e:
            log.warning(
                "[files] attach: download failed",
                file_id=file_id,
                filename=document.filename,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        else:
            sandbox_path = await FileService._project_to_workspace(
                user_id=user_id,
                conversation_id=conversation_id,
                projection=_WorkspaceProjection(
                    file_id=file_id,
                    filename=document.filename,
                    content=response.content,
                    content_type=document.type,
                    description=document.description,
                    page_wise_summary=document.page_wise_summary,
                ),
            )
            if sandbox_path is not None:
                update.sandbox_path = sandbox_path

        await file_repository.apply_metadata_update(file_id, user_id=user_id, update=update)
