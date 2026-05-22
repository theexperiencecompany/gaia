"""Google Maps custom tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio

from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.errors import AppError
from shared.py.wide_events import log

MAPS_API_BASE = "https://maps.googleapis.com/maps/api"
MAPS_TOOLKIT = "GOOGLE_MAPS"


def register_google_maps_custom_tools(composio: Composio) -> list[str]:
    @composio.tools.custom_tool(toolkit="GOOGLE_MAPS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Google Maps context snapshot: API connectivity and available services.

        Zero required parameters. Confirms API access and returns available capabilities.
        """
        user_id = auth_credentials.get("user_id")
        if not user_id:
            raise AppError(
                message="Missing user_id in auth_credentials",
                why="CUSTOM_GATHER_CONTEXT requires a user-scoped auth context",
                status_code=500,
            )

        try:
            data = (
                proxy_request_sync(
                    user_id=user_id,
                    toolkit=MAPS_TOOLKIT,
                    endpoint=f"{MAPS_API_BASE}/geocode/json",
                    method="GET",
                    query={"address": "New York, NY", "result_type": "locality"},
                )
                or {}
            )
            status = data.get("status", "UNKNOWN")
            connected = status == "OK"
        except Exception as e:
            log.debug(f"Google Maps integration failed: {e}")
            status = "ERROR"
            connected = False

        return {
            "api_connected": connected,
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
