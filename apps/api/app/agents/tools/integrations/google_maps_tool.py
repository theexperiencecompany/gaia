"""Google Maps custom tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.errors import AppError
from app.utils.json_helpers import text_bag
from shared.py.wide_events import log

MAPS_API_BASE = "https://maps.googleapis.com/maps/api"
MAPS_TOOLKIT = "GOOGLE_MAPS"


def register_google_maps_custom_tools(composio: Composio[Any, Any]) -> list[str]:
    @composio.tools.custom_tool(toolkit="GOOGLE_MAPS")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Google Maps context snapshot: API connectivity and available services.

        Zero required parameters. Confirms API access and returns available capabilities.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = auth_credentials.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise AppError(
                message="Missing user_id in auth_credentials",
                why="CUSTOM_GATHER_CONTEXT requires a user-scoped auth context",
                status_code=500,
            )

        try:
            response = proxy_request_sync(
                user_id=user_id,
                toolkit=MAPS_TOOLKIT,
                endpoint=f"{MAPS_API_BASE}/geocode/json",
                method="GET",
                query={"address": "New York, NY", "result_type": "locality"},
            )
            data = response if isinstance(response, dict) else {}
            status = text_bag(data, "status", "UNKNOWN")
            connected = status == "OK"
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Google Maps integration failed", error_type=type(e).__name__)
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
