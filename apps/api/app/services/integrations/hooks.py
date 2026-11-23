"""What a feature declares to follow a user's integrations as they connect and disconnect."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

#: Called with the user id and the integration id.
IntegrationHook = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class IntegrationHooks:
    """One subscriber's hooks; a connect hook is best-effort, a disconnect hook's failure fails the disconnect."""

    name: str
    on_connected: IntegrationHook
    on_disconnected: IntegrationHook
