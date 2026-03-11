"""HubSpot tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.config.loggers import chat_logger as logger
from app.models.common_models import GatherContextInput


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

        contacts: List[Dict[str, Any]] = []
        try:
            resp = httpx.get(
                "https://api.hubapi.com/crm/v3/objects/contacts",
                headers=headers,
                params={
                    "limit": 10,
                    "properties": "firstname,lastname,email,hs_lead_status",
                    "sort": "-createdate",
                },
                timeout=15,
            )
            resp.raise_for_status()
            contacts = resp.json().get("results", [])
        except Exception as e:
            logger.debug(f"HubSpot contacts fetch failed: {e}")

        deals: List[Dict[str, Any]] = []
        try:
            resp = httpx.get(
                "https://api.hubapi.com/crm/v3/objects/deals",
                headers=headers,
                params={
                    "limit": 10,
                    "properties": "dealname,amount,dealstage,closedate",
                    "sort": "-createdate",
                },
                timeout=15,
            )
            resp.raise_for_status()
            deals = resp.json().get("results", [])
        except Exception as e:
            logger.debug(f"HubSpot deals fetch failed: {e}")

        recent_contacts = [
            {
                "id": c.get("id"),
                "firstname": c.get("properties", {}).get("firstname"),
                "lastname": c.get("properties", {}).get("lastname"),
                "email": c.get("properties", {}).get("email"),
                "lead_status": c.get("properties", {}).get("hs_lead_status"),
            }
            for c in contacts
        ]
        recent_deals = [
            {
                "id": d.get("id"),
                "dealname": d.get("properties", {}).get("dealname"),
                "amount": d.get("properties", {}).get("amount"),
                "dealstage": d.get("properties", {}).get("dealstage"),
                "closedate": d.get("properties", {}).get("closedate"),
            }
            for d in deals
        ]

        return {
            "recent_contacts": recent_contacts,
            "recent_deals": recent_deals,
            "contact_count": len(contacts),
            "deal_count": len(deals),
        }

    return ["HUBSPOT_CUSTOM_GATHER_CONTEXT"]
