"""Google Maps custom tools using Composio custom tool infrastructure."""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.google_maps import GoogleGeocodeResponse
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from app.utils.errors import AppError
from shared.py.wide_events import log

MAPS_API_BASE = "https://maps.googleapis.com/maps/api"
MAPS_TOOLKIT = "GOOGLE_MAPS"


def register_google_maps_custom_tools(composio: Composio) -> list[str]:
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
        try:
            user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
        except ValueError as e:
            raise AppError(
                message="Missing user_id in auth_credentials",
                why="CUSTOM_GATHER_CONTEXT requires a user-scoped auth context",
            ) from e

        try:
            status = GoogleGeocodeResponse.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=MAPS_TOOLKIT,
                        endpoint=f"{MAPS_API_BASE}/geocode/json",
                        method="GET",
                        query={"address": "New York, NY", "result_type": "locality"},
                    )
                )
                or {}
            ).status
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
