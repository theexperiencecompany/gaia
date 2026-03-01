"""HubSpot tools using Composio custom tool infrastructure.

These tools provide HubSpot CRM functionality using the access_token from Composio's
auth_credentials. Uses HubSpot CRM API v3 for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

HUBSPOT_API_BASE = "https://api.hubapi.com"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_hubspot_custom_tools(composio: Composio) -> List[str]:
    """Register HubSpot tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="HUBSPOT")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get HubSpot CRM context snapshot: recent contacts and deals.

        Zero required parameters. Returns current CRM state for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Get recent contacts
        contacts_resp = _http_client.get(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts",
            headers=headers,
            params={
                "limit": 5,
                "properties": "firstname,lastname,email,hs_lead_status",
                "sort": "-createdate",
            },
        )
        contacts_resp.raise_for_status()
        contacts_data = contacts_resp.json()
        contacts = contacts_data.get("results", [])

        # Get recent deals
        deals_resp = _http_client.get(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/deals",
            headers=headers,
            params={
                "limit": 5,
                "properties": "dealname,amount,dealstage,closedate",
                "sort": "-createdate",
            },
        )
        deals_resp.raise_for_status()
        deals_data = deals_resp.json()
        deals = deals_data.get("results", [])

        return {
            "recent_contacts": [
                {
                    "id": c.get("id"),
                    "firstname": c.get("properties", {}).get("firstname"),
                    "lastname": c.get("properties", {}).get("lastname"),
                    "email": c.get("properties", {}).get("email"),
                    "lead_status": c.get("properties", {}).get("hs_lead_status"),
                }
                for c in contacts
            ],
            "recent_deals": [
                {
                    "id": d.get("id"),
                    "dealname": d.get("properties", {}).get("dealname"),
                    "amount": d.get("properties", {}).get("amount"),
                    "dealstage": d.get("properties", {}).get("dealstage"),
                    "closedate": d.get("properties", {}).get("closedate"),
                }
                for d in deals
            ],
            "contact_count": len(contacts),
            "deal_count": len(deals),
        }

    return ["HUBSPOT_CUSTOM_GATHER_CONTEXT"]
