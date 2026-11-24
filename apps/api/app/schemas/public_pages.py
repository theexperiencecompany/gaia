"""Body of the call that tells the web server its cached public pages are out of date."""

from pydantic import BaseModel, Field

from app.constants.public_pages import PublicPageDomain


class PublicPagesChanged(BaseModel):
    """Data shown on cached public pages changed."""

    domain: PublicPageDomain = Field(description="The data that changed")
