"""What find_elements and search_page found reaches the model, not only how many."""

from __future__ import annotations

from typing import Any

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools
import pytest

import app.patches.browser_use_read_result_patch as patch_module

pytestmark = pytest.mark.unit

MATCHES = "1. <a href='https://example.test/first'>First result</a>"


class _Action:
    """One of Browser-Use's action models: every action a field, only the chosen one set."""

    def __init__(self, name: str) -> None:
        self._name = name

    def model_dump(self, exclude_unset: bool = False) -> dict[str, Any]:
        fields: dict[str, Any] = dict.fromkeys(("find_elements", "search_page", "click"))
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


def test_apply_routes_every_action_through_the_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Tools, "act", None)

    patch_module.apply()

    assert Tools.act is patch_module._act
