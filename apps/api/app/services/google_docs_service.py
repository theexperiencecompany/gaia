from typing import Any, Dict, List, Optional

from app.config.loggers import general_logger as logger
from app.config.oauth_config import get_integration_scopes
from app.config.settings import settings
from app.utils.document_utils import create_temp_docx_file
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


def get_docs_service(refresh_token: str, access_token: str):
    """Create and return Google Docs API service instance."""
    # Get combined scopes for both docs and drive access
    docs_scopes = get_integration_scopes("google_docs")
    drive_scopes = get_integration_scopes("google_drive")
    combined_scopes = list(set(docs_scopes + drive_scopes))

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=settings.GOOGLE_TOKEN_URL,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=combined_scopes,
    )
    return build("docs", "v1", credentials=creds)


def get_drive_service(refresh_token: str, access_token: str):
    """Create and return Google Drive API service instance for file management."""
    # Get combined scopes for both docs and drive access
    docs_scopes = get_integration_scopes("google_docs")
    drive_scopes = get_integration_scopes("google_drive")
    combined_scopes = list(set(docs_scopes + drive_scopes))

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=settings.GOOGLE_TOKEN_URL,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=combined_scopes,
    )
    return build("drive", "v3", credentials=creds)


async def create_google_doc(
    refresh_token: str,
    access_token: str,
    title: str,
    content: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new Google Doc from markdown content or create an empty document.

    Args:
        refresh_token: OAuth refresh token
        access_token: OAuth access token
        title: Title of the document
        content: Markdown content to convert and upload (optional)

    Returns:
        Dict containing document information
    """
    try:
        if content:
            # Create Google Doc from markdown content via DOCX conversion
            logger.info("Creating Google Doc from markdown content via DOCX conversion")

            async with create_temp_docx_file(title.replace(" ", "_"), title) as (
                temp_path,
                convert_markdown,
            ):
                # Convert markdown to DOCX
                await convert_markdown(content)

                # Upload DOCX to Google Drive
                drive_service = get_drive_service(refresh_token, access_token)

                # Set up the file metadata
                file_metadata = {
                    "name": title,
                    "mimeType": "application/vnd.google-apps.document",  # Convert to Google Doc
                }

                # Create media upload object
                media = MediaFileUpload(
                    temp_path,
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    resumable=True,
                )

                # Upload the file
                result = (
                    drive_service.files()
                    .create(
                        body=file_metadata,
                        media_body=media,
                        fields="id,name,webViewLink",
                    )
                    .execute()
                )

                doc_id = result.get("id")
                logger.info(f"Created Google Doc from markdown with ID: {doc_id}")

                return {
                    "document_id": doc_id,
                    "title": result.get("name", title),
                    "url": result.get(
                        "webViewLink",
                        f"https://docs.google.com/document/d/{doc_id}/edit",
                    ),
                    "content": content,
                    "source": "markdown_conversion",
                }
        else:
            # Create empty Google Doc using native API
            logger.info("Creating empty Google Doc using native API")
            docs_service = get_docs_service(refresh_token, access_token)

            # Create the document
            doc = {"title": title}
            result = docs_service.documents().create(body=doc).execute()

            doc_id = result.get("documentId")
            logger.info(f"Created empty Google Doc with ID: {doc_id}")

            # Set default margins (1 inch = 72 points)
            if doc_id:
                margin_requests = [
                    {
                        "updateDocumentStyle": {
                            "documentStyle": {
                                "marginTop": {"magnitude": 72, "unit": "PT"},
                                "marginBottom": {"magnitude": 72, "unit": "PT"},
                                "marginLeft": {"magnitude": 72, "unit": "PT"},
                                "marginRight": {"magnitude": 72, "unit": "PT"},
                            },
                            "fields": "marginTop,marginBottom,marginLeft,marginRight",
                        }
                    }
                ]

                docs_service.documents().batchUpdate(
                    documentId=doc_id, body={"requests": margin_requests}
                ).execute()

                logger.info(f"Applied default margins to Google Doc {doc_id}")

            return {
                "document_id": doc_id,
                "title": title,
                "url": f"https://docs.google.com/document/d/{doc_id}/edit",
                "content": "",
                "source": "empty_document",
            }

    except Exception as e:
        logger.error(f"Error creating Google Doc: {e}")
        raise e


async def list_google_docs(
    refresh_token: str,
    access_token: str,
    limit: int = 10,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List Google Docs from the user's Drive.

    Args:
        refresh_token: OAuth refresh token
        access_token: OAuth access token
        limit: Maximum number of documents to return
        query: Optional search query to filter documents

    Returns:
        List of documents with metadata
    """
    try:
        drive_service = get_drive_service(refresh_token, access_token)

        # Build query to filter for Google Docs
        drive_query = (
            "mimeType='application/vnd.google-apps.document' and trashed=false"
        )
        if query:
            drive_query += f" and name contains '{query}'"

        logger.info(f"Querying Google Drive with: q='{drive_query}', pageSize={limit}")

        # Use max pageSize allowed by Google Drive API (1000) if limit is higher
        api_page_size = min(limit, 1000)

        results = (
            drive_service.files()
            .list(
                q=drive_query,
                pageSize=api_page_size,
                fields="nextPageToken, files(id, name, createdTime, modifiedTime, webViewLink, parents)",
                orderBy="modifiedTime desc",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        files = results.get("files", [])
        next_page_token = results.get("nextPageToken")

        logger.info(
            f"Google Drive API returned {len(files)} files, nextPageToken: {next_page_token}"
        )

        docs_list = []
        for file in files:
            docs_list.append(
                {
                    "document_id": file["id"],
                    "title": file["name"],
                    "created_time": file.get("createdTime"),
                    "modified_time": file.get("modifiedTime"),
                    "url": file.get("webViewLink"),
                }
            )

        logger.info(f"Retrieved {len(docs_list)} Google Docs total")
        return docs_list

    except HttpError as e:
        logger.error(f"Error listing Google Docs: {e}")
        raise e


async def get_google_doc(
    refresh_token: str,
    access_token: str,
    document_id: str,
) -> Dict[str, Any]:
    """
    Retrieve a Google Doc's content and metadata.

    Args:
        refresh_token: OAuth refresh token
        access_token: OAuth access token
        document_id: ID of the document to retrieve

    Returns:
        Dict containing document content and metadata
    """
    try:
        docs_service = get_docs_service(refresh_token, access_token)

        doc = docs_service.documents().get(documentId=document_id).execute()

        # Extract text content from the document
        content = extract_text_from_doc(doc)

        return {
            "document_id": document_id,
            "title": doc.get("title"),
            "content": content,
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
            "revision_id": doc.get("revisionId"),
        }

    except HttpError as e:
        logger.error(f"Error retrieving Google Doc {document_id}: {e}")
        raise e


async def update_google_doc_content(
    refresh_token: str,
    access_token: str,
    document_id: str,
    content: str,
    insert_at_end: bool = True,
) -> Dict[str, Any]:
    """
    Update content in a Google Doc.

    Args:
        refresh_token: OAuth refresh token
        access_token: OAuth access token
        document_id: ID of the document to update
        content: New content to add
        insert_at_end: Whether to insert at end (True) or replace all content (False)

    Returns:
        Dict containing updated document information
    """
    try:
        docs_service = get_docs_service(refresh_token, access_token)

        if insert_at_end:
            # Get current document to find the end index
            doc = docs_service.documents().get(documentId=document_id).execute()
            end_index = (
                doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1
            )

            requests = [
                {
                    "insertText": {
                        "location": {"index": end_index},
                        "text": f"\n{content}",
                    }
                }
            ]
        else:
            # Replace all content - first get current document to find actual end index
            doc = docs_service.documents().get(documentId=document_id).execute()
            doc_end_index = (
                doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
            )

            # Only delete if there's content to delete (avoid empty documents)
            if doc_end_index > 1:
                requests = [
                    {
                        "deleteContentRange": {
                            "range": {"startIndex": 1, "endIndex": doc_end_index - 1}
                        }
                    },
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": content,
                        }
                    },
                ]
            else:
                # Document is empty, just insert content
                requests = [
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": content,
                        }
                    },
                ]

        docs_service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()

        logger.info(f"Updated Google Doc {document_id}")

        return {
            "document_id": document_id,
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
            "updates_applied": len(requests),
        }

    except HttpError as e:
        logger.error(f"Error updating Google Doc {document_id}: {e}")
        raise e


async def format_google_doc(
    refresh_token: str,
    access_token: str,
    document_id: str,
    start_index: int,
    end_index: int,
    formatting: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply formatting to a range of text in a Google Doc.

    Args:
        refresh_token: OAuth refresh token
        access_token: OAuth access token
        document_id: ID of the document
        start_index: Start position for formatting
        end_index: End position for formatting
        formatting: Dictionary with formatting options (bold, italic, fontSize, etc.)

    Returns:
        Dict containing formatting result
    """
    try:
        docs_service = get_docs_service(refresh_token, access_token)

        requests = []

        # Build formatting request
        text_style: Dict[str, Any] = {}
        if formatting.get("bold"):
            text_style["bold"] = True
        if formatting.get("italic"):
            text_style["italic"] = True
        if formatting.get("underline"):
            text_style["underline"] = True
        if formatting.get("fontSize"):
            text_style["fontSize"] = {"magnitude": formatting["fontSize"], "unit": "PT"}
        if formatting.get("foregroundColor"):
            text_style["foregroundColor"] = {
                "color": {"rgbColor": formatting["foregroundColor"]}
            }

        if text_style:
            requests.append(
                {
                    "updateTextStyle": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "textStyle": text_style,
                        "fields": ",".join(text_style.keys()),
                    }
                }
            )

        if requests:
            docs_service.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()

            logger.info(f"Applied formatting to Google Doc {document_id}")

        return {
            "document_id": document_id,
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
            "formatting_applied": len(requests),
        }

    except HttpError as e:
        logger.error(f"Error formatting Google Doc {document_id}: {e}")
        raise e


async def share_google_doc(
    refresh_token: str,
    access_token: str,
    document_id: str,
    email: str,
    role: str = "writer",
    send_notification: bool = True,
) -> Dict[str, Any]:
    """
    Share a Google Doc with a user.

    Args:
        refresh_token: OAuth refresh token
        access_token: OAuth access token
        document_id: ID of the document to share
        email: Email address to share with
        role: Role to grant (reader, writer, owner)
        send_notification: Whether to send email notification

    Returns:
        Dict containing sharing result
    """
    try:
        drive_service = get_drive_service(refresh_token, access_token)

        permission = {
            "type": "user",
            "role": role,
            "emailAddress": email,
        }

        result = (
            drive_service.permissions()
            .create(
                fileId=document_id,
                body=permission,
                sendNotificationEmail=send_notification,
            )
            .execute()
        )

        logger.info(f"Shared Google Doc {document_id} with {email}")

        return {
            "document_id": document_id,
            "shared_with": email,
            "role": role,
            "permission_id": result.get("id"),
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
        }

    except HttpError as e:
        logger.error(f"Error sharing Google Doc {document_id}: {e}")
        raise e


async def search_google_docs(
    refresh_token: str,
    access_token: str,
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Search Google Docs by content and title.

    Args:
        refresh_token: OAuth refresh token
        access_token: OAuth access token
        query: Search query
        limit: Maximum number of results

    Returns:
        List of matching documents
    """
    try:
        drive_service = get_drive_service(refresh_token, access_token)

        # Search in both title and full text
        drive_query = f"mimeType='application/vnd.google-apps.document' and trashed=false and (name contains '{query}' or fullText contains '{query}')"

        # Use max pageSize allowed by Google Drive API (1000) if limit is higher
        api_page_size = min(limit, 1000)

        results = (
            drive_service.files()
            .list(
                q=drive_query,
                pageSize=api_page_size,
                fields="nextPageToken, files(id, name, createdTime, modifiedTime, webViewLink)",
                orderBy="modifiedTime desc",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        files = results.get("files", [])

        docs_list = []
        for file in files:
            docs_list.append(
                {
                    "document_id": file["id"],
                    "title": file["name"],
                    "created_time": file.get("createdTime"),
                    "modified_time": file.get("modifiedTime"),
                    "url": file.get("webViewLink"),
                }
            )

        logger.info(f"Found {len(docs_list)} Google Docs matching query: {query}")
        return docs_list

    except HttpError as e:
        logger.error(f"Error searching Google Docs: {e}")
        raise e


def extract_text_from_doc(doc: Dict[str, Any]) -> str:
    """
    Extract plain text content from a Google Doc structure.

    Args:
        doc: Document structure from Google Docs API

    Returns:
        Plain text content
    """
    content = doc.get("body", {}).get("content", [])
    text_content = []

    for element in content:
        if "paragraph" in element:
            paragraph = element["paragraph"]
            for text_element in paragraph.get("elements", []):
                if "textRun" in text_element:
                    text_content.append(text_element["textRun"]["content"])

    return "".join(text_content)
