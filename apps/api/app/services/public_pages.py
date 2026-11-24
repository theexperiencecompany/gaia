"""Tell the web server that data its cached public pages show has changed."""

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_fixed,
)

from app.config.settings import settings
from app.constants.http import INTERNAL_CALLER_HEADER
from app.constants.public_pages import (
    PUBLIC_PAGES_REVALIDATE_ATTEMPTS,
    PUBLIC_PAGES_REVALIDATE_PATH,
    PUBLIC_PAGES_REVALIDATE_RETRY_WAIT_SECONDS,
    PUBLIC_PAGES_REVALIDATE_TIMEOUT_SECONDS,
    PublicPageDomain,
)
from app.schemas.public_pages import PublicPagesChanged
from shared.py.wide_events import log

_FIRST_SERVER_ERROR_STATUS = 500


def _is_transient(error: BaseException) -> bool:
    """Whether another attempt can succeed: the web server was unreachable or answered 5xx."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= _FIRST_SERVER_ERROR_STATUS
    return isinstance(error, httpx.TransportError)


async def _post_change(token: str, change: PublicPagesChanged) -> None:
    retrying = AsyncRetrying(
        stop=stop_after_attempt(PUBLIC_PAGES_REVALIDATE_ATTEMPTS),
        wait=wait_fixed(PUBLIC_PAGES_REVALIDATE_RETRY_WAIT_SECONDS),
        retry=retry_if_exception(_is_transient),
        reraise=True,
    )
    async with httpx.AsyncClient(timeout=PUBLIC_PAGES_REVALIDATE_TIMEOUT_SECONDS) as client:
        async for attempt in retrying:
            with attempt:
                response = await client.post(
                    f"{settings.WEB_INTERNAL_URL}{PUBLIC_PAGES_REVALIDATE_PATH}",
                    json=change.model_dump(mode="json"),
                    headers={INTERNAL_CALLER_HEADER: token},
                )
                response.raise_for_status()


async def invalidate_public_pages(domain: PublicPageDomain) -> None:
    """Clear the web server's cached pages for domain, after the change is stored.

    Never raises: the change is already saved, so a lost call is logged and the
    pages stay as they were until their daily rebuild or the domain's next change.
    """
    token = settings.INTERNAL_API_TOKEN
    if not token:
        log.warning(
            "Public pages not invalidated: INTERNAL_API_TOKEN is not set",
            public_pages_domain=domain.value,
        )
        return
    try:
        await _post_change(token, PublicPagesChanged(domain=domain))
    except httpx.HTTPError as e:
        log.error(
            "Public page invalidation failed",
            public_pages_domain=domain.value,
            error=str(e),
            error_type=type(e).__name__,
        )
        return
    log.set_ns("public_pages", invalidated=domain.value)
