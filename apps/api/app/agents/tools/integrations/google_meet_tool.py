"""Google Meet custom tools using Composio custom tool infrastructure."""

import datetime
from typing import Any, Dict, List

import httpx
from app.models.common_models import GatherContextInput
from composio import Composio

_http_client = httpx.Client(timeout=30)


def register_google_meet_custom_tools(composio: Composio) -> List[str]:
    @composio.tools.custom_tool(toolkit="GOOGLEMEET")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Google Meet context snapshot: upcoming meetings with Meet links.

        Zero required parameters. Returns user profile and scheduled Meet calls.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        # Get user profile
        me_resp = _http_client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers=headers,
        )
        me_resp.raise_for_status()
        me = me_resp.json()

        # Get upcoming calendar events that have conferenceData (Meet links)
        now = datetime.datetime.utcnow().isoformat() + "Z"
        events_resp = _http_client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=headers,
            params={
                "timeMin": now,
                "maxResults": 5,
                "singleEvents": "true",
                "orderBy": "startTime",
                "fields": "items(id,summary,start,end,conferenceData,htmlLink)",
            },
        )
        upcoming_meets: List[Dict[str, Any]] = []
        if events_resp.status_code == 200:
            items = events_resp.json().get("items", [])
            for event in items:
                conf = event.get("conferenceData", {})
                if not conf:
                    continue
                entry_points = conf.get("entryPoints", [])
                meet_link = next(
                    (
                        ep.get("uri")
                        for ep in entry_points
                        if ep.get("entryPointType") == "video"
                    ),
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
