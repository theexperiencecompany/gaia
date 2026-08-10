"""Google Meet custom tools using Composio custom tool infrastructure."""

import datetime
from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.json_helpers import dict_bag, list_bag, text_bag, text_opt_bag
from shared.py.wide_events import log

GOOGLE_MEET_TOOLKIT = "GOOGLEMEET"


def register_google_meet_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
    @composio.tools.custom_tool(toolkit="GOOGLEMEET")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Google Meet context snapshot: upcoming meetings with Meet links.

        Zero required parameters. Returns user profile and scheduled Meet calls.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = auth_credentials.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        me: dict[str, object] = {}
        try:
            me_response = proxy_request_sync(
                user_id=user_id,
                toolkit=GOOGLE_MEET_TOOLKIT,
                endpoint="https://www.googleapis.com/oauth2/v3/userinfo",
                method="GET",
            )
            if isinstance(me_response, dict):
                me = me_response
        except Exception as e:
            log.debug(
                f"{LogTag.TOOL} Google Meet userinfo fetch failed", error_type=type(e).__name__
            )

        # The calendar fetch may fail if the GOOGLEMEET connection lacks
        # calendar scope. The legacy tool gated on status_code == 200 and
        # returned an empty list — preserve that behavior so the whole tool
        # doesn't error out when only the profile is accessible.
        events_data: dict[str, object] = {}
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        try:
            events_response = proxy_request_sync(
                user_id=user_id,
                toolkit=GOOGLE_MEET_TOOLKIT,
                endpoint="https://www.googleapis.com/calendar/v3/calendars/primary/events",
                method="GET",
                query={
                    "timeMin": now,
                    "maxResults": 5,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "fields": "items(id,summary,start,end,conferenceData,htmlLink)",
                },
            )
            if isinstance(events_response, dict):
                events_data = events_response
        except Exception as e:
            log.debug(
                f"{LogTag.TOOL} Google Meet calendar fetch failed", error_type=type(e).__name__
            )

        upcoming_meets: list[dict[str, object]] = []
        for event in list_bag(events_data, "items"):
            if not isinstance(event, dict):
                continue
            conf = dict_bag(event, "conferenceData")
            if not conf:
                continue
            entry_points = list_bag(conf, "entryPoints")
            meet_link = next(
                (
                    text_opt_bag(ep, "uri")
                    for ep in entry_points
                    if isinstance(ep, dict) and text_bag(ep, "entryPointType") == "video"
                ),
                None,
            )
            start = dict_bag(event, "start")
            upcoming_meets.append(
                {
                    "id": text_opt_bag(event, "id"),
                    "summary": (text_bag(event, "summary") or "")[:100],
                    "start": text_opt_bag(start, "dateTime") or text_opt_bag(start, "date"),
                    "meet_link": meet_link,
                }
            )

        return {
            "user": {
                "email": text_opt_bag(me, "email"),
                "name": text_opt_bag(me, "name"),
                "picture": text_opt_bag(me, "picture"),
            },
            "upcoming_meets": upcoming_meets,
            "upcoming_meet_count": len(upcoming_meets),
        }

    return ["GOOGLEMEET_CUSTOM_GATHER_CONTEXT"]
