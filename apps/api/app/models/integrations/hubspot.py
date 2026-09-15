"""HubSpot CRM v3 payloads the HubSpot tool reads.

Reference: https://developers.hubspot.com/docs/reference/api/crm/objects/contacts
(the same object envelope serves /crm/v3/objects/deals).
"""

from pydantic import BaseModel, ConfigDict, Field


class HubSpotContactProperties(BaseModel):
    """The ``properties`` map of a contact under the projection the tool requests.

    HubSpot returns a requested property the record has no value for as ``null``.
    """

    model_config = ConfigDict(extra="ignore")

    firstname: str | None = None
    lastname: str | None = None
    email: str | None = None
    hs_lead_status: str | None = None


class HubSpotDealProperties(BaseModel):
    """The ``properties`` map of a deal under the projection the tool requests."""

    model_config = ConfigDict(extra="ignore")

    dealname: str | None = None
    amount: str | None = None
    dealstage: str | None = None
    closedate: str | None = None


class HubSpotContact(BaseModel):
    """One ``results`` item of ``GET /crm/v3/objects/contacts``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    properties: HubSpotContactProperties = Field(default_factory=HubSpotContactProperties)


class HubSpotDeal(BaseModel):
    """One ``results`` item of ``GET /crm/v3/objects/deals``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    properties: HubSpotDealProperties = Field(default_factory=HubSpotDealProperties)


class HubSpotContactsPage(BaseModel):
    """``GET /crm/v3/objects/contacts`` — ``paging`` is ignored."""

    model_config = ConfigDict(extra="ignore")

    results: list[HubSpotContact] = Field(default_factory=list)


class HubSpotDealsPage(BaseModel):
    """``GET /crm/v3/objects/deals`` — ``paging`` is ignored."""

    model_config = ConfigDict(extra="ignore")

    results: list[HubSpotDeal] = Field(default_factory=list)
