"""LinkedIn utility functions for API operations.

This module provides helper functions for LinkedIn API interactions including:
- Access token extraction
- Header generation
- Author URN resolution
- Image and document uploads
"""

from typing import Any, Dict

import httpx

from app.config.loggers import chat_logger as logger

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_REST_BASE = "https://api.linkedin.com/rest"

# LinkedIn API version - use a recent stable version
LINKEDIN_VERSION = "202401"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=60)


def get_access_token(auth_credentials: Dict[str, Any]) -> str:
    """Extract access token from auth_credentials."""
    token = auth_credentials.get("access_token")
    if not token:
        raise ValueError("Missing access_token in auth_credentials")
    return token


def linkedin_headers(access_token: str) -> Dict[str, str]:
    """Return headers for LinkedIn API v2 requests."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }


def get_author_urn(access_token: str, organization_id: str | None = None) -> str:
    """Get the author URN (person or organization)."""
    if organization_id:
        # If org ID provided, use it directly
        if organization_id.startswith("urn:li:organization:"):
            return organization_id
        return f"urn:li:organization:{organization_id}"

    # Get the authenticated user's URN
    try:
        resp = _http_client.get(
            f"{LINKEDIN_API_BASE}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        sub = data.get("sub")
        if sub:
            return f"urn:li:person:{sub}"
    except Exception as e:
        logger.error(f"Error getting user info: {e}")

    raise ValueError("Could not determine author URN")


def upload_image_from_url(
    access_token: str,
    image_url: str,
    author_urn: str,
) -> str | None:
    """Download image from URL and upload to LinkedIn, returning the asset URN."""
    headers = linkedin_headers(access_token)

    try:
        # Step 1: Initialize upload
        init_data = {
            "initializeUploadRequest": {
                "owner": author_urn,
            }
        }

        init_resp = _http_client.post(
            f"{LINKEDIN_REST_BASE}/images?action=initializeUpload",
            headers=headers,
            json=init_data,
        )
        init_resp.raise_for_status()
        init_result = init_resp.json()

        upload_url = init_result.get("value", {}).get("uploadUrl")
        image_urn = init_result.get("value", {}).get("image")

        if not upload_url or not image_urn:
            logger.error("Failed to get upload URL from LinkedIn")
            return None

        # Step 2: Download image from URL
        img_resp = _http_client.get(image_url, follow_redirects=True)
        img_resp.raise_for_status()
        image_data = img_resp.content
        content_type = img_resp.headers.get("content-type", "image/jpeg")

        # Step 3: Upload to LinkedIn
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
        }
        upload_resp = _http_client.put(
            upload_url,
            headers=upload_headers,
            content=image_data,
        )
        upload_resp.raise_for_status()

        return image_urn

    except Exception as e:
        logger.error(f"Error uploading image: {e}")
        return None


def upload_document_from_url(
    access_token: str,
    document_url: str,
    author_urn: str,
) -> str | None:
    """Download document from URL and upload to LinkedIn, returning the asset URN."""
    headers = linkedin_headers(access_token)

    try:
        # Step 1: Initialize upload
        init_data = {
            "initializeUploadRequest": {
                "owner": author_urn,
            }
        }

        init_resp = _http_client.post(
            f"{LINKEDIN_REST_BASE}/documents?action=initializeUpload",
            headers=headers,
            json=init_data,
        )
        init_resp.raise_for_status()
        init_result = init_resp.json()

        upload_url = init_result.get("value", {}).get("uploadUrl")
        document_urn = init_result.get("value", {}).get("document")

        if not upload_url or not document_urn:
            logger.error("Failed to get upload URL from LinkedIn")
            return None

        # Step 2: Download document from URL
        doc_resp = _http_client.get(document_url, follow_redirects=True)
        doc_resp.raise_for_status()
        document_data = doc_resp.content
        content_type = doc_resp.headers.get("content-type", "application/pdf")

        # Step 3: Upload to LinkedIn
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
        }
        upload_resp = _http_client.put(
            upload_url,
            headers=upload_headers,
            content=document_data,
        )
        upload_resp.raise_for_status()

        return document_urn

    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        return None
