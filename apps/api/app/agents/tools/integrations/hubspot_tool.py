"""HubSpot tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.json_helpers import dict_bag, list_bag, text_opt_bag
from shared.py.wide_events import log

HUBSPOT_TOOLKIT = "HUBSPOT"


def register_hubspot_custom_tools(composio: Composio[Any, Any]) -> list[str]:
    """Register HubSpot tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="HUBSPOT")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get HubSpot CRM context snapshot: recent contacts and deals.

        Zero required parameters. Returns current CRM state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "hubspot", "action": "gather_context"})
        user_id = text_opt_bag(auth_credentials, "user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        contacts: list[dict[str, object]] = []
        try:
            response = proxy_request_sync(
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
            data = response if isinstance(response, dict) else {}
            contacts = [c for c in list_bag(data, "results") if isinstance(c, dict)]
        except Exception as e:
            log.debug(f"{LogTag.TOOL} HubSpot contacts fetch failed", error_type=type(e).__name__)

        deals: list[dict[str, object]] = []
        try:
            response = proxy_request_sync(
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
            data = response if isinstance(response, dict) else {}
            deals = [d for d in list_bag(data, "results") if isinstance(d, dict)]
        except Exception as e:
            log.debug(f"{LogTag.TOOL} HubSpot deals fetch failed", error_type=type(e).__name__)

        recent_contacts = [
            {
                "id": c.get("id"),
                "firstname": text_opt_bag(dict_bag(c, "properties"), "firstname"),
                "lastname": text_opt_bag(dict_bag(c, "properties"), "lastname"),
                "email": text_opt_bag(dict_bag(c, "properties"), "email"),
                "lead_status": text_opt_bag(dict_bag(c, "properties"), "hs_lead_status"),
            }
            for c in contacts
        ]
        recent_deals = [
            {
                "id": d.get("id"),
                "dealname": text_opt_bag(dict_bag(d, "properties"), "dealname"),
                "amount": text_opt_bag(dict_bag(d, "properties"), "amount"),
                "dealstage": text_opt_bag(dict_bag(d, "properties"), "dealstage"),
                "closedate": text_opt_bag(dict_bag(d, "properties"), "closedate"),
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
