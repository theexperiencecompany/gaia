"""Which connected account a Composio tool call acts as, for the sync code that runs it.

Dispatch chooses the account (async, before the call); the tool wrapper opens a
scope around the synchronous execution; the before-execute hook (native tools)
and the proxy client (custom tools) read it. Composio's custom-tool runner only
forwards user_id, so a context variable is the one channel that reaches the
proxy. With no scope — trigger option lookups, background jobs — the primary
account is resolved, so no call ever lets Composio pick an account itself.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from composio import before_execute
from composio.types import ToolExecuteParams

from app.config.oauth_config import get_integration_by_toolkit
from app.constants.integrations import PRIMARY_ACCOUNT_LOOKUP_TIMEOUT_SECONDS
from app.models.agent_config import ComposioAccountSelection
from app.services.integrations.integration_accounts import primary_connected_account_id
from app.utils.concurrency import run_on_captured_loop

_selected_account: ContextVar[ComposioAccountSelection | None] = ContextVar(
    "composio_selected_account", default=None
)


@contextmanager
def account_scope(selection: ComposioAccountSelection | None) -> Iterator[None]:
    token = _selected_account.set(selection)
    try:
        yield
    finally:
        _selected_account.reset(token)


def current_selection(toolkit: str) -> ComposioAccountSelection | None:
    selection = _selected_account.get()
    if selection is None or selection.toolkit.upper() != toolkit.upper():
        return None
    return selection


def scoped_connected_account_id(user_id: str, toolkit: str) -> str:
    """Return the account this call acts as on toolkit: the scoped choice, else the primary.

    Sync, for executor threads; the primary lookup runs on the server loop.
    """
    selection = current_selection(toolkit)
    if selection is not None:
        return selection.connected_account_id
    return run_on_captured_loop(
        primary_connected_account_id(user_id, toolkit),
        timeout=PRIMARY_ACCOUNT_LOOKUP_TIMEOUT_SECONDS,
    )


def pin_connected_account(tool: str, toolkit: str, params: ToolExecuteParams) -> ToolExecuteParams:
    """Name the account a native tool call acts as, so Composio never picks one of several itself.

    A before-execute modifier. Catalog toolkits with no GAIA integration hold no
    accounts of ours to choose from.
    """
    del tool  # the modifier signature Composio calls
    user_id = params.get("user_id")
    if user_id and get_integration_by_toolkit(toolkit) is not None:
        params["connected_account_id"] = scoped_connected_account_id(user_id, toolkit)
    return params


# For a direct tools.execute, which runs no hook pipeline: pins the account all the same.
PIN_ACCOUNT_MODIFIER = before_execute(pin_connected_account)
