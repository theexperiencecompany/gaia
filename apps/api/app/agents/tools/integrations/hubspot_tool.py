"""HubSpot tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio

from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from shared.py.wide_events import log

HUBSPOT_TOOLKIT = "HUBSPOT"


def register_hubspot_custom_tools(composio: Composio) -> list[str]:
    """Register HubSpot tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="HUBSPOT")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get HubSpot CRM context snapshot: recent contacts and deals.

        Zero required parameters. Returns current CRM state for situational awareness.
        """
        log.set(tool={"integration": "hubspot", "action": "gather_context"})
        user_id = auth_credentials.get("user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        contacts: list[dict[str, Any]] = []
        try:
            data = (
                proxy_request_sync(
                    user_id=user_id,
                    toolkit=HUBSPOT_TOOLKIT,
                    endpoint="https://api.hubapi.com/crm/v3/objects/contacts",
                    method="GET",
                    query={
                        "limit": 10,
                        "properties": "firstname,lastname,email,hs_lead_status",
                        "sort": "-createdate",
                    },
                )
                or {}
            )
            contacts = data.get("results", [])
        except Exception as e:
            log.debug(f"HubSpot contacts fetch failed: {e}")

        deals: list[dict[str, Any]] = []
        try:
            data = (
                proxy_request_sync(
                    user_id=user_id,
                    toolkit=HUBSPOT_TOOLKIT,
                    endpoint="https://api.hubapi.com/crm/v3/objects/deals",
                    method="GET",
                    query={
                        "limit": 10,
                        "properties": "dealname,amount,dealstage,closedate",
                        "sort": "-createdate",
                    },
                )
                or {}
            )
            deals = data.get("results", [])
        except Exception as e:
            log.debug(f"HubSpot deals fetch failed: {e}")

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
