"""
MCP OAuth Discovery Utilities.

Contains functions for OAuth discovery per MCP specification:
- WWW-Authenticate challenge extraction
- Protected Resource Metadata (RFC 9728) discovery
- Authorization Server Metadata (RFC 8414) discovery
"""

import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config.loggers import langchain_logger as logger


async def extract_auth_challenge(server_url: str) -> dict:
    """
    Probe MCP server and parse full WWW-Authenticate challenge per MCP spec.

    Per MCP Authorization spec Phase 1:
    - Server returns 401 with WWW-Authenticate header
    - Header may contain: resource_metadata, scope, error, error_description

    Returns dict with extracted fields (empty dict if no 401 or parse fails).
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(server_url, timeout=10)

            if response.status_code == 401:
                www_auth = response.headers.get("WWW-Authenticate", "")
                result = {"raw": www_auth}

                rm_match = re.search(r'resource_metadata="([^"]+)"', www_auth)
                if rm_match:
                    result["resource_metadata"] = rm_match.group(1)

                scope_match = re.search(r'scope="([^"]+)"', www_auth)
                if scope_match:
                    result["scope"] = scope_match.group(1)

                error_match = re.search(r'error="([^"]+)"', www_auth)
                if error_match:
                    result["error"] = error_match.group(1)

                error_desc_match = re.search(r'error_description="([^"]+)"', www_auth)
                if error_desc_match:
                    result["error_description"] = error_desc_match.group(1)

                logger.debug(f"Parsed WWW-Authenticate for {server_url}: {result}")
                return result

            return {}

    except Exception as e:
        logger.debug(f"Auth challenge probe failed for {server_url}: {e}")
        return {}


async def find_protected_resource_metadata(server_url: str) -> Optional[str]:
    """
    Find Protected Resource Metadata via well-known URIs per RFC 9728 Section 5.2.

    Per MCP spec Phase 2b, when no resource_metadata in WWW-Authenticate header,
    try well-known URIs in order:
    1. Path-aware: {origin}/.well-known/oauth-protected-resource{path}
    2. Root: {origin}/.well-known/oauth-protected-resource

    Returns the URL that responds with valid JSON, or None.
    """
    parsed = urlparse(server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

    candidates = []
    if path:
        candidates.append(f"{origin}/.well-known/oauth-protected-resource{path}")
    candidates.append(f"{origin}/.well-known/oauth-protected-resource")

    async with httpx.AsyncClient() as client:
        for url in candidates:
            try:
                response = await client.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if "authorization_servers" in data or "resource" in data:
                        logger.info(f"Found Protected Resource Metadata at {url}")
                        return url
            except Exception as e:
                logger.debug(f"PRM not found at {url}: {e}")

    return None


async def fetch_protected_resource_metadata(prm_url: str) -> dict:
    """
    Fetch Protected Resource Metadata (RFC 9728).

    Returns dict with 'authorization_servers', 'scopes_supported', etc.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(prm_url, timeout=10)
        response.raise_for_status()
        return response.json()


async def fetch_auth_server_metadata(auth_server_url: str) -> dict:
    """
    Fetch Authorization Server Metadata (RFC 8414).

    Per RFC 8414, for an issuer URL like https://auth.example.com/tenant1:
    - Path-aware: https://auth.example.com/.well-known/oauth-authorization-server/tenant1
    - Root: https://auth.example.com/.well-known/oauth-authorization-server

    Tries multiple discovery patterns and both OAuth and OIDC endpoints.
    """
    parsed = urlparse(auth_server_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

    candidate_urls = []

    if path:
        candidate_urls.append(f"{origin}/.well-known/oauth-authorization-server{path}")
        candidate_urls.append(f"{origin}/.well-known/openid-configuration{path}")

    candidate_urls.append(f"{origin}/.well-known/oauth-authorization-server")
    candidate_urls.append(f"{origin}/.well-known/openid-configuration")

    last_error = None
    async with httpx.AsyncClient() as client:
        for url in candidate_urls:
            try:
                response = await client.get(url, timeout=10)
                if response.status_code == 200:
                    logger.debug(f"Found auth server metadata at {url}")
                    return response.json()
            except Exception as e:
                logger.debug(f"Auth metadata not found at {url}: {e}")
                last_error = e

    error_msg = f"Failed to fetch auth server metadata for {auth_server_url}"
    logger.error(error_msg)
    raise Exception(error_msg) from last_error
