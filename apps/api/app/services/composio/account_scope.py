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

from app.models.agent_config import ComposioAccountSelection
from app.services.integrations.integration_accounts import primary_connected_account_id
from app.utils.concurrency import run_on_captured_loop

_PRIMARY_LOOKUP_TIMEOUT_SECONDS = 10.0

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
        timeout=_PRIMARY_LOOKUP_TIMEOUT_SECONDS,
    )
