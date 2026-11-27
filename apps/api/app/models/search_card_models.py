"""The search_results card's payload: what a web search shows the user in the chat."""

from app.schemas.common import ResponseModel
from app.utils.search.models import SearchResultItem


class SearchResultCount(ResponseModel):
    """How many results of each kind the search card holds."""

    web: int
    images: int
    videos: int


class SearchResultsData(ResponseModel):
    """One web search's results; news and videos are always empty."""

    web: list[SearchResultItem]
    news: list[SearchResultItem]
    images: list[str]
    videos: list[str]
    query: str
    elapsed_time: float
    answer: str
    response_time: int
    request_id: str
    result_count: SearchResultCount
