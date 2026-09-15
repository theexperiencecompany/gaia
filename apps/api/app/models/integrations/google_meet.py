"""Payloads the Google Meet tool reads: the OAuth2 profile and a Calendar events projection.

References: https://developers.google.com/identity/openid-connect/openid-connect#obtaininguserprofileinformation,
https://developers.google.com/workspace/calendar/api/v3/reference/events
"""

from pydantic import BaseModel, ConfigDict, Field

from app.models.calendar_models import GoogleCalendarEventDateTime


class GoogleUserInfo(BaseModel):
    """``GET /oauth2/v3/userinfo`` — every claim depends on the granted scopes."""

    model_config = ConfigDict(extra="ignore")

    email: str | None = None
    name: str | None = None
    picture: str | None = None


class GoogleConferenceEntryPoint(BaseModel):
    """One ``conferenceData.entryPoints`` item of a Calendar event."""

    model_config = ConfigDict(extra="ignore")

    entryPointType: str | None = None
    uri: str | None = None


class GoogleConferenceDataResource(BaseModel):
    """The ``conferenceData`` of a Calendar event as Google returns it."""

    model_config = ConfigDict(extra="ignore")

    entryPoints: list[GoogleConferenceEntryPoint] = Field(default_factory=list)


class GoogleMeetEvent(BaseModel):
    """A Calendar event under the ``items(id,summary,start,end,conferenceData,htmlLink)`` projection."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    summary: str = ""
    start: GoogleCalendarEventDateTime = Field(default_factory=GoogleCalendarEventDateTime)
    conferenceData: GoogleConferenceDataResource | None = None


class GoogleMeetEventsPage(BaseModel):
    """``events.list`` on the primary calendar — ``items`` is absent when empty."""

    model_config = ConfigDict(extra="ignore")

    items: list[GoogleMeetEvent] = Field(default_factory=list)
