"""LinkedIn utility functions for API operations.

These helpers wrap LinkedIn REST/v2 calls behind Composio's proxy. Composio
attaches the user's OAuth token server-side; callers only supply `user_id`.

Binary uploads (images, documents) use the proxy's `binary_body={"url": ...}`
shape: Composio fetches the source URL and forwards the bytes to LinkedIn's
upload endpoint with the authenticated headers.
"""

from typing import Any

from app.services.composio.proxy_client import proxy_request_sync
from shared.py.wide_events import log

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_REST_BASE = "https://api.linkedin.com/rest"
LINKEDIN_VERSION = "202401"
LINKEDIN_TOOLKIT = "LINKEDIN"


def _restli_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }


def _proxy(
    user_id: str,
    *,
    endpoint: str,
    method: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    binary_body: dict[str, str] | None = None,
) -> Any:
    return proxy_request_sync(
        user_id=user_id,
        toolkit=LINKEDIN_TOOLKIT,
        endpoint=endpoint,
        method=method,  # type: ignore[arg-type]
        body=body,
        query=query,
        headers=headers,
        binary_body=binary_body,
    )


def get_author_urn(user_id: str, organization_id: str | None = None) -> str:
    """Get the author URN (person or organization)."""
    log.set(operation="get_author_urn", organization_id=organization_id)
    if organization_id:
        if organization_id.startswith("urn:li:organization:"):
            return organization_id
        return f"urn:li:organization:{organization_id}"

    try:
        data = _proxy(user_id, endpoint=f"{LINKEDIN_API_BASE}/userinfo", method="GET")
        sub = (data or {}).get("sub")
        if sub:
            return f"urn:li:person:{sub}"
    except Exception as e:
        log.error(f"Error getting user info: {e}")

    raise ValueError("Could not determine author URN")


def upload_image_from_url(
    user_id: str,
    image_url: str,
    author_urn: str,
) -> str | None:
    """Initialize a LinkedIn image upload and stream the source URL into it.

    Returns the LinkedIn image URN on success, or None on failure.
    """
    log.set(operation="upload_image", image_url=image_url, author_urn=author_urn)

    try:
        init_result = _proxy(
            user_id,
            endpoint=f"{LINKEDIN_REST_BASE}/images?action=initializeUpload",
            method="POST",
            body={"initializeUploadRequest": {"owner": author_urn}},
            headers=_restli_headers(),
        )

        upload_url = (init_result or {}).get("value", {}).get("uploadUrl")
        image_urn = (init_result or {}).get("value", {}).get("image")

        if not upload_url or not image_urn:
            log.error("Failed to get upload URL from LinkedIn")
            return None

        _proxy(
            user_id,
            endpoint=upload_url,
            method="PUT",
            binary_body={"url": image_url},
        )
        return image_urn

    except Exception as e:
        log.error(f"Error uploading image: {e}")
        return None


def upload_document_from_url(
    user_id: str,
    document_url: str,
    author_urn: str,
) -> str | None:
    """Initialize a LinkedIn document upload and stream the source URL into it.

    Returns the LinkedIn document URN on success, or None on failure.
    """
    log.set(operation="upload_document", document_url=document_url, author_urn=author_urn)

    try:
        init_result = _proxy(
            user_id,
            endpoint=f"{LINKEDIN_REST_BASE}/documents?action=initializeUpload",
            method="POST",
            body={"initializeUploadRequest": {"owner": author_urn}},
            headers=_restli_headers(),
        )

        upload_url = (init_result or {}).get("value", {}).get("uploadUrl")
        document_urn = (init_result or {}).get("value", {}).get("document")

        if not upload_url or not document_urn:
            log.error("Failed to get upload URL from LinkedIn")
            return None

        _proxy(
            user_id,
            endpoint=upload_url,
            method="PUT",
            binary_body={"url": document_url},
        )
        return document_urn

    except Exception as e:
        log.error(f"Error uploading document: {e}")
        return None
