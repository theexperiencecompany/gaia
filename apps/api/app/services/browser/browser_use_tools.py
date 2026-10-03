"""GaiaTools: Browser-Use's Tools as a run uses them, scoping secrets and showing what reads found.

Secrets: Browser-Use puts a <secret>name</secret> value into the parameters of
any action. Only input gets values, and only on the secret's own site; an input
naming one it may not fill there, a send_keys naming any (its keys are logged
and kept in memory), or an input of a secret's bare name fails and types nothing.

Reads: find_elements and search_page results are flagged read-once, or the model
sees only their count; extract's result carries the page's real title.
Pinned to browser-use==0.11.13.
"""

from __future__ import annotations

import json
import re
from typing import TypedDict
from urllib.parse import urlsplit

from browser_use.agent.views import ActionResult
from browser_use.browser.session import BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.utils import match_url_with_domain_pattern
from pydantic import TypeAdapter
from typing_extensions import override

from app.services.browser.browser_use_session import GaiaBrowserSession

#: The one action whose typed text Browser-Use logs only by its placeholder name.
_SECRET_TYPING_ACTION = "input"  # nosec B105 -- a Browser-Use action name, not a credential
#: Types text as keys; Browser-Use logs those keys, so it never gets a secret's value.
_KEYS_ACTION = "send_keys"
#: Browser-Use's own placeholder pattern (Registry._replace_sensitive_data).
_PLACEHOLDER = re.compile(r"<secret>(.*?)</secret>")
#: The actions whose matches are otherwise summarised away.
_READ_ACTIONS = frozenset({"find_elements", "search_page"})
#: The action that reads a page's content without its title.
_EXTRACT_ACTION = "extract"

SensitiveData = dict[str, str | dict[str, str]]


def _focused_url(browser_session: BrowserSession) -> str | None:
    """Return the address of the tab the action runs on, read as Browser-Use reads it to fill secrets."""
    focus = browser_session.agent_focus_target_id
    target = browser_session.session_manager.get_target(focus) if focus else None
    if target is None:
        return None
    url: str = target.url
    return url


def _names(sensitive_data: SensitiveData, url: str | None = None) -> set[str]:
    """Return the secret names given, or only those Browser-Use fills on url's page."""
    return {
        name
        for pattern, values in sensitive_data.items()
        if isinstance(values, dict) and (url is None or match_url_with_domain_pattern(url, pattern))
        for name in values
    }


class _Typed(TypedDict, total=False):
    """Browser-Use's input action, read for the text it types."""

    text: str


_TYPED: TypeAdapter[_Typed] = TypeAdapter(_Typed)


def _refusal(
    name: str, params: object, sensitive_data: SensitiveData, url: str | None
) -> str | None:
    """Return why the action may not type the secrets it names on url's page, or None when it may."""
    typed: _Typed = _TYPED.validate_python(params) if name == _SECRET_TYPING_ACTION else {}
    text = typed.get("text")
    if text is not None and text in _names(sensitive_data):
        return (
            f"{text} is the name of a secret, not its value: type <secret>{text}</secret>; "
            "nothing was typed."
        )
    named = sorted(set(_PLACEHOLDER.findall(json.dumps(params))))
    if name == _KEYS_ACTION:
        # Keys never carry a value, so a placeholder there would be typed as it is.
        refused = [f"{secret} is typed only into its field, never as keys" for secret in named]
    elif name == _SECRET_TYPING_ACTION:
        usable = _names(sensitive_data, url) if url is not None else set()
        host = (urlsplit(url).hostname if url else None) or "this page"
        refused = [f"{secret} is not used on {host}" for secret in named if secret not in usable]
    else:
        refused = []
    return f"{'; '.join(refused)}; nothing was typed." if refused else None


class GaiaTools(Tools[None]):
    """The run's actions: secrets only where they are typed, and reads shown in full."""

    @override
    async def act(
        self,
        action: ActionModel,
        browser_session: BrowserSession,
        page_extraction_llm: BaseChatModel | None = None,
        sensitive_data: SensitiveData | None = None,
        available_file_paths: list[str] | None = None,
        file_system: FileSystem | None = None,
        extraction_schema: dict[str, object] | None = None,
    ) -> ActionResult:
        """Run the action with secret values only where they are typed; a read's result is shown in full."""
        [(name, params)] = action.model_dump(exclude_unset=True).items()
        url = _focused_url(browser_session)
        if refused := _refusal(name, params, sensitive_data or {}, url):
            return ActionResult(error=refused)
        result = await super().act(
            action=action,
            browser_session=browser_session,
            page_extraction_llm=page_extraction_llm,
            sensitive_data=sensitive_data if name == _SECRET_TYPING_ACTION else None,
            available_file_paths=available_file_paths,
            file_system=file_system,
            extraction_schema=extraction_schema,
        )
        if result.error or not result.extracted_content:
            return result
        if name in _READ_ACTIONS:
            result.include_extracted_content_only_once = True
        # The page's markdown has no <title>: asked for it, extract said "Not available".
        if name == _EXTRACT_ACTION and isinstance(browser_session, GaiaBrowserSession):
            title = await browser_session.document_title()
            if title:
                titled = f"<page_title>\n{title}\n</page_title>\n{result.extracted_content}"
                if result.long_term_memory == result.extracted_content:
                    result.long_term_memory = titled
                result.extracted_content = titled
        return result
