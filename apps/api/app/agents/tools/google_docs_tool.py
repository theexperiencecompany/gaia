"""Google Docs tools using Composio custom tool infrastructure.

These tools provide Google Docs functionality using the access_token from Composio's
auth_credentials. Uses Google Drive API for sharing operations and composio.tools.execute
for calling other Composio tools.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

import json
from typing import Any, Dict, List

import httpx
from app.config.loggers import chat_logger as logger
from app.decorators import with_doc
from app.models.google_docs_models import CreateTOCInput, DeleteDocInput, ShareDocInput
from app.templates.docstrings.google_docs_tool_docs import (
    CUSTOM_CREATE_TOC as CUSTOM_CREATE_TOC_DOC,
)
from app.templates.docstrings.google_docs_tool_docs import (
    CUSTOM_DELETE_DOC as CUSTOM_DELETE_DOC_DOC,
)
from app.templates.docstrings.google_docs_tool_docs import (
    CUSTOM_SHARE_DOC as CUSTOM_SHARE_DOC_DOC,
)
from app.utils.google_docs_utils import (
    extract_headings_from_document,
    generate_toc_text,
)
from composio import Composio
from composio.core.models.tools import ToolExecutionResponse

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"

# Reusable sync HTTP client for direct API calls
_http_client = httpx.Client(timeout=30)


def _get_access_token(auth_credentials: Dict[str, Any]) -> str:
    """Extract access token from auth_credentials."""
    token = auth_credentials.get("access_token")
    if not token:
        raise ValueError("Missing access_token in auth_credentials")
    return token


def _auth_headers(access_token: str) -> Dict[str, str]:
    """Return Bearer token header for Google Drive API."""
    return {"Authorization": f"Bearer {access_token}"}


def register_google_docs_custom_tools(composio: Composio) -> List[str]:
    """Register Google Docs tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    @with_doc(CUSTOM_SHARE_DOC_DOC)
    def CUSTOM_SHARE_DOC(
        request: ShareDocInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Share a Google Doc with one or more recipients."""
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)
        headers["Content-Type"] = "application/json"

        shared = []
        errors = []

        for recipient in request.recipients:
            permission = {
                "type": "user",
                "role": recipient.role,
                "emailAddress": recipient.email,
            }

            url = f"{DRIVE_API_BASE}/files/{request.document_id}/permissions"
            params = {"sendNotificationEmail": str(recipient.send_notification).lower()}

            try:
                resp = _http_client.post(
                    url, headers=headers, json=permission, params=params
                )
                resp.raise_for_status()
                result = resp.json()
                shared.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "permission_id": result.get("id"),
                        "notification_sent": recipient.send_notification,
                    }
                )
            except httpx.HTTPStatusError as e:
                logger.error(f"Error sharing with {recipient.email}: {e}")
                errors.append(
                    {
                        "email": recipient.email,
                        "role": recipient.role,
                        "error": f"Failed to share: {e.response.status_code} - {e.response.text}",
                    }
                )

        # If all shares failed, raise an exception
        if errors and not shared:
            raise RuntimeError(
                f"Failed to share document with all recipients: {errors}"
            )

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
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            get_doc_result: ToolExecutionResponse = composio.tools.execute(
                slug="GOOGLEDOCS_GET_DOCUMENT_BY_ID",
                arguments={"id": request.document_id},
                version=auth_credentials.get("version"),
                dangerously_skip_version_check=True,
                user_id=auth_credentials.get("user_id"),
            )
        except TypeError as e:
            print(f"DEBUG: TypeError in execute: {e}")
            raise

        # Unwrap response (ToolExecutionResponse format)
        if not get_doc_result["successful"]:
            raise ValueError(f"Failed to get document: {get_doc_result.get('error')}")

        doc_data = get_doc_result["data"]
        # Handle double wrapping if data is stringified JSON
        if isinstance(doc_data, str):
            try:
                doc_data = json.loads(doc_data)
            except Exception:
                pass  # nosec

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
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Delete a file permanently using Drive API."""
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)

        url = f"{DRIVE_API_BASE}/files/{request.document_id}"

        try:
            resp = _http_client.delete(url, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"Error deleting doc {request.document_id}: {e}")
            raise RuntimeError(
                f"Failed to delete document: {e.response.status_code} - {e.response.text}"
            )

        return {
            "successful": True,
            "document_id": request.document_id,
        }

    return [
        "GOOGLEDOCS_CUSTOM_SHARE_DOC",
        "GOOGLEDOCS_CUSTOM_CREATE_TOC",
        "GOOGLEDOCS_CUSTOM_DELETE_DOC",
    ]
