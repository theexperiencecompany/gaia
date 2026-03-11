"""Google Maps custom tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

import httpx
from app.models.common_models import GatherContextInput
from composio import Composio

_http_client = httpx.Client(timeout=30)

MAPS_API_BASE = "https://maps.googleapis.com/maps/api"


def register_google_maps_custom_tools(composio: Composio) -> List[str]:
    @composio.tools.custom_tool(toolkit="GOOGLE_MAPS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Google Maps context snapshot: API connectivity and available services.

        Zero required parameters. Confirms API access and returns available capabilities.
        """
        token = auth_credentials.get("access_token")
        api_key = auth_credentials.get("api_key", "")

        if not token and not api_key:
            raise ValueError("Missing access_token or api_key in auth_credentials")

        # Use whichever auth method is available
        params: Dict[str, str] = {}
        headers: Dict[str, str] = {"Accept": "application/json"}

        if token:
            headers["Authorization"] = f"Bearer {token}"
        if api_key:
            params["key"] = api_key

        # Test geocoding API with a known location to confirm connectivity
        geocode_resp = _http_client.get(
            f"{MAPS_API_BASE}/geocode/json",
            headers=headers,
            params={**params, "address": "New York, NY", "result_type": "locality"},
        )

        connected = geocode_resp.status_code == 200
        status = "ok"
        if connected:
            data = geocode_resp.json()
            status = data.get("status", "UNKNOWN")

        return {
            "api_connected": connected and status == "OK",
            "status": status,
            "available_services": [
                "geocoding",
                "places",
                "directions",
                "distance_matrix",
                "elevation",
                "timezone",
            ],
        }

    return ["GOOGLE_MAPS_CUSTOM_GATHER_CONTEXT"]
