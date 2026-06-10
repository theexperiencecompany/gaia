"""Google Meet custom tools using Composio custom tool infrastructure."""

import datetime
from typing import Any

from composio import Composio

from app.models.common_models import GatherContextInput
from app.services.composio.proxy_client import proxy_request_sync
from shared.py.wide_events import log

GOOGLE_MEET_TOOLKIT = "GOOGLEMEET"


def register_google_meet_custom_tools(composio: Composio) -> list[str]:
    @composio.tools.custom_tool(toolkit="GOOGLEMEET")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Google Meet context snapshot: upcoming meetings with Meet links.

        Zero required parameters. Returns user profile and scheduled Meet calls.
        """
        user_id = auth_credentials.get("user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        me: dict[str, Any] = {}
        try:
            me = (
                proxy_request_sync(
                    user_id=user_id,
                    toolkit=GOOGLE_MEET_TOOLKIT,
                    endpoint="https://www.googleapis.com/oauth2/v3/userinfo",
                    method="GET",
                )
                or {}
            )
        except Exception as e:
            log.debug(f"Google Meet userinfo fetch failed: {e}")

        # The calendar fetch may fail if the GOOGLEMEET connection lacks
        # calendar scope. The legacy tool gated on status_code == 200 and
        # returned an empty list — preserve that behavior so the whole tool
        # doesn't error out when only the profile is accessible.
        events_data: dict[str, Any] = {}
        now = datetime.datetime.utcnow().isoformat() + "Z"
        try:
            events_data = (
                proxy_request_sync(
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
                or {}
            )
        except Exception as e:
            log.debug(f"Google Meet calendar fetch failed: {e}")

        upcoming_meets: list[dict[str, Any]] = []
        for event in events_data.get("items", []):
            conf = event.get("conferenceData", {})
            if not conf:
                continue
            entry_points = conf.get("entryPoints", [])
            meet_link = next(
                (ep.get("uri") for ep in entry_points if ep.get("entryPointType") == "video"),
                None,
            )
            start = event.get("start", {})
            upcoming_meets.append(
                {
                    "id": event.get("id"),
                    "summary": event.get("summary", "")[:100],
                    "start": start.get("dateTime") or start.get("date"),
                    "meet_link": meet_link,
                }
            )

        return {
            "user": {
                "email": me.get("email"),
                "name": me.get("name"),
                "picture": me.get("picture"),
            },
            "upcoming_meets": upcoming_meets,
            "upcoming_meet_count": len(upcoming_meets),
        }

    return ["GOOGLEMEET_CUSTOM_GATHER_CONTEXT"]
