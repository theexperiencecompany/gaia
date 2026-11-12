"""Check the URLs a shared HTML or SVG file names against Google Web Risk."""

import asyncio

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config.settings import settings
from app.constants.short_links import (
    WEB_RISK_CONCURRENCY,
    WEB_RISK_MAX_URLS,
    WEB_RISK_SEARCH_URL,
    WEB_RISK_THREAT_TYPES,
    WEB_RISK_TIMEOUT_SECONDS,
)
from app.utils.errors import AppError


class _Threat(BaseModel):
    threat_types: list[str] = Field(alias="threatTypes")


class _SearchResponse(BaseModel):
    threat: _Threat | None = None


def _unavailable(cause: str) -> AppError:
    return AppError(
        message="This file couldn't be checked for unsafe links right now",
        why="Google Web Risk is unavailable",
        fix="Try sharing it again in a minute",
        status_code=503,
        code="web_risk_unavailable",
        meta={"cause": cause},
    )


async def _flagged(client: httpx.AsyncClient, key: str, url: str, gate: asyncio.Semaphore) -> bool:
    params: list[tuple[str, str | int | float | bool | None]] = [("uri", url), ("key", key)]
    params += [("threatTypes", threat) for threat in WEB_RISK_THREAT_TYPES]
    async with gate:
        try:
            response = await client.get(WEB_RISK_SEARCH_URL, params=params)
            response.raise_for_status()
            return _SearchResponse.model_validate(response.json()).threat is not None
        except (httpx.HTTPError, ValueError, ValidationError) as e:
            raise _unavailable(type(e).__name__) from e


async def flagged_urls(urls: list[str]) -> bool:
    """Whether any of urls is a known threat; False without a Web Risk key (self-host, development)."""
    key = settings.GOOGLE_WEB_RISK_API_KEY
    if key is None:
        return False
    if len(urls) > WEB_RISK_MAX_URLS:
        return True
    gate = asyncio.Semaphore(WEB_RISK_CONCURRENCY)
    async with httpx.AsyncClient(timeout=WEB_RISK_TIMEOUT_SECONDS) as client:
        results = await asyncio.gather(*(_flagged(client, key, url, gate) for url in urls))
    return any(results)
