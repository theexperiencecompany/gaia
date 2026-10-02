"""The tab list the agent sees each step titles its page from the document."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from browser_use import Browser
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import TabInfo
import pytest

import app.patches.browser_use_page_title_patch as patch_module
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


def page_answers(
    monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any] | Exception
) -> list[tuple[bool, dict[str, Any], str]]:
    """Fake the page's CDP session: record each read (focus, params, session), answer it."""
    reads: list[tuple[bool, dict[str, Any], str]] = []

    async def _cdp(self: BrowserSession, focus: bool = True) -> Any:
        async def _evaluate(params: dict[str, Any], session_id: str) -> dict[str, Any]:
            reads.append((focus, params, session_id))
            if isinstance(answer, Exception):
                raise answer
            return answer

        runtime = SimpleNamespace(evaluate=_evaluate)
        return SimpleNamespace(
            session_id="s1", cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=runtime))
        )

    monkeypatch.setattr(BrowserSession, "get_or_create_cdp_session", _cdp)
    return reads


class _Tabs:
    """A browser whose agent is on one tab, labelled by its address; records the titles it lists."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, focused: str | None = "T1") -> None:
        self.target = SimpleNamespace(title="example.com")
        self.session = Browser(cdp_url="ws://host.test/x")
        self.session.agent_focus_target_id = focused
        manager = SimpleNamespace(get_target={"T1": self.target}.get)
        monkeypatch.setattr(self.session, "session_manager", manager)
        self.listed: list[str] = []

        async def _listed(session: BrowserSession) -> list[TabInfo]:
            assert session is self.session
            self.listed.append(self.target.title)
            return []

        monkeypatch.setattr(patch_module, "_original_get_tabs", _listed)

    async def tab_title(self) -> str:
        await patch_module._get_tabs(self.session)
        return self.listed[-1]


async def test_the_agents_tab_is_titled_from_its_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """h_stall: the tab's label was the address, so the agent reported "example.com"."""
    reads = page_answers(monkeypatch, {"result": {"type": "string", "value": " Example Domain "}})

    assert await _Tabs(monkeypatch).tab_title() == "Example Domain"
    # Read on the run's tab without taking focus from it.
    assert reads == [(False, {"expression": "document.title", "returnByValue": True}, "s1")]


@pytest.mark.parametrize("focused", [None, "T2"])
async def test_no_tab_of_the_agents_is_read(
    monkeypatch: pytest.MonkeyPatch, focused: str | None
) -> None:
    reads = page_answers(monkeypatch, {"result": {"type": "string", "value": "Example Domain"}})

    assert await _Tabs(monkeypatch, focused).tab_title() == "example.com"
    assert reads == []


@pytest.mark.parametrize("result", [{"type": "string", "value": "  "}, {"type": "undefined"}])
async def test_a_page_with_no_title_keeps_the_tabs_label(
    monkeypatch: pytest.MonkeyPatch, result: dict[str, str]
) -> None:
    page_answers(monkeypatch, {"result": result})

    assert await _Tabs(monkeypatch).tab_title() == "example.com"


async def test_a_page_that_does_not_answer_keeps_the_tabs_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_answers(monkeypatch, ValueError("detached"))

    async with captured_wide_event() as event:
        title = await _Tabs(monkeypatch).tab_title()

    assert title == "example.com"
    [warning] = event["warnings"]
    assert (warning["msg"], warning["error_type"]) == (
        "[BROWSER] Page title not read",
        "ValueError",
    )


def test_apply_routes_the_tab_list_through_the_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BrowserSession, "get_tabs", None)

    patch_module.apply()

    assert BrowserSession.get_tabs is patch_module._get_tabs
