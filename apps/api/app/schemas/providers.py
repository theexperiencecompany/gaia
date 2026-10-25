"""Request schemas for the provider-credential setup surfaces."""

from pydantic import BaseModel

from app.constants.providers import PresetName


class ProviderCredentialBody(BaseModel):
    """Provider payload shared by upsert and test.

    ``preset`` prefills the endpoint + default model server-side so configuring
    OpenCode/Nous is paste-an-API-key-only.
    """

    preset: PresetName | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    account_id: str | None = None
    api_secret: str | None = None
