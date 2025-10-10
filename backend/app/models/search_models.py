from typing import Dict, List, Optional, Union
from pydantic import BaseModel, HttpUrl


class URLRequest(BaseModel):
    urls: List[str]  # Always accept array of URLs


class URLResponse(BaseModel):
    title: Union[str, None] = None
    description: Union[str, None] = None
    favicon: Union[str, None] = None
    website_name: Union[str, None] = None
    website_image: Union[str, None] = None
    url: HttpUrl


class MultiURLResponse(BaseModel):
    results: Dict[str, URLResponse]  # URL -> metadata mapping


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
    web: Optional[List[WebResult]] = []
    images: Optional[List[ImageResult]] = []
    news: Optional[List[NewsResult]] = []
    videos: Optional[List[VideoResult]] = []


class DeepResearchResultsMedata(BaseModel):
    elapsed_time: Optional[float] = None
    query: Optional[str] = None
    total_content_size: Optional[int] = None


class DeepResearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    full_content: Optional[str] = None
    screenshot_url: Optional[str] = None
    fetch_error: Optional[str] = None
    source: Optional[str] = None
    date: Optional[str] = None


class DeepResearchResults(BaseModel):
    original_search: Optional[SearchResults] = None
    enhanced_results: Optional[List[DeepResearchResult]] = None
    metadata: Optional[DeepResearchResultsMedata] = None
    query: Optional[str] = None
    error: Optional[str] = None
