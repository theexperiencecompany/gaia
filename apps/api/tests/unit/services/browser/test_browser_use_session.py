"""The run's Browser-Use session: no page script of GAIA's on any tab, a capped load wait, and tabs titled from their documents."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from browser_use.browser.session import BrowserSession
from browser_use.browser.views import TabInfo
import pytest

from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH
from app.services.browser import browser_use_session as session_mod
from app.services.browser.browser_use_session import GaiaBrowserSession
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


def _session() -> GaiaBrowserSession:
    return GaiaBrowserSession(cdp_url="ws://host.test/x")


def test_the_session_attaches_to_the_host_at_the_screencast_size() -> None:
    session = _session()

    profile = session.browser_profile
    assert session.cdp_url == "ws://host.test/x"
    assert (profile.viewport.width, profile.viewport.height) == (
        BROWSER_VIEWPORT_WIDTH,
        BROWSER_VIEWPORT_HEIGHT,
    )
    # Shots and click points share one coordinate space.
    assert (profile.device_scale_factor, profile.no_viewport) == (1, False)


@pytest.mark.regression
async def test_no_tab_gets_a_fingerprint_script_of_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: our JS stealth on Chrome was detectable and lost to Fortress's engine (12/24 vs 20/24 loads)."""
    add_script = AsyncMock(return_value={"identifier": "1"})
    served = SimpleNamespace(
        target_id="t1",
        session_id="sess-t1",
        cdp_client=SimpleNamespace(
            send=SimpleNamespace(Page=SimpleNamespace(addScriptToEvaluateOnNewDocument=add_script))
        ),
    )
    monkeypatch.setattr(BrowserSession, "get_or_create_cdp_session", AsyncMock(return_value=served))
    session = _session()

    assert await session.get_or_create_cdp_session(target_id="t1") is served
    await session.get_or_create_cdp_session(target_id="t2", focus=False)

    add_script.assert_not_awaited()


@pytest.mark.parametrize(
    ("given", "waited"), [(None, session_mod._MAX_READINESS_WAIT_SECONDS), (0.25, 0.25)]
)
async def test_a_load_is_waited_on_at_most_the_cap_unless_the_caller_says(
    monkeypatch: pytest.MonkeyPatch, given: float | None, waited: float
) -> None:
    original = AsyncMock()
    monkeypatch.setattr(BrowserSession, "_navigate_and_wait", original)

    await _session()._navigate_and_wait("https://x.test", "t9", timeout=given)

    assert original.await_args.args == ("https://x.test", "t9")
    assert original.await_args.kwargs == {"timeout": waited, "wait_until": "load"}


def _titled_page(monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any] | Exception) -> list[Any]:
    reads: list[Any] = []

    async def _cdp(self: BrowserSession, target_id: str | None = None, focus: bool = True) -> Any:
        async def _evaluate(params: dict[str, Any], session_id: str) -> dict[str, Any]:
            reads.append((focus, params, session_id))
            if isinstance(answer, Exception):
                raise answer
            return answer

        return SimpleNamespace(
            session_id="s1",
            cdp_client=SimpleNamespace(
                send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=_evaluate))
            ),
        )

    monkeypatch.setattr(GaiaBrowserSession, "get_or_create_cdp_session", _cdp)
    return reads


async def _tab_title(monkeypatch: pytest.MonkeyPatch, focused: str | None = "T1") -> str:
    target = SimpleNamespace(title="example.com")
    session = _session()
    session.agent_focus_target_id = focused
    monkeypatch.setattr(session, "session_manager", SimpleNamespace(get_target={"T1": target}.get))
    listed: list[str] = []

    async def _listed(self: BrowserSession) -> list[TabInfo]:
        listed.append(target.title)
        return []

    monkeypatch.setattr(BrowserSession, "get_tabs", _listed)
    await session.get_tabs()
    return listed[-1]


async def test_the_agents_tab_is_titled_from_its_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """h_stall: the tab's label was the address, so the agent reported "example.com"."""
    reads = _titled_page(monkeypatch, {"result": {"type": "string", "value": " Example Domain "}})

    assert await _tab_title(monkeypatch) == "Example Domain"
    # Read without taking focus from the run's tab.
    assert reads == [(False, {"expression": "document.title", "returnByValue": True}, "s1")]
    assert await _tab_title(monkeypatch, focused="T2") == "example.com"


@pytest.mark.parametrize(
    "answer", [{"result": {"type": "string", "value": "  "}}, {"result": {"type": "undefined"}}]
)
async def test_a_page_with_no_title_keeps_the_tabs_label(
    monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any]
) -> None:
    _titled_page(monkeypatch, answer)

    assert await _tab_title(monkeypatch) == "example.com"


async def test_a_page_that_does_not_answer_keeps_the_tabs_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _titled_page(monkeypatch, ValueError("detached"))

    async with captured_wide_event() as event:
        assert await _tab_title(monkeypatch) == "example.com"

    [warning] = event["warnings"]
    assert (warning["msg"], warning["error_type"]) == (
        "[BROWSER] Page title not read",
        "ValueError",
    )
