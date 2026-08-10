"""Typed results shared by search providers and the search engine."""

from pydantic import BaseModel, Field


class SearchResultItem(BaseModel):  # type: ignore[explicit-any]
    """A single web result in the shape the agent and frontend consume."""

    url: str
    title: str = ""
    content: str = ""
    score: float = 0.5
    published_date: str = ""
    favicon: str = ""


class SearchResponse(BaseModel):  # type: ignore[explicit-any]
    """The outcome of one search, from a single provider or the whole engine."""

    results: list[SearchResultItem] = Field(default_factory=list)
    answer: str = ""
    images: list[str] = Field(default_factory=list)
    provider: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.results


class WebSearchResult(BaseModel):  # type: ignore[explicit-any]
    """The wire shape ``perform_search`` returns: results plus the query echoed back."""

    web: list[SearchResultItem] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    answer: str = ""
    query: str
    provider: str | None = None
