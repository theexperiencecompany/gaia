"""The seam where a tracked todo run's own Gmail fetch meets that todo's trigger gate.

The gate lives in app.services.triggers, which imports this Composio layer, so startup
installs it here instead of this layer importing it back.
"""

from collections.abc import Callable, Coroutine

from app.models.composio_schemas.gmail import GmailMessageView

# (user_id, todo_id, fetched) -> the messages the todo's gate lets through.
FetchedMailGate = Callable[
    [str, str, list[GmailMessageView]], Coroutine[object, None, list[GmailMessageView]]
]

_installed: list[FetchedMailGate] = []


def install_fetched_mail_gate(gate: FetchedMailGate) -> None:
    """Install the gate a todo run's fetch passes; startup calls it once per process."""
    _installed[:] = [gate]


def installed_fetched_mail_gate() -> FetchedMailGate | None:
    """Return the installed gate, or None in a process that never ran startup."""
    return _installed[0] if _installed else None
