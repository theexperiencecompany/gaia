"""The seam where a tracked todo run's own Gmail fetch meets the Inbox desk's mail buckets.

The bucketing reads the desk's todo and asks JEV, both above this Composio layer, so
startup installs it here instead of this layer importing it back.
"""

from collections.abc import Callable, Coroutine

from app.models.composio_schemas.gmail import GmailMessageView

# (user_id, todo_id, fetched) -> the same messages in order, each bucketed where it could be.
FetchedMailBucketer = Callable[
    [str, str, list[GmailMessageView]], Coroutine[object, None, list[GmailMessageView]]
]

_installed: list[FetchedMailBucketer] = []


def install_fetched_mail_bucketer(bucketer: FetchedMailBucketer) -> None:
    """Install what buckets a todo run's fetch; startup calls it once per process."""
    _installed[:] = [bucketer]


def installed_fetched_mail_bucketer() -> FetchedMailBucketer | None:
    """Return the installed bucketer, or None in a process that never ran startup."""
    return _installed[0] if _installed else None
