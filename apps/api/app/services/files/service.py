"""FileService — the single entry point for user-uploaded-file operations.

Each public method orchestrates the concern-specific helpers (`store`, `sandbox`,
`summaries`) into one readable flow. Durable storage (Cloudinary) and metadata
(Mongo) are authoritative; vector indexing and the sandbox mirror are best-effort.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import uuid

from fastapi import HTTPException, UploadFile
import httpx

from app.agents.workspace.paths import safe_upload_filename
from app.constants.cache import FILES_CACHE_PATTERN
from app.constants.files import FILE_SEED_DOWNLOAD_TIMEOUT_SECONDS
from app.db.mongodb.collections import files_collection
from app.db.utils import serialize_document
from app.decorators.caching import CacheInvalidator
from app.models.message_models import FileData as MessageFileData
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
    PageWiseSummary,
    process_summary,
    render_summary_markdown,
)
from app.utils.file_utils import generate_file_summary
from app.utils.upload_validation import validate_upload
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
) -> dict:
    """Assemble the authoritative Mongo document for an uploaded file."""
    now = datetime.now(UTC)
    metadata = {
        "file_id": upload.file_id,
        "filename": upload.filename,
        "type": upload.content_type,
        "size": upload.size_bytes,
        "url": url,
        "public_id": upload.public_id,
        "user_id": user_id,
        "description": description,
        "page_wise_summary": page_wise_summary,
        "sandbox_path": sandbox_path,
        "created_at": now,
        "updated_at": now,
    }
    if conversation_id:
        metadata["conversation_id"] = conversation_id
    return metadata


class FileService:
    """Lifecycle of user-uploaded files: upload, summarize, index, search context, delete, update."""

    @staticmethod
    @CacheInvalidator(key_patterns=[FILES_CACHE_PATTERN])
    async def upload(
        file: UploadFile,
        user_id: str,
        conversation_id: str | None = None,
        content_length: int | None = None,
    ) -> dict:
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
            f"[files] upload start file_id={upload.file_id} "
            f"name={upload.filename!r} type={content_type}"
        )

        try:
            # 1. Durable blob + AI content summary, in parallel.
            blob_url, generated_summary = await asyncio.gather(
                upload_to_cloudinary(upload.content, resource_type, upload.public_id),
                generate_file_summary(
                    file_content=upload.content, content_type=content_type, filename=upload.filename
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
            await asyncio.gather(
                insert_metadata(
                    _build_file_metadata(
                        upload,
                        user_id=user_id,
                        url=blob_url,
                        description=description,
                        page_wise_summary=page_wise_summary,
                        sandbox_path=sandbox_path,
                        conversation_id=conversation_id,
                    )
                ),
                index_file(
                    file_id=upload.file_id,
                    user_id=user_id,
                    filename=upload.filename,
                    content_type=content_type,
                    summary=generated_summary,
                    conversation_id=conversation_id,
                ),
            )
            log.info(f"[files] upload complete file_id={upload.file_id}")

            return {
                "file_id": upload.file_id,
                "url": blob_url,
                "filename": upload.filename,
                "description": description,
                "type": content_type,
                "sandbox_path": sandbox_path,
            }
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"[files] upload failed file_id={upload.file_id}: {e!s}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {e!s}")

    @staticmethod
    async def get_descriptions(file_ids: list[str], user_id: str) -> dict[str, str]:
        """Return `{file_id: description}` for the user's files, in one batched query.

        Authoritative source for the agent's file context — never trust the
        client request for this. Files without a stored summary are omitted.
        """
        if not file_ids:
            return {}

        docs = await files_collection.find(
            {"file_id": {"$in": file_ids}, "user_id": user_id},
            projection={"_id": 0, "file_id": 1, "description": 1},
        ).to_list(length=None)
        return {
            doc["file_id"]: doc["description"]
            for doc in docs
            if doc.get("file_id") and doc.get("description")
        }

    @staticmethod
    @CacheInvalidator(key_patterns=[FILES_CACHE_PATTERN])
    async def delete(file_id: str, user_id: str | None) -> dict:
        """Delete a file from Mongo, Cloudinary, and the vector index."""
        log.info(f"[files] delete start file_id={file_id}")
        if user_id is None:
            raise HTTPException(status_code=400, detail="User ID is required")
        log.set(file=FileContext(operation="delete", file_id=file_id))

        file_data = await files_collection.find_one({"file_id": file_id, "user_id": user_id})
        if not file_data:
            log.warning(f"[files] delete: file_id={file_id} not found for user")
            raise HTTPException(status_code=404, detail="File not found")

        result = await files_collection.delete_one({"file_id": file_id, "user_id": user_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="File not found")

        public_id = file_data.get("public_id")
        if public_id:
            destroy_in_cloudinary(public_id)
        else:
            log.warning(f"[files] delete: file_id={file_id} has no public_id; skipping blob delete")

        await delete_from_index(file_id)
        log.info(f"[files] delete complete file_id={file_id}")

        return {
            "message": "File deleted successfully",
            "file_id": file_id,
            "filename": file_data.get("filename", "Unknown"),
        }

    @staticmethod
    @CacheInvalidator(key_patterns=[FILES_CACHE_PATTERN])
    async def update(
        file_id: str,
        user_id: str,
        update_data: dict,
        file_content: bytes | None = None,
        conversation_id: str | None = None,
    ) -> dict:
        """Update file metadata, regenerating the summary + vector index when new content is given."""
        log.info(f"[files] update start file_id={file_id}")
        log.set(file=FileContext(operation="update", file_id=file_id))

        file_data = await files_collection.find_one({"file_id": file_id, "user_id": user_id})
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")

        conversation_id = conversation_id or file_data.get("conversation_id")
        update_data["updated_at"] = datetime.now(UTC)

        if file_content:
            try:
                content_type = update_data.get("type") or file_data.get("type")
                filename = update_data.get("filename") or file_data.get("filename")
                generated_summary = await generate_file_summary(
                    file_content=file_content, content_type=content_type, filename=filename
                )
                description, page_wise_summary = process_summary(generated_summary)
                update_data["description"] = description
                update_data["page_wise_summary"] = page_wise_summary
            except Exception as e:
                log.error(f"[files] update: summary regeneration failed: {e!s}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to process file: {e!s}")

        description_updated = "description" in update_data
        result = await files_collection.update_one(
            {"file_id": file_id, "user_id": user_id}, {"$set": update_data}
        )
        if result.modified_count == 0:
            log.warning(f"[files] update: no fields changed for file_id={file_id}")

        updated_file = await files_collection.find_one({"file_id": file_id, "user_id": user_id})
        if not updated_file:
            raise HTTPException(status_code=404, detail="File not found after update")

        if description_updated:
            await reindex_file(
                file_id=file_id,
                user_id=user_id,
                filename=updated_file.get("filename", ""),
                content_type=updated_file.get("type", ""),
                summary=update_data["description"],
                conversation_id=conversation_id,
            )

        log.info(f"[files] update complete file_id={file_id}")
        return serialize_document(updated_file)

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

        log.info(f"[files] seeding {len(file_data)} upload(s) into conversation={conversation_id}")
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
            log.warning(f"[files] skipping sandbox mirror, unsafe filename {filename!r}: {e}")
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
            log.warning(f"[files] seed: skipping {file.filename!r}, unsafe after sanitize")
            return

        try:
            resp = await client.get(file.url)
            resp.raise_for_status()
        except Exception as e:
            log.warning(f"[files] seed: download failed for {file.filename!r}: {e}")
            return

        await mirror_upload(
            user_id=user_id,
            conversation_id=conversation_id,
            safe_filename=safe_name,
            content=resp.content,
            content_type=file.type or "application/octet-stream",
        )

        doc = await files_collection.find_one(
            {"file_id": file.fileId, "user_id": user_id},
            projection={"_id": 0, "description": 1, "page_wise_summary": 1, "type": 1},
        )
        if not doc:
            return

        if doc.get("description") or doc.get("page_wise_summary"):
            await write_summary_sidecar(
                user_id=user_id,
                conversation_id=conversation_id,
                safe_filename=safe_name,
                summary_md=render_summary_markdown(
                    filename=file.filename,
                    content_type=doc.get("type") or file.type or "application/octet-stream",
                    description=doc.get("description"),
                    page_wise_summary=doc.get("page_wise_summary"),
                ),
            )

        await files_collection.update_one(
            {"file_id": file.fileId, "user_id": user_id},
            {"$set": {"conversation_id": conversation_id}},
        )
