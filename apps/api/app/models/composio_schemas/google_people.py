"""Google People API shapes returned through Composio's Gmail toolkit.

``GMAIL_GET_CONTACTS`` and ``GMAIL_SEARCH_PEOPLE`` both answer with People API
``person`` resources, so the same models describe both. Every field is optional:
People only returns the field groups the request's read mask asked for, and
``extra="allow"`` keeps the rest of the resource rather than dropping it.
"""

from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class GooglePersonFieldMetadata(BaseModel):
    """The ``metadata`` block on a person field, flagging the primary entry."""

    model_config = ConfigDict(extra="allow")

    primary: bool | None = None


class GooglePersonName(BaseModel):
    """One entry of a person's ``names``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    display_name: str | None = Field(default=None, alias="displayName")
    metadata: GooglePersonFieldMetadata | None = None


class GooglePersonValue(BaseModel):
    """One entry of ``emailAddresses`` or ``phoneNumbers`` — both are ``{value, metadata}``."""

    model_config = ConfigDict(extra="allow")

    value: str | None = None
    metadata: GooglePersonFieldMetadata | None = None


class GooglePerson(BaseModel):
    """A People API ``person`` resource."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    resource_name: str | None = Field(default=None, alias="resourceName")
    names: list[GooglePersonName] = Field(default_factory=list)
    email_addresses: list[GooglePersonValue] = Field(default_factory=list, alias="emailAddresses")
    phone_numbers: list[GooglePersonValue] = Field(default_factory=list, alias="phoneNumbers")


class GooglePeopleSearchResult(BaseModel):
    """One entry of a ``people:searchContacts`` result list."""

    model_config = ConfigDict(extra="allow")

    person: GooglePerson = Field(default_factory=GooglePerson)


class GoogleContactsResponseData(BaseModel):
    """The ``response_data`` payload of ``GMAIL_GET_CONTACTS``."""

    model_config = ConfigDict(extra="allow")

    connections: list[GooglePerson] = Field(default_factory=list)


class GooglePeopleSearchResponseData(BaseModel):
    """The ``response_data`` payload of ``GMAIL_SEARCH_PEOPLE``."""

    model_config = ConfigDict(extra="allow")

    results: list[GooglePeopleSearchResult] = Field(default_factory=list)


class ContactCard(TypedDict):
    """A person flattened to their primary name/email/phone, for the chat UI.

    Every field is optional because People may send a key as an explicit
    ``null``, which the hook forwards untouched rather than normalizing — see
    ``_contact_card``.
    """

    name: str | None
    email: str | None
    phone: str | None
    resource_name: str | None


class ContactSummary(TypedDict):
    """The same contact trimmed for the LLM — blank fields are omitted, not sent empty."""

    name: str | None
    email: NotRequired[str]
    phone: NotRequired[str]
