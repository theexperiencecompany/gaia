"""Airtable Meta API payloads the context tool reads.

Reference: https://airtable.com/developers/web/api/list-bases and
https://airtable.com/developers/web/api/get-base-schema
"""

from pydantic import BaseModel, ConfigDict, Field


class AirtableBase(BaseModel):
    """One ``bases[]`` entry of ``GET /v0/meta/bases``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


class AirtableBaseList(BaseModel):
    """``AIRTABLE_LIST_BASES`` data — the ``bases`` page."""

    model_config = ConfigDict(extra="ignore")

    bases: list[AirtableBase] = Field(default_factory=list)


class AirtableTable(BaseModel):
    """One ``tables[]`` entry of ``GET /v0/meta/bases/{baseId}/tables``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


class AirtableBaseSchema(BaseModel):
    """``AIRTABLE_GET_BASE_SCHEMA`` data — the base's tables."""

    model_config = ConfigDict(extra="ignore")

    tables: list[AirtableTable] = Field(default_factory=list)
