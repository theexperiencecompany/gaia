"""The run's Browser-Use tools: a secret's value goes only into the input that types it on its site, and reads are shown in full."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from browser_use.agent.views import ActionResult
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from pydantic import PrivateAttr
import pytest

from app.constants.browser import BROWSER_CODE_BOXES_TO_JEV, BrowserEngine
from app.schemas.browser import BrowserAction
from app.services.browser.browser_use_session import GaiaBrowserSession
from app.services.browser.browser_use_tools import GaiaTools
from app.services.browser.jev.tool import Bursts, JevDelegate, register_jev

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
    _elements: dict[int, Any] = PrivateAttr(default_factory=dict)

    def __init__(
        self, url: str | None, title: str | None = None, elements: dict[int, Any] | None = None
    ) -> None:
        super().__init__(cdp_url="ws://host.test/x", user_id=None, engine=BrowserEngine.CHROMIUM)
        self.agent_focus_target_id = "tab-1" if url else None
        self.session_manager = SimpleNamespace(get_target={"tab-1": SimpleNamespace(url=url)}.get)
        self._title = title
        self._elements = elements or {}

    async def document_title(self) -> str | None:
        return self._title

    async def get_element_by_index(self, index: int) -> Any:
        return self._elements.get(index)


async def _act(name: str, params: dict[str, Any], page: _Page) -> ActionResult:
    action = _Actions(**{name: params})
    return await GaiaTools().act(action=action, browser_session=page, sensitive_data=SECRETS)


async def test_the_input_action_gets_the_secret_values_on_its_site(
    browser_use: _BrowserUse,
) -> None:
    page = _Page("https://example.test/login")
    action = _Actions(input={"index": 3, "text": "<secret>password</secret>"})
    context: dict[str, Any] = {
        "page_extraction_llm": object(),
        "available_file_paths": ["a.pdf"],
        "file_system": object(),
        "extraction_schema": {"type": "object"},
    }

    await GaiaTools().act(action, page, sensitive_data=SECRETS, **context)

    # Everything else reaches Browser-Use as it was given.
    assert browser_use.calls == [
        {"action": action, "browser_session": page, "sensitive_data": SECRETS, **context}
    ]


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


def _node(name: str, attributes: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        node_name=name, attributes=attributes or {}, parent_node=None, children_nodes=[]
    )


def _adopt(parent: SimpleNamespace, *children: SimpleNamespace) -> None:
    parent.children_nodes = [*parent.children_nodes, *children]
    for child in children:
        child.parent_node = parent


def _code_boxes(boxes: int = 8, *, container: str = "FORM", halves: bool = False) -> dict[int, Any]:
    """Build a code entry by index: one-character boxes, a read-only dash after the fourth, in container.

    With halves, each side of the dash sits in its own wrapper, as GitHub lays its code out.
    """
    outer = _node(container)
    holders = [_node("DIV"), _node("DIV")] if halves else [outer]
    if halves:
        _adopt(outer, *holders)
    for n in range(boxes):
        holder = holders[min(n // 4, len(holders) - 1)]
        _adopt(holder, _node("INPUT", {"maxlength": "1"}))
        if n == 3:
            _adopt(holder, _node("INPUT", {"readonly": ""}))
    _adopt(_node("BODY"), outer)
    return {10 + n: box for n, box in enumerate(b for h in holders for b in h.children_nodes)}


def _no_bursts() -> Bursts:
    raise AssertionError("typing into a box never runs Jev")


async def _no_emit(actions: list[BrowserAction], url: str, title: str) -> None:
    raise AssertionError("typing into a box never shows a burst")


async def _typed(
    browser_use: _BrowserUse, elements: dict[int, Any], index: int, *, jev: bool = True
) -> ActionResult:
    """Type one character into the element at index, on a run whose tools have jev or not."""
    tools = GaiaTools()
    if jev:
        register_jev(tools, JevDelegate(runner_for=_no_bursts, emit=_no_emit))
    page = _Page("https://github.com/login/device", elements=elements)
    action = _Actions(input={"index": index, "text": "E"})
    return await tools.act(action=action, browser_session=page, sensitive_data=SECRETS)


async def test_a_code_split_into_boxes_is_never_typed_box_by_box(browser_use: _BrowserUse) -> None:
    """Regression for GAIA-715: the agent typed GitHub's device code box by box and lost characters."""
    result = await _typed(browser_use, _code_boxes(), 11)

    assert result.error == BROWSER_CODE_BOXES_TO_JEV.format(count=8)
    assert browser_use.calls == []


@pytest.mark.parametrize(
    "boxes", [_code_boxes(halves=True), _code_boxes(container="DIV")], ids=["halves", "no-form"]
)
async def test_boxes_split_across_their_form_or_in_no_form_are_one_code(
    browser_use: _BrowserUse, boxes: dict[int, Any]
) -> None:
    result = await _typed(browser_use, boxes, 10)

    assert result.error == BROWSER_CODE_BOXES_TO_JEV.format(count=8)


async def test_four_boxes_make_a_code_and_three_do_not(browser_use: _BrowserUse) -> None:
    four = await _typed(browser_use, _code_boxes(4), 10)
    three = await _typed(browser_use, _code_boxes(3), 10)

    assert four.error == BROWSER_CODE_BOXES_TO_JEV.format(count=4)
    assert three.error is None
    assert len(browser_use.calls) == 1


@pytest.mark.parametrize(
    "target",
    [_node("DIV", {"maxlength": "1"}), _node("INPUT")],
    ids=["one-character-non-input", "input-of-any-length"],
)
async def test_a_field_beside_a_code_is_typed_as_asked(
    browser_use: _BrowserUse, target: SimpleNamespace
) -> None:
    boxes = _code_boxes()
    _adopt(next(iter(boxes.values())).parent_node, target)

    result = await _typed(browser_use, {**boxes, 3: target}, 3)

    assert result.error is None
    assert len(browser_use.calls) == 1


async def test_a_run_without_jev_types_into_a_code_box_as_asked(
    browser_use: _BrowserUse,
) -> None:
    """With BROWSER_JEV off there is no jev to hand the code to, so the agent's input runs."""
    result = await _typed(browser_use, _code_boxes(), 11, jev=False)

    assert result.error is None
    assert len(browser_use.calls) == 1


async def test_an_element_the_page_no_longer_has_is_left_to_browser_use(
    browser_use: _BrowserUse,
) -> None:
    result = await _typed(browser_use, {}, 3)

    assert result.error is None
    assert len(browser_use.calls) == 1
