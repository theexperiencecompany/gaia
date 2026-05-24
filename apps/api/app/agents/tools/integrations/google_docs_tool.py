"""Google Docs tools using Composio custom tool infrastructure.

Provider API calls go through Composio's proxy via `proxy_request_sync`.
The Drive API is the GOOGLEDOCS toolkit's underlying surface.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

import json
from typing import Any

from composio import Composio
from composio.core.models.tools import ToolExecutionResponse

from app.decorators import with_doc
from app.models.common_models import GatherContextInput
from app.models.google_docs_models import CreateTOCInput, DeleteDocInput, ShareDocInput
from app.services.composio.proxy_client import proxy_request_sync
from app.templates.docstrings.google_docs_tool_docs import (
    CUSTOM_CREATE_TOC as CUSTOM_CREATE_TOC_DOC,
    CUSTOM_DELETE_DOC as CUSTOM_DELETE_DOC_DOC,
    CUSTOM_SHARE_DOC as CUSTOM_SHARE_DOC_DOC,
)
from app.utils.errors import AppError
from app.utils.google_docs_utils import (
    extract_headings_from_document,
    generate_toc_text,
)
from shared.py.wide_events import log

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DOCS_TOOLKIT = "GOOGLEDOCS"


def _user_id(auth_credentials: dict[str, Any]) -> str:
    user_id = auth_credentials.get("user_id")
    if not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


def register_google_docs_custom_tools(composio: Composio) -> list[str]:
    """Register Google Docs tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    @with_doc(CUSTOM_SHARE_DOC_DOC)
    def CUSTOM_SHARE_DOC(
        request: ShareDocInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Share a Google Doc with one or more recipients."""
        log.set(tool={"integration": "google_docs", "action": "share_doc"})
        user_id = _user_id(auth_credentials)

        shared = []
        errors = []

        for recipient in request.recipients:
            try:
                result = proxy_request_sync(
                    user_id=user_id,
                    toolkit=DOCS_TOOLKIT,
                    endpoint=f"{DRIVE_API_BASE}/files/{request.document_id}/permissions",
                    method="POST",
                    body={
                        "type": "user",
                        "role": recipient.role,
                        "emailAddress": recipient.email,
                    },
                    query={"sendNotificationEmail": str(recipient.send_notification).lower()},
                )
                shared.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "permission_id": (result or {}).get("id"),
                        "notification_sent": recipient.send_notification,
                    }
                )
            except AppError as e:
                log.error(f"Error sharing with {recipient.email}: {e}")
                errors.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "error": f"Failed to share: {e.status_code} - {e.message}",
                    }
                )

        if errors and not shared:
            raise RuntimeError(f"Failed to share document with all recipients: {errors}")

        doc_url = f"https://docs.google.com/document/d/{request.document_id}/edit"

        return {
            "document_id": request.document_id,
            "url": doc_url,
            "shared": shared,
        }

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    @with_doc(CUSTOM_CREATE_TOC_DOC)
    def CUSTOM_CREATE_TOC(
        request: CreateTOCInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        log.set(tool={"integration": "google_docs", "action": "create_toc"})
        try:
            get_doc_result: ToolExecutionResponse = composio.tools.execute(
                slug="GOOGLEDOCS_GET_DOCUMENT_BY_ID",
                arguments={"id": request.document_id},
                version=auth_credentials.get("version"),
                dangerously_skip_version_check=True,
                user_id=auth_credentials.get("user_id"),
            )
        except TypeError as e:
            log.debug(f"TypeError in execute: {e}")
            raise

        # Unwrap response (ToolExecutionResponse format)
        if not get_doc_result["successful"]:
            raise ValueError(f"Failed to get document: {get_doc_result.get('error')}")

        doc_data = get_doc_result["data"]
        # Handle double wrapping if data is stringified JSON
        if isinstance(doc_data, str):
            try:
                doc_data = json.loads(doc_data)
            except json.JSONDecodeError as e:
                log.debug(f"JSON parsing skipped for doc_data: {e}")

        if not doc_data or "body" not in doc_data:
            raise ValueError("Failed to get document or document has no body content")

        # Step 2: Extract headings from document
        if not isinstance(doc_data, dict):
            raise ValueError("Document data is not in expected format")
        headings = extract_headings_from_document(
            doc_data,
            request.include_heading_levels,
        )

        # Step 3: Generate TOC text
        toc_text = generate_toc_text(headings, request.title)

        # Step 4: Insert TOC at specified position using composio.tools.execute
        insert_result: ToolExecutionResponse = composio.tools.execute(
            slug="GOOGLEDOCS_INSERT_TEXT_ACTION",
            arguments={
                "document_id": request.document_id,
                "text": toc_text,
                "insertion_index": request.insertion_index,
            },
            version=auth_credentials.get("version"),
            dangerously_skip_version_check=True,
            user_id=auth_credentials.get("user_id"),
        )

        # Unwrap response (ToolExecutionResponse format)
        if not insert_result["successful"]:
            raise ValueError(f"Failed to insert text: {insert_result.get('error')}")

        insert_data = insert_result["data"]

        doc_url = f"https://docs.google.com/document/d/{request.document_id}/edit"

        return {
            "document_id": request.document_id,
            "url": doc_url,
            "headings_found": len(headings),
            "toc_content": toc_text,
            "headings": headings,
            "insert_response": insert_data,
        }

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    @with_doc(CUSTOM_DELETE_DOC_DOC)
    def CUSTOM_DELETE_DOC(
        request: DeleteDocInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Delete a file permanently using Drive API."""
        log.set(tool={"integration": "google_docs", "action": "delete_doc"})
        user_id = _user_id(auth_credentials)

        try:
            proxy_request_sync(
                user_id=user_id,
                toolkit=DOCS_TOOLKIT,
                endpoint=f"{DRIVE_API_BASE}/files/{request.document_id}",
                method="DELETE",
            )
        except AppError as e:
            log.error(f"Error deleting doc {request.document_id}: {e}")
            raise RuntimeError(f"Failed to delete document: {e.status_code} - {e.message}")

        return {
            "successful": True,
            "document_id": request.document_id,
        }

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Google Docs context snapshot: recently viewed/modified documents.

        Zero required parameters. Returns user's recently accessed Google Docs.
        """
        log.set(tool={"integration": "google_docs", "action": "gather_context"})
        user_id = _user_id(auth_credentials)

        mime = "application/vnd.google-apps.document"
        files: list[dict[str, Any]] = []
        try:
            data = proxy_request_sync(
                user_id=user_id,
                toolkit=DOCS_TOOLKIT,
                endpoint=f"{DRIVE_API_BASE}/files",
                method="GET",
                query={
                    "q": f"mimeType='{mime}'",
                    "orderBy": "viewedByMeTime desc",
                    "pageSize": 20,
                    "fields": "files(id,name,modifiedTime,webViewLink)",
                },
            )
            files = [
                {
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "modified": f.get("modifiedTime"),
                    "url": f.get("webViewLink"),
                }
                for f in (data or {}).get("files", [])
            ]
        except Exception as e:
            log.debug(f"Google Docs fetch failed: {e}")

        return {"recent_docs": files, "doc_count": len(files)}

    return [
        "GOOGLEDOCS_CUSTOM_SHARE_DOC",
        "GOOGLEDOCS_CUSTOM_CREATE_TOC",
        "GOOGLEDOCS_CUSTOM_DELETE_DOC",
        "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT",
    ]
