"""Google Meet custom tools using Composio custom tool infrastructure."""

import datetime

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.google_meet import (
    GoogleMeetEvent,
    GoogleMeetEventsPage,
    GoogleUserInfo,
)
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from shared.py.wide_events import log

GOOGLE_MEET_TOOLKIT = "GOOGLEMEET"


def register_google_meet_custom_tools(composio: Composio) -> list[str]:
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        me = GoogleUserInfo()
        try:
            me = GoogleUserInfo.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=GOOGLE_MEET_TOOLKIT,
                        endpoint="https://www.googleapis.com/oauth2/v3/userinfo",
                        method="GET",
                    )
                )
                or {}
            )
        except Exception as e:
            log.debug(
                f"{LogTag.TOOL} Google Meet userinfo fetch failed", error_type=type(e).__name__
            )

        # The calendar fetch may fail if the GOOGLEMEET connection lacks calendar
        # scope; match the legacy tool's status_code == 200 gate and empty-list
        # fallback so the tool still works with only profile access.
        events: list[GoogleMeetEvent] = []
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        try:
            events = GoogleMeetEventsPage.model_validate(
                proxy_request_sync(
                    ProxyRequest(
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
                )
                or {}
            ).items
        except Exception as e:
            log.debug(
                f"{LogTag.TOOL} Google Meet calendar fetch failed", error_type=type(e).__name__
            )

        upcoming_meets: list[dict[str, str | None]] = []
        for event in events:
            conf = event.conferenceData
            if conf is None:
                continue
            meet_link = next(
                (ep.uri for ep in conf.entryPoints if ep.entryPointType == "video"),
                None,
            )
            upcoming_meets.append(
                {
                    "id": event.id,
                    "summary": event.summary[:100],
                    "start": event.start.dateTime or event.start.date,
                    "meet_link": meet_link,
                }
            )

        return {
            "user": {
                "email": me.email,
                "name": me.name,
                "picture": me.picture,
            },
            "upcoming_meets": upcoming_meets,
            "upcoming_meet_count": len(upcoming_meets),
        }

    return ["GOOGLEMEET_CUSTOM_GATHER_CONTEXT"]
