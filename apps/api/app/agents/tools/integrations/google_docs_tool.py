"""Google Docs tools using Composio custom tool infrastructure.

Provider API calls go through Composio's proxy via proxy_request_sync.
The Drive API is the GOOGLEDOCS toolkit's underlying surface.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

import json

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.decorators import with_doc
from app.models.common_models import GatherContextInput
from app.models.google_docs_models import CreateTOCInput, DeleteDocInput, ShareDocInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.google_docs import GoogleDocsDocument, GoogleDocsToolExecution
from app.models.integrations.google_drive import (
    GoogleDriveFileList,
    GoogleDrivePermission,
    GoogleDrivePermissionCreate,
)
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
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


def _share_doc(request: ShareDocInput, user_id: str) -> dict[str, object]:
    shared: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []

    for recipient in request.recipients:
        permission = GoogleDrivePermissionCreate(
            type="user", role=recipient.role, emailAddress=recipient.email
        )
        try:
            result = proxy_request_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=DOCS_TOOLKIT,
                    endpoint=f"{DRIVE_API_BASE}/files/{request.document_id}/permissions",
                    method="POST",
                    # Every field is str, so json and python dumps are byte identical
                    # and the mode value is provably unobservable here.
                    body=permission.model_dump(mode="json"),  # pragma: no mutate
                    query={"sendNotificationEmail": str(recipient.send_notification).lower()},
                )
            )
            shared.append(
                {
                    "email": recipient.email,
                    "role": recipient.role,
                    "permission_id": GoogleDrivePermission.model_validate(result or {}).id,
                    "notification_sent": recipient.send_notification,
                }
            )
        except AppError as e:
            log.error(
                f"{LogTag.TOOL} Error sharing doc with recipient", error_type=type(e).__name__
            )
            errors.append(
                {
                    "email": recipient.email,
                    "role": recipient.role,
                    "error": f"Failed to share: {e.status_code} - {e.message}",
                }
            )

    if errors and not shared:
        raise RuntimeError(f"Failed to share document with all recipients: {errors}")

    response: dict[str, object] = {
        "document_id": request.document_id,
        "url": f"https://docs.google.com/document/d/{request.document_id}/edit",
        "shared": shared,
    }
    if errors:
        response["errors"] = errors
    return response


def _fetch_document_data(
    composio: Composio,
    document_id: str,
    credentials: CustomToolAuthCredentials,
) -> GoogleDocsDocument:
    try:
        get_doc_result = GoogleDocsToolExecution.model_validate(
            composio.tools.execute(
                slug="GOOGLEDOCS_GET_DOCUMENT_BY_ID",
                arguments={"id": document_id},
                version=credentials.version,
                dangerously_skip_version_check=True,
                user_id=credentials.user_id,
            )
        )
    except TypeError as e:
        log.debug(f"{LogTag.TOOL} TypeError in execute", error_type=type(e).__name__)
        raise

    if not get_doc_result.successful:
        raise ValueError(f"Failed to get document: {get_doc_result.error}")

    # Composio has answered with the document JSON-encoded as a string as well
    # as a dict — decode it before the shape checks.
    doc_data = get_doc_result.data
    if isinstance(doc_data, str):
        try:
            doc_data = json.loads(doc_data)
        except json.JSONDecodeError as e:
            log.debug(
                f"{LogTag.TOOL} JSON parsing skipped for doc_data", error_type=type(e).__name__
            )

    # A key on a dict, a substring on a string that did not decode: an
    # undecodable blob without one fails here, not as "unexpected format".
    if not doc_data or not (isinstance(doc_data, dict | str) and "body" in doc_data):
        raise ValueError("Failed to get document or document has no body content")

    if not isinstance(doc_data, dict):
        raise ValueError("Document data is not in expected format")
    return GoogleDocsDocument.model_validate(doc_data)


def _insert_toc_text(
    composio: Composio,
    request: CreateTOCInput,
    toc_text: str,
    credentials: CustomToolAuthCredentials,
) -> GoogleDocsToolExecution:
    insert_result = GoogleDocsToolExecution.model_validate(
        composio.tools.execute(
            slug="GOOGLEDOCS_INSERT_TEXT_ACTION",
            arguments={
                "document_id": request.document_id,
                "text": toc_text,
                "insertion_index": request.insertion_index,
            },
            version=credentials.version,
            dangerously_skip_version_check=True,
            user_id=credentials.user_id,
        )
    )

    if not insert_result.successful:
        raise ValueError(f"Failed to insert text: {insert_result.error}")

    return insert_result


def _create_toc(
    composio: Composio,
    request: CreateTOCInput,
    credentials: CustomToolAuthCredentials,
) -> dict[str, object]:
    document = _fetch_document_data(composio, request.document_id, credentials)
    headings = extract_headings_from_document(document, request.include_heading_levels)
    toc_text = generate_toc_text(headings, request.title)
    insert_result = _insert_toc_text(composio, request, toc_text, credentials)

    return {
        "document_id": request.document_id,
        "url": f"https://docs.google.com/document/d/{request.document_id}/edit",
        "headings_found": len(headings),
        "toc_content": toc_text,
        # str/int fields only: json and python dumps are byte identical here.
        "headings": [heading.model_dump(mode="json") for heading in headings],  # pragma: no mutate
        "insert_response": insert_result.data,
    }


def _delete_doc(request: DeleteDocInput, user_id: str) -> dict[str, object]:
    try:
        proxy_request_sync(
            ProxyRequest(
                user_id=user_id,
                toolkit=DOCS_TOOLKIT,
                endpoint=f"{DRIVE_API_BASE}/files/{request.document_id}",
                method="DELETE",
            )
        )
    except AppError as e:
        log.error(
            f"{LogTag.TOOL} Error deleting doc",
            document_id=request.document_id,
            error_type=type(e).__name__,
        )
        raise RuntimeError(f"Failed to delete document: {e.status_code} - {e.message}") from e

    return {
        "successful": True,
        "document_id": request.document_id,
    }


def _gather_recent_docs(user_id: str) -> dict[str, object]:
    mime = "application/vnd.google-apps.document"
    listing = GoogleDriveFileList.model_validate(
        proxy_request_sync(
            ProxyRequest(
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
        )
        or {}
    )
    files = [
        {"id": f.id, "name": f.name, "modified": f.modifiedTime, "url": f.webViewLink}
        for f in listing.files
    ]

    return {"recent_docs": files, "doc_count": len(files)}


def register_google_docs_custom_tools(composio: Composio) -> list[str]:
    """Register Google Docs tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    @with_doc(CUSTOM_SHARE_DOC_DOC)
    def CUSTOM_SHARE_DOC(
        request: ShareDocInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Share a Google Doc with one or more recipients."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_docs", "action": "share_doc"})
        return _share_doc(request, CustomToolAuthCredentials.parse(auth_credentials).user_id)

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    @with_doc(CUSTOM_CREATE_TOC_DOC)
    def CUSTOM_CREATE_TOC(
        request: CreateTOCInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_docs", "action": "create_toc"})
        return _create_toc(composio, request, CustomToolAuthCredentials.parse(auth_credentials))

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    @with_doc(CUSTOM_DELETE_DOC_DOC)
    def CUSTOM_DELETE_DOC(
        request: DeleteDocInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Delete a file permanently using Drive API."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_docs", "action": "delete_doc"})
        return _delete_doc(request, CustomToolAuthCredentials.parse(auth_credentials).user_id)

    @composio.tools.custom_tool(toolkit="GOOGLEDOCS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Google Docs context snapshot: recently viewed/modified documents.

        Zero required parameters. Returns user's recently accessed Google Docs.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_docs", "action": "gather_context"})
        return _gather_recent_docs(CustomToolAuthCredentials.parse(auth_credentials).user_id)

    return [
        "GOOGLEDOCS_CUSTOM_SHARE_DOC",
        "GOOGLEDOCS_CUSTOM_CREATE_TOC",
        "GOOGLEDOCS_CUSTOM_DELETE_DOC",
        "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT",
    ]
