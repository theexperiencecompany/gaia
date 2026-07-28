from typing import Union

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import MongoDocument
from app.models.conversation_models import ConversationDescriptionHit, ConversationMessageHit
from app.models.notes_models import NoteSearchHit
from app.utils.search.models import WebSearchResult


class URLRequest(BaseModel):
    urls: list[str]  # Always accept array of URLs


class EmailSearchResponse(BaseModel):
    """Contact-email addresses extracted from a web search, plus the raw search data."""

    emails: list[str]
    combined_text: str
    search_data: WebSearchResult


class MessageSearchResult(ConversationMessageHit):
    """A message hit from keyword search, with its highlighting snippet."""

    snippet: str


class NoteSearchResult(NoteSearchHit):
    """A note hit from keyword search, with its highlighting snippet."""

    snippet: str


class SearchResultsResponse(BaseModel):
    """Keyword search results across messages, conversations, and notes."""

    messages: list[MessageSearchResult]
    conversations: list[ConversationDescriptionHit]
    notes: list[NoteSearchResult]


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
