"""HubSpot tools using Composio custom tool infrastructure."""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.hubspot import (
    HubSpotContact,
    HubSpotContactsPage,
    HubSpotDeal,
    HubSpotDealsPage,
)
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from shared.py.wide_events import log

HUBSPOT_TOOLKIT = "HUBSPOT"


def register_hubspot_custom_tools(composio: Composio) -> list[str]:
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        contacts: list[HubSpotContact] = []
        try:
            contacts = HubSpotContactsPage.model_validate(
                proxy_request_sync(
                    ProxyRequest(
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
                )
                or {}
            ).results
        except Exception as e:
            log.debug(f"{LogTag.TOOL} HubSpot contacts fetch failed", error_type=type(e).__name__)

        deals: list[HubSpotDeal] = []
        try:
            deals = HubSpotDealsPage.model_validate(
                proxy_request_sync(
                    ProxyRequest(
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
                )
                or {}
            ).results
        except Exception as e:
            log.debug(f"{LogTag.TOOL} HubSpot deals fetch failed", error_type=type(e).__name__)

        recent_contacts = [
            {
                "id": c.id,
                "firstname": c.properties.firstname,
                "lastname": c.properties.lastname,
                "email": c.properties.email,
                "lead_status": c.properties.hs_lead_status,
            }
            for c in contacts
        ]
        recent_deals = [
            {
                "id": d.id,
                "dealname": d.properties.dealname,
                "amount": d.properties.amount,
                "dealstage": d.properties.dealstage,
                "closedate": d.properties.closedate,
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
