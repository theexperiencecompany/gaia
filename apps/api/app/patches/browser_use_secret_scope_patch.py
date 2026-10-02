"""Put secret values only into the actions that type them, and only on each secret's own site.

Browser-Use replaces every <secret>name</secret> placeholder with its value in
the parameters of any action it executes. The done text then carries the
password (and Browser-Use logs it as the "Final Result"), and a jev goal the
agent wrote would carry it to Jev's decision model. Only input gets values:
send_keys types too, but Browser-Use logs its keys at INFO and keeps them in
the step's memory. Every other action keeps the placeholder.

Off a secret's site Browser-Use leaves its placeholder in the text and types
that literally, with only a log line. An input naming a secret it may not fill
there, or send_keys naming any, fails instead, saying so, and types nothing; so
does an input of a secret's bare name, its placeholder's tags dropped.

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

#: The one action whose typed text Browser-Use logs only by its placeholder name.
_SECRET_TYPING_ACTION = "input"  # nosec B105 -- a Browser-Use action name, not a credential
#: Types text as keys; Browser-Use logs those keys, so it never gets a secret's value.
_KEYS_ACTION = "send_keys"
#: Browser-Use's own placeholder pattern (Registry._replace_sensitive_data).
_PLACEHOLDER = re.compile(r"<secret>(.*?)</secret>")

_original_execute_action: Callable[..., Awaitable[object]] = Registry.execute_action


def _focused_url(browser_session: BrowserSession | None) -> str | None:
    """Return the address of the tab the action runs on, read as Browser-Use reads it to fill secrets."""
    if browser_session is None:
        return None
    focus = browser_session.agent_focus_target_id
    if focus is None:
        return None
    target = browser_session.session_manager.get_target(focus)
    if target is None:
        return None
    url: str = target.url
    return url


def _usable(sensitive_data: dict[str, str | dict[str, str]], url: str | None) -> set[str]:
    """Return the secret names Browser-Use fills on url; the run scopes every one to its own site."""
    names: set[str] = set()
    for pattern, values in sensitive_data.items():
        if (
            isinstance(values, dict)
            and url is not None
            and match_url_with_domain_pattern(url, pattern)
        ):
            names.update(values)
    return names


def _refusals(action_name: str, named: list[str], kwargs: dict[str, object]) -> list[str]:
    """Return why the action may not type the secrets it names, one line per secret."""
    if action_name == _KEYS_ACTION:
        # Keys never carry a value, so a placeholder there would be typed as it is.
        return [f"{name} is typed only into its field, never as keys" for name in named]
    if action_name != _SECRET_TYPING_ACTION:
        return []
    # Browser-Use's own keywords, passed with these types (Registry.execute_action).
    url = _focused_url(cast("BrowserSession | None", kwargs.get("browser_session")))
    secrets = cast("dict[str, str | dict[str, str]] | None", kwargs.get("sensitive_data"))
    usable = _usable(secrets or {}, url)
    host = (urlsplit(url).hostname if url else None) or "this page"
    return [f"{name} is not used on {host}" for name in named if name not in usable]


def _typed_name(action_name: str, params: dict[str, Any], kwargs: dict[str, object]) -> str | None:
    """Return the secret name an input would type as plain text: the placeholder's tags were dropped."""
    if action_name != _SECRET_TYPING_ACTION:
        return None
    secrets = cast("dict[str, str | dict[str, str]] | None", kwargs.get("sensitive_data"))
    names = {
        name for values in (secrets or {}).values() if isinstance(values, dict) for name in values
    }
    text = params.get("text")
    return text if isinstance(text, str) and text in names else None


async def _execute_action(
    self: Registry[Any], action_name: str, params: dict[str, Any], **kwargs: object
) -> object:
    """Execute the action, with secret values only for the input action on each secret's own site."""
    # Browser-Use passes everything by keyword; a positional call fails loudly here.
    if (name := _typed_name(action_name, params, kwargs)) is not None:
        return ActionResult(
            error=f"{name} is the name of a secret, not its value: type <secret>{name}</secret>; "
            "nothing was typed."
        )
    named = sorted(set(_PLACEHOLDER.findall(json.dumps(params))))
    if refused := _refusals(action_name, named, kwargs):
        return ActionResult(error=f"{'; '.join(refused)}; nothing was typed.")
    if action_name != _SECRET_TYPING_ACTION:
        kwargs["sensitive_data"] = None
    return await _original_execute_action(self, action_name=action_name, params=params, **kwargs)


def apply() -> None:
    """Scope placeholder substitution to the input action and to each secret's site."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind that keeps
    # mypy satisfied without an ignore.
    type.__setattr__(Registry, "execute_action", _execute_action)


apply()
