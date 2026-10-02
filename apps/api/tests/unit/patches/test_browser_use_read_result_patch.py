"""What find_elements and search_page found reaches the model, not only how many."""

from __future__ import annotations

from typing import Any, cast

from browser_use import Browser
from browser_use.agent.views import ActionResult
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
import pytest

import app.patches.browser_use_read_result_patch as patch_module
from tests.unit.patches.test_browser_use_page_title_patch import page_answers

pytestmark = pytest.mark.unit

MATCHES = "1. <a href='https://example.test/first'>First result</a>"


class _Action:
    """One of Browser-Use's action models: every action a field, only the chosen one set."""

    def __init__(self, name: str) -> None:
        self._name = name

    def model_dump(self, exclude_unset: bool = False) -> dict[str, Any]:
        fields: dict[str, Any] = dict.fromkeys(("find_elements", "search_page", "click", "extract"))
        fields[self._name] = {"query": "a"}
        return {self._name: fields[self._name]} if exclude_unset else fields


def _returns(result: ActionResult, calls: list[dict[str, Any]]) -> Any:
    async def _original(self: object, **kwargs: Any) -> ActionResult:
        calls.append({"tools": self, **kwargs})
        return result

    return _original


@pytest.mark.parametrize("name", ["find_elements", "search_page"])
async def test_a_read_actions_matches_are_shown_to_the_model_at_its_next_step(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    calls: list[dict[str, Any]] = []
    found = ActionResult(extracted_content=MATCHES, long_term_memory="Found 1 element")
    monkeypatch.setattr(patch_module, "_original_act", _returns(found, calls))
    action, tools = _Action(name), Tools()

    result = await patch_module._act(tools, action, browser_session="session")  # type: ignore[arg-type]  # a duck-typed action model

    assert result.include_extracted_content_only_once is True
    assert calls == [{"tools": tools, "action": action, "browser_session": "session"}]


@pytest.mark.parametrize(
    ("name", "result"),
    [
        ("click", ActionResult(extracted_content="Clicked First result")),
        ("find_elements", ActionResult(extracted_content=MATCHES, error="page changed")),
        ("find_elements", ActionResult(extracted_content=None)),
    ],
)
async def test_any_other_result_is_left_as_browser_use_gave_it(
    monkeypatch: pytest.MonkeyPatch, name: str, result: ActionResult
) -> None:
    monkeypatch.setattr(patch_module, "_original_act", _returns(result, []))

    returned = await patch_module._act(Tools(), _Action(name))  # type: ignore[arg-type]  # a duck-typed action model

    assert returned.include_extracted_content_only_once is False


_READ = (
    "<url>\nhttps://example.com\n</url>\n<result>\nDocument page title: Not available\n</result>"
)


async def _extract(monkeypatch: pytest.MonkeyPatch, given: ActionResult) -> ActionResult:
    monkeypatch.setattr(patch_module, "_original_act", _returns(given, []))
    extract = cast(ActionModel, _Action("extract"))
    session = Browser(cdp_url="ws://host.test/x")
    return await patch_module._act(Tools(), extract, browser_session=session)


async def test_an_extract_carries_the_pages_real_title(monkeypatch: pytest.MonkeyPatch) -> None:
    """The page's markdown has no <title>: asked for it, extract said "Not available"."""
    reads = page_answers(monkeypatch, {"result": {"type": "string", "value": " Example Domain "}})

    result = await _extract(
        monkeypatch, ActionResult(extracted_content=_READ, long_term_memory=_READ)
    )

    # Read on the run's tab without taking focus from it.
    assert reads == [(False, {"expression": "document.title", "returnByValue": True}, "s1")]
    assert result.extracted_content == f"<page_title>\nExample Domain\n</page_title>\n{_READ}"
    assert result.long_term_memory == result.extracted_content


@pytest.mark.parametrize(
    "given",
    [
        ActionResult(extracted_content=_READ, error="page changed"),
        ActionResult(extracted_content=None),
    ],
)
async def test_an_extract_that_failed_or_read_nothing_is_left_untitled(
    monkeypatch: pytest.MonkeyPatch, given: ActionResult
) -> None:
    reads = page_answers(monkeypatch, {"result": {"type": "string", "value": "Example Domain"}})

    result = await _extract(monkeypatch, given)

    assert (reads, result.extracted_content) == ([], given.extracted_content)


async def test_a_page_with_no_title_leaves_the_extract_untitled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_answers(monkeypatch, {"result": {"type": "string", "value": ""}})

    result = await _extract(monkeypatch, ActionResult(extracted_content=_READ))

    assert result.extracted_content == _READ


def test_apply_routes_every_action_through_the_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Tools, "act", None)

    patch_module.apply()

    assert Tools.act is patch_module._act
