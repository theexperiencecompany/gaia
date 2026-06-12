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
