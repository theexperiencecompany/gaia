"""FileService — the single entry point for user-uploaded-file operations.

Each public method orchestrates the concern-specific helpers (`store`, `sandbox`,
`summaries`) into one readable flow. Durable storage (Cloudinary) and metadata
(Mongo) are authoritative; vector indexing and the sandbox mirror are best-effort.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
import uuid

from fastapi import HTTPException, UploadFile
import httpx

from app.agents.workspace.paths import safe_upload_filename
from app.constants.cache import FILES_CACHE_PATTERN
from app.constants.files import FILE_SEED_DOWNLOAD_TIMEOUT_SECONDS
from app.db.repositories.files import file_repository
from app.decorators.caching import CacheInvalidator
from app.models.files_models import FileDocument, FileUpdate, PageWiseSummary
from app.models.message_models import FileData as MessageFileData
from app.schemas.file import FileDeletedResponse
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.files.sandbox import mirror_upload, write_summary_sidecar
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
from app.utils.file_utils import generate_file_summary
from app.utils.upload_validation import validate_upload
from shared.py.wide_events import FileContext, log

# Client-editable file metadata fields. Anything else in the incoming payload is
# ignored to prevent mass-assignment of protected fields (user_id, created_at…).
ALLOWED_FILE_UPDATE_FIELDS = ("filename", "description")


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


def _log_upload_context(
    upload: _PreparedUpload,
    conversation_id: str | None,
    description: str | None,
    page_wise_summary: PageWiseSummary,
) -> None:
    log.set(
        file=FileContext(
            operation="upload",
            file_id=upload.file_id,
            filename=upload.filename,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            conversation_id=conversation_id or "",
            has_summary=bool(description),
            page_count=_page_count(page_wise_summary),
        )
    )


def _build_file_metadata(
    upload: _PreparedUpload,
    *,
    user_id: str,
    url: str,
    description: str | None,
    page_wise_summary: PageWiseSummary,
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
        description=description,
        page_wise_summary=page_wise_summary,
        sandbox_path=sandbox_path,
        conversation_id=conversation_id,
        created_at=now,
        updated_at=now,
    )


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
        vector index, and the sandbox copy + `.summary.md` sidecar are layered on
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
            _log_upload_context(upload, conversation_id, description, page_wise_summary)

            # 2. Mirror into the session workspace + summary sidecar (best-effort; needs JuiceFS).
            sandbox_path = (
                await FileService._mirror_to_session(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    filename=upload.filename,
                    content=upload.content,
                    content_type=content_type,
                    description=description,
                    page_wise_summary=page_wise_summary,
                )
                if conversation_id
                else None
            )

            # 3. Persist authoritative metadata (Mongo) + vector index (Chroma).
            metadata = _build_file_metadata(
                upload,
                user_id=user_id,
                url=blob_url,
                description=description,
                page_wise_summary=page_wise_summary,
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

            capture_event(
                user_id,
                AnalyticsEvents.FILE_UPLOADED,
                {
                    "size_bytes": upload.size_bytes,
                    "resource_type": upload.resource_type,
                    "content_type": upload.content_type,
                },
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
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {e!s}")

    @staticmethod
    async def get_descriptions(file_ids: list[str], user_id: str) -> dict[str, str]:
        """Return `{file_id: description}` for the user's files, in one batched query.

        Authoritative source for the agent's file context — never trust the
        client request for this. Files without a stored summary are omitted.
        """
        if not file_ids:
            return {}

        documents = await file_repository.find_by_ids_for_user(file_ids, user_id)
        return {
            document.file_id: document.description for document in documents if document.description
        }

    @staticmethod
    async def list_conversation_files(conversation_id: str, user_id: str) -> list[MessageFileData]:
        """Every file uploaded in a conversation, as ``FileData`` carrying its summary.

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
        update_data: dict[str, Any],
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

        # Build the update from allowlisted fields only — never spread the raw
        # payload, or a client could mass-assign protected fields (user_id, …).
        set_fields: dict[str, Any] = {
            field: update_data[field]
            for field in ALLOWED_FILE_UPDATE_FIELDS
            if update_data.get(field) is not None
        }

        if file_content:
            try:
                generated_summary = await generate_file_summary(
                    file_content=file_content,
                    content_type=file_data.type,
                    filename=set_fields.get("filename") or file_data.filename,
                    user_id=user_id,
                )
                description, page_wise_summary = process_summary(generated_summary)
                set_fields["description"] = description
                set_fields["page_wise_summary"] = page_wise_summary
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
                raise HTTPException(status_code=500, detail=f"Failed to process file: {e!s}")

        description_updated = "description" in set_fields
        # updated_at is stamped by the repository.
        updated_file = await file_repository.apply_metadata_update(
            file_id, user_id=user_id, update=FileUpdate(**set_fields)
        )
        if not updated_file:
            raise HTTPException(status_code=404, detail="File not found after update")

        if description_updated:
            await reindex_file(
                file_id=file_id,
                user_id=user_id,
                filename=updated_file.filename,
                content_type=updated_file.type,
                summary=set_fields["description"],
                conversation_id=conversation_id,
            )

        log.info("[files] update complete file_id", file_id=file_id)
        return updated_file

    @staticmethod
    async def seed_uploads(
        file_data: list[MessageFileData],
        user_id: str,
        conversation_id: str,
    ) -> None:
        """Associate pre-conversation uploads with a freshly created session.

        Files attached before a conversation existed landed in Cloudinary only.
        Once the session exists, mirror each into `user-uploaded/`, write its
        summary sidecar, and stamp `conversation_id` on its Mongo record so
        conversation-scoped search can find it.
        """
        if not file_data:
            return

        log.info(
            "[files] seeding upload(s) into conversation",
            file_data_count=len(file_data),
            conversation_id=conversation_id,
        )
        async with httpx.AsyncClient(timeout=FILE_SEED_DOWNLOAD_TIMEOUT_SECONDS) as client:
            await asyncio.gather(
                *(
                    FileService._seed_one(client, file, user_id, conversation_id)
                    for file in file_data
                )
            )

    @staticmethod
    async def _mirror_to_session(
        user_id: str,
        conversation_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        description: str | None,
        page_wise_summary: PageWiseSummary,
    ) -> str | None:
        """Mirror an upload + its summary sidecar into the session workspace (best-effort).

        Returns the `/workspace/...` path the file was mirrored to, or None when
        the filename is unsafe or JuiceFS is unavailable.
        """
        try:
            safe_filename = safe_upload_filename(filename)
        except ValueError as e:
            log.warning(
                "[files] skipping sandbox mirror, unsafe filename",
                filename=filename,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return None

        sandbox_path = await mirror_upload(
            user_id=user_id,
            conversation_id=conversation_id,
            safe_filename=safe_filename,
            content=content,
            content_type=content_type,
        )
        await write_summary_sidecar(
            user_id=user_id,
            conversation_id=conversation_id,
            safe_filename=safe_filename,
            summary_md=render_summary_markdown(
                filename=filename,
                content_type=content_type,
                description=description,
                page_wise_summary=page_wise_summary,
            ),
        )
        return sandbox_path

    @staticmethod
    async def _seed_one(
        client: httpx.AsyncClient,
        file: MessageFileData,
        user_id: str,
        conversation_id: str,
    ) -> None:
        """Download one Cloudinary-hosted file and associate it with the conversation."""
        try:
            safe_name = safe_upload_filename(file.filename)
        except ValueError:
            log.warning(
                "[files] seed: skipping file, unsafe after sanitize",
                filename=file.filename,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return

        try:
            resp = await client.get(file.url)
            resp.raise_for_status()
        except Exception as e:
            log.warning(
                "[files] seed: download failed for",
                filename=file.filename,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return

        await mirror_upload(
            user_id=user_id,
            conversation_id=conversation_id,
            safe_filename=safe_name,
            content=resp.content,
            content_type=file.type or "application/octet-stream",
        )

        document = await file_repository.get_by_file_id(file.fileId, user_id)
        if not document:
            return

        if document.description or document.page_wise_summary:
            await write_summary_sidecar(
                user_id=user_id,
                conversation_id=conversation_id,
                safe_filename=safe_name,
                summary_md=render_summary_markdown(
                    filename=file.filename,
                    content_type=document.type or file.type or "application/octet-stream",
                    description=document.description,
                    page_wise_summary=document.page_wise_summary,
                ),
            )

        await file_repository.apply_metadata_update(
            file.fileId, user_id=user_id, update=FileUpdate(conversation_id=conversation_id)
        )
