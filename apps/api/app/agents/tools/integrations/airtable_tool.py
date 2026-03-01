"""Airtable tools using Composio custom tool infrastructure.

These tools provide Airtable functionality using the access_token from Composio's
auth_credentials. Uses Airtable Metadata API for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

AIRTABLE_API_BASE = "https://api.airtable.com"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_airtable_custom_tools(composio: Composio) -> List[str]:
    """Register Airtable tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="AIRTABLE")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Airtable context snapshot: bases (workspaces) and their tables.

        Zero required parameters. Returns current workspace structure for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        headers = {"Authorization": f"Bearer {token}"}

        # List all bases
        bases_resp = _http_client.get(
            f"{AIRTABLE_API_BASE}/v0/meta/bases",
            headers=headers,
        )
        bases_resp.raise_for_status()
        bases_data = bases_resp.json()
        bases_raw = bases_data.get("bases", [])

        bases: List[Dict[str, Any]] = []
        for base in bases_raw[:3]:
            base_id = base.get("id", "")
            base_name = base.get("name", "")

            # Get tables for this base
            tables: List[Dict[str, Any]] = []
            try:
                tables_resp = _http_client.get(
                    f"{AIRTABLE_API_BASE}/v0/meta/bases/{base_id}/tables",
                    headers=headers,
                )
                tables_resp.raise_for_status()
                tables_data = tables_resp.json()
                tables = [
                    {"id": t.get("id"), "name": t.get("name")}
                    for t in tables_data.get("tables", [])
                ]
            except httpx.HTTPStatusError:
                pass

            bases.append({"id": base_id, "name": base_name, "tables": tables})

        return {
            "bases": bases,
            "base_count": len(bases_raw),
        }

    return ["AIRTABLE_CUSTOM_GATHER_CONTEXT"]
