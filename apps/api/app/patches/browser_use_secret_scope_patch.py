"""Put secret values only into the actions that type them, and only on each secret's own site.

Browser-Use replaces every <secret>name</secret> placeholder with its value in
the parameters of any action it executes. The done text then carries the
password (and Browser-Use logs it as the "Final Result"), and a jev goal the
agent wrote would carry it to Jev's decision model. Measured 2026-09-25: the
agent's done text for the selenium form held the typed password in its URL.
Only input and send_keys put text into the page, so only they get values;
every other action keeps the placeholder.

Off a secret's site Browser-Use leaves its placeholder in the text and types
that literally, with only a log line. A typing action naming a secret it may
not fill there fails instead, saying so, and types nothing.

Pinned to browser-use==0.11.13; the import fails loudly if the method moves.
"""

from collections.abc import Awaitable, Callable
import json
import re
from typing import Any, cast
from urllib.parse import urlsplit

from browser_use.agent.views import ActionResult
from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.utils import match_url_with_domain_pattern

#: The actions whose parameters reach the page as typed text.
_TYPING_ACTIONS = frozenset({"input", "send_keys"})
#: Browser-Use's own placeholder pattern (Registry._replace_sensitive_data).
_PLACEHOLDER = re.compile(r"<secret>(.*?)</secret>")

_original_execute_action: Callable[..., Awaitable[object]] = Registry.execute_action


def _focused_url(browser_session: BrowserSession | None) -> str | None:
    """Return the address of the tab the action runs on, read as Browser-Use reads it to fill secrets."""
    if browser_session is None or browser_session.agent_focus_target_id is None:
        return None
    target = browser_session.session_manager.get_target(browser_session.agent_focus_target_id)
    if target is None:
        return None
    url: str = target.url
    return url


def _usable(sensitive_data: dict[str, str | dict[str, str]], url: str | None) -> set[str]:
    """Return the secret names Browser-Use fills on url: each scoped one only on its own site."""
    names: set[str] = set()
    for pattern, values in sensitive_data.items():
        if not isinstance(values, dict):
            names.add(pattern)
        elif url is not None and match_url_with_domain_pattern(url, pattern):
            names.update(values)
    return names


async def _execute_action(
    self: Registry[Any], action_name: str, params: dict[str, Any], **kwargs: object
) -> object:
    """Execute the action, with secret values only for a typing action on each secret's own site."""
    # Browser-Use passes everything by keyword; a positional call fails loudly here.
    if action_name not in _TYPING_ACTIONS:
        kwargs["sensitive_data"] = None
        return await _original_execute_action(
            self, action_name=action_name, params=params, **kwargs
        )
    named = set(_PLACEHOLDER.findall(json.dumps(params)))
    # Browser-Use's own keywords, passed with these types (Registry.execute_action).
    url = _focused_url(cast("BrowserSession | None", kwargs.get("browser_session")))
    secrets = cast("dict[str, str | dict[str, str]] | None", kwargs.get("sensitive_data"))
    withheld = sorted(named - _usable(secrets or {}, url))
    if withheld:
        host = (urlsplit(url).hostname if url else None) or "this page"
        return ActionResult(
            error=f"{', '.join(withheld)} is not used on {host}; nothing was typed."
        )
    return await _original_execute_action(self, action_name=action_name, params=params, **kwargs)


def apply() -> None:
    """Scope placeholder substitution to the typing actions and to each secret's site."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind that keeps
    # mypy satisfied without an ignore.
    type.__setattr__(Registry, "execute_action", _execute_action)


apply()
