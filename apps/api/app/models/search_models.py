from typing import Union

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import MongoDocument


class URLRequest(BaseModel):
    urls: list[str]  # Always accept array of URLs


class URLResponse(BaseModel):
    title: Union[str, None] = None
    description: Union[str, None] = None
    favicon: Union[str, None] = None
    website_name: Union[str, None] = None
    website_image: Union[str, None] = None
    # str, not HttpUrl: email previews use bare addresses / mailto: targets
    url: str


class MultiURLResponse(BaseModel):
    results: dict[str, URLResponse]  # URL -> metadata mapping


class SearchUrlDocument(MongoDocument):
    """A scraped URL's metadata as cached in the ``search_urls`` collection.

    Global, keyed by ``url`` (the incidental Mongo ``_id`` is unused above the
    repository). Same shape as :class:`URLResponse`, which is the API projection.
    """

    url: str
    title: str | None = None
    description: str | None = None
    favicon: str | None = None
    website_name: str | None = None
    website_image: str | None = None


class SearchUrlUpdate(BaseModel):
    """Refreshable metadata fields for a cached URL."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    favicon: str | None = None
    website_name: str | None = None
    website_image: str | None = None
