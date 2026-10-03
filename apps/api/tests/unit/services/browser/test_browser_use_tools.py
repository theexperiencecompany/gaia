"""The run's Browser-Use tools: a secret's value goes only into the input that types it on its site, and reads are shown in full."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from browser_use.agent.views import ActionResult
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from pydantic import PrivateAttr
import pytest

from app.services.browser.browser_use_session import GaiaBrowserSession
from app.services.browser.browser_use_tools import GaiaTools

pytestmark = pytest.mark.unit

SECRETS: dict[str, str | dict[str, str]] = {"https://example.test": {"password": "hunter2"}}
MATCHES = "1. <a href='https://example.test/first'>First result</a>"
READ = "<url>\nhttps://example.com\n</url>\n<result>\nDocument page title: Not available\n</result>"


class _Actions(ActionModel):
    """Some of Browser-Use's actions, as an agent step names one of them."""

    input: dict[str, Any] | None = None
    send_keys: dict[str, Any] | None = None
    done: dict[str, Any] | None = None
    jev: dict[str, Any] | None = None
    navigate: dict[str, Any] | None = None
    click: dict[str, Any] | None = None
    find_elements: dict[str, Any] | None = None
    search_page: dict[str, Any] | None = None
    extract: dict[str, Any] | None = None


class _BrowserUse:
    """Browser-Use's own act: records what it was asked to run and answers with result."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = ActionResult()


@pytest.fixture
def browser_use(monkeypatch: pytest.MonkeyPatch) -> _BrowserUse:
    fake = _BrowserUse()

    async def _act(tools: Tools[None], **kwargs: Any) -> ActionResult:
        fake.calls.append(kwargs)
        return fake.result

    monkeypatch.setattr(Tools, "act", _act)
    return fake


class _Page(GaiaBrowserSession):
    """The run's session with its focused tab on url (no tab for None), titled title."""

    _title: str | None = PrivateAttr(default=None)

    def __init__(self, url: str | None, title: str | None = None) -> None:
        super().__init__(cdp_url="ws://host.test/x", user_id=None)
        self.agent_focus_target_id = "tab-1" if url else None
        self.session_manager = SimpleNamespace(get_target={"tab-1": SimpleNamespace(url=url)}.get)
        self._title = title

    async def document_title(self) -> str | None:
        return self._title


async def _act(name: str, params: dict[str, Any], page: _Page) -> ActionResult:
    action = _Actions(**{name: params})
    return await GaiaTools().act(action=action, browser_session=page, sensitive_data=SECRETS)


async def test_the_input_action_gets_the_secret_values_on_its_site(
    browser_use: _BrowserUse,
) -> None:
    page = _Page("https://example.test/login")

    await _act("input", {"index": 3, "text": "<secret>password</secret>"}, page)

    [call] = browser_use.calls
    assert (call["browser_session"], call["sensitive_data"]) == (page, SECRETS)


async def test_a_typing_action_naming_a_secret_it_cannot_fill_fails_and_types_nothing(
    browser_use: _BrowserUse,
) -> None:
    text = {"index": 3, "text": "<secret>user</secret> <secret>password</secret>"}

    off_site = await _act("input", text, _Page("https://evil.test/"))
    no_tab = await _act("input", text, _Page(None))
    # Browser-Use logs send_keys' keys at INFO and keeps them in the step's memory.
    as_keys = await _act(
        "send_keys", {"keys": "<secret>password</secret>"}, _Page("https://example.test/login")
    )
    # The agent dropped the tags and wrote "password": the field got the word, not the secret.
    bare = await _act("input", {"index": 3, "text": "password"}, _Page("https://example.test/"))

    assert browser_use.calls == []
    assert off_site.error == (
        "password is not used on evil.test; user is not used on evil.test; nothing was typed."
    )
    assert no_tab.error == (
        "password is not used on this page; user is not used on this page; nothing was typed."
    )
    assert as_keys.error == (
        "password is typed only into its field, never as keys; nothing was typed."
    )
    assert bare.error == (
        "password is the name of a secret, not its value: type <secret>password</secret>; "
        "nothing was typed."
    )


@pytest.mark.parametrize("name", ["done", "jev", "navigate", "click"])
async def test_every_other_action_keeps_the_placeholder(
    browser_use: _BrowserUse, name: str
) -> None:
    await _act(name, {"text": "<secret>password</secret>"}, _Page("https://example.test/"))

    [call] = browser_use.calls
    assert call["sensitive_data"] is None


@pytest.mark.parametrize("name", ["find_elements", "search_page"])
async def test_a_read_actions_matches_are_shown_to_the_model_at_its_next_step(
    browser_use: _BrowserUse, name: str
) -> None:
    """DuckDuckGo: three find_elements, each read by the model as "Found 1 element"."""
    browser_use.result = ActionResult(extracted_content=MATCHES, long_term_memory="Found 1")

    result = await _act(name, {"query": "a"}, _Page("https://example.test/"))

    assert result.include_extracted_content_only_once is True


@pytest.mark.parametrize(
    ("name", "result"),
    [
        ("click", ActionResult(extracted_content="Clicked First result")),
        ("find_elements", ActionResult(extracted_content=MATCHES, error="page changed")),
        ("extract", ActionResult(extracted_content=READ, error="page changed")),
        ("extract", ActionResult(extracted_content=None)),
    ],
)
async def test_any_other_result_is_left_as_browser_use_gave_it(
    browser_use: _BrowserUse, name: str, result: ActionResult
) -> None:
    browser_use.result = result.model_copy()

    returned = await _act(name, {"query": "a"}, _Page("https://example.test/", "Example"))

    assert returned == result


async def test_an_extract_carries_the_pages_real_title(browser_use: _BrowserUse) -> None:
    """The page's markdown has no <title>: asked for it, extract said "Not available"."""
    browser_use.result = ActionResult(extracted_content=READ, long_term_memory=READ)

    result = await _act("extract", {"query": "title"}, _Page("https://example.com/", "Example"))

    assert result.extracted_content == f"<page_title>\nExample\n</page_title>\n{READ}"
    assert result.long_term_memory == result.extracted_content
    untitled = ActionResult(extracted_content=READ)
    browser_use.result = untitled.model_copy()
    assert await _act("extract", {"query": "t"}, _Page("https://example.com/")) == untitled
