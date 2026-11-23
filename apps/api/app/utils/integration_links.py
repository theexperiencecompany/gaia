"""In-app links into the web integrations page; apps/web useIntegrationDeepLink reads their params."""

from urllib.parse import urlencode

INTEGRATIONS_PAGE_PATH = "/integrations"


def integration_connect_path(integration_id: str, account_id: str | None = None) -> str:
    """Return the in-app path that starts connecting integration_id, or reconnecting account_id.

    ?connect= starts the connect flow on arrival; ?id= would only open the sidebar.
    """
    params = {"connect": integration_id}
    if account_id:
        params["account"] = account_id
    return f"{INTEGRATIONS_PAGE_PATH}?{urlencode(params)}"
