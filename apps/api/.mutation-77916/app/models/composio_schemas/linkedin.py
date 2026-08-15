"""LinkedIn REST/v2 response shapes returned through Composio's proxy.

Only the fields `linkedin_utils` actually reads are declared; `extra="allow"`
keeps the rest of each response rather than dropping it.
"""

from pydantic import BaseModel, ConfigDict, Field


class LinkedInUserInfo(BaseModel):
    """``/v2/userinfo`` — the OpenID Connect profile. ``sub`` is the member id."""

    model_config = ConfigDict(extra="allow")

    sub: str | None = None


class LinkedInUploadTarget(BaseModel):
    """The ``value`` block of an ``initializeUpload`` response.

    Images and documents share this shape; each populates its own urn field
    (``image`` or ``document``) alongside the common ``uploadUrl``.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    upload_url: str | None = Field(default=None, alias="uploadUrl")
    image: str | None = None
    document: str | None = None


class LinkedInInitializeUploadResponse(BaseModel):
    """``/rest/{images,documents}?action=initializeUpload`` response."""

    model_config = ConfigDict(extra="allow")

    value: LinkedInUploadTarget | None = None
