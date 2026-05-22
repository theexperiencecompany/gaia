from typing import Union

from pydantic import BaseModel, HttpUrl


class URLRequest(BaseModel):
    urls: list[str]  # Always accept array of URLs


class URLResponse(BaseModel):
    title: Union[str, None] = None
    description: Union[str, None] = None
    favicon: Union[str, None] = None
    website_name: Union[str, None] = None
    website_image: Union[str, None] = None
    url: HttpUrl


class MultiURLResponse(BaseModel):
    results: dict[str, URLResponse]  # URL -> metadata mapping


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str
    source: str
    date: str


class ImageResult(BaseModel):
    title: str
    url: str
    thumbnail: str
    source: str


class NewsResult(BaseModel):
    title: str
    url: str
    snippet: str
    source: str
    date: str


class VideoResult(BaseModel):
    title: str
    url: str
    thumbnail: str
    source: str


class SearchResults(BaseModel):
    web: list[WebResult] | None = []
    images: list[ImageResult] | None = []
    news: list[NewsResult] | None = []
    videos: list[VideoResult] | None = []


class DeepResearchResultsMedata(BaseModel):
    elapsed_time: float | None = None
    query: str | None = None
    total_content_size: int | None = None


class DeepResearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    full_content: str | None = None
    screenshot_url: str | None = None
    fetch_error: str | None = None
    source: str | None = None
    date: str | None = None


class DeepResearchResults(BaseModel):
    original_search: SearchResults | None = None
    enhanced_results: list[DeepResearchResult] | None = None
    metadata: DeepResearchResultsMedata | None = None
    query: str | None = None
    error: str | None = None
