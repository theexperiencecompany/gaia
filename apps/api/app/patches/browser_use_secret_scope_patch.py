"""Put secret values only into the actions that type them into the page.

Browser-Use replaces every <secret>name</secret> placeholder with its value in
the parameters of any action it executes. The done text then carries the
password (and Browser-Use logs it as the "Final Result"), and a jev goal the
agent wrote would carry it to Jev's decision model. Measured 2026-09-25: the
agent's done text for the selenium form held the typed password in its URL.
Only input and send_keys put text into the page, so only they get values;
every other action keeps the placeholder.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from browser_use.tools.registry.service import Registry

#: The actions whose parameters reach the page as typed text.
_TYPING_ACTIONS = frozenset({"input", "send_keys"})

_original_execute_action: Callable[..., Awaitable[object]] = Registry.execute_action


async def _execute_action(
    self: Registry[Any], action_name: str, params: dict[str, Any], **kwargs: object
) -> object:
    """Execute the action, with secret values only for a typing action."""
    # Browser-Use passes everything by keyword; a positional call fails loudly here.
    if action_name not in _TYPING_ACTIONS:
        kwargs["sensitive_data"] = None
    return await _original_execute_action(self, action_name=action_name, params=params, **kwargs)


def apply() -> None:
    """Scope placeholder substitution to the typing actions."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind that keeps
    # mypy satisfied without an ignore.
    type.__setattr__(Registry, "execute_action", _execute_action)


apply()
