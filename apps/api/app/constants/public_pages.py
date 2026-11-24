"""The web server's cached public pages, which the API clears when their data changes."""

from enum import StrEnum


class PublicPageDomain(StrEnum):
    """Data a cached public page shows; the web app owns which pages each value clears."""

    INTEGRATIONS = "integrations"
    WORKFLOWS = "workflows"


#: The OpenAPI webhook that documents the call, so the web app's types follow PublicPageDomain.
PUBLIC_PAGES_CHANGED_WEBHOOK = "public-pages-changed"
#: The web server's route handler (apps/web/src/app/api/public-pages/revalidate/route.ts).
PUBLIC_PAGES_REVALIDATE_PATH = "/api/public-pages/revalidate"
#: Per attempt. The publisher's request waits on it, since their browser opens the page next.
PUBLIC_PAGES_REVALIDATE_TIMEOUT_SECONDS = 3.0
PUBLIC_PAGES_REVALIDATE_ATTEMPTS = 3
PUBLIC_PAGES_REVALIDATE_RETRY_WAIT_SECONDS = 0.3
