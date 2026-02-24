from typing import Dict, List, Union
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
