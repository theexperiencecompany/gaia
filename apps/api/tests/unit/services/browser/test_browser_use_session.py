"""The run's Browser-Use session: stealth on every tab for its user, a capped load wait, and tabs titled from their documents."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from browser_use.browser.session import BrowserSession
from browser_use.browser.views import TabInfo
import pytest

from app.browser_host.stealth import build_stealth_script
from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH
from app.services.browser import browser_use_session as session_mod
from app.services.browser.browser_use_session import GaiaBrowserSession, seed_for_user
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


def _session(user_id: str | None = "user-1") -> GaiaBrowserSession:
    return GaiaBrowserSession(cdp_url="ws://host.test/x", user_id=user_id)


def _tabs(
    monkeypatch: pytest.MonkeyPatch, add_script: AsyncMock
) -> tuple[dict[str, Any], list[bool]]:
    """Serve each target its own CDP session from Browser-Use's pool; return them by target, and each focus asked."""
    served: dict[str, Any] = {}
    focuses: list[bool] = []

    async def _pooled(
        self: BrowserSession, target_id: str | None = None, focus: bool = True
    ) -> Any:
        focuses.append(focus)
        page = SimpleNamespace(addScriptToEvaluateOnNewDocument=add_script)
        return served.setdefault(
            target_id or "t1",
            SimpleNamespace(
                target_id=target_id or "t1",
                session_id=f"sess-{target_id}",
                cdp_client=SimpleNamespace(send=SimpleNamespace(Page=page)),
            ),
        )

    monkeypatch.setattr(BrowserSession, "get_or_create_cdp_session", _pooled)
    return served, focuses


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


async def test_every_tab_gets_the_users_stealth_script_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the script registered on the first tab only, so a window.open tab was fingerprint-naked."""
    add_script = AsyncMock(return_value={"identifier": "1"})
    _, focuses = _tabs(monkeypatch, add_script)
    session = _session("user-1")

    await session.get_or_create_cdp_session(target_id="t1")
    await session.get_or_create_cdp_session(target_id="t1")
    await session.get_or_create_cdp_session(target_id="t2", focus=False)

    source = build_stealth_script(seed_for_user("user-1"))
    assert [c.kwargs for c in add_script.await_args_list] == [
        {"params": {"source": source, "runImmediately": True}, "session_id": "sess-t1"},
        {"params": {"source": source, "runImmediately": True}, "session_id": "sess-t2"},
    ]
    assert focuses == [True, True, False]


async def test_a_script_that_did_not_register_is_tried_again_and_the_page_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_script = AsyncMock(side_effect=[RuntimeError("cdp down"), {"identifier": "1"}])
    served, _ = _tabs(monkeypatch, add_script)
    session = _session()

    async with captured_wide_event() as event:
        assert await session.get_or_create_cdp_session(target_id="t1") is served["t1"]
    await session.get_or_create_cdp_session(target_id="t1")

    assert add_script.await_count == 2
    [warning] = event["warnings"]
    assert (warning["msg"], warning["error_type"], warning["target_id"]) == (
        "[BROWSER] Stealth script not registered",
        "RuntimeError",
        "t1",
    )


def test_each_user_is_one_stable_device_and_no_user_still_one() -> None:
    users = ("user-1", "user-2", "alice@example.com")
    seeds = [seed_for_user(user) for user in users]

    assert all(0 <= seed < 2**32 for seed in seeds)
    assert len(set(seeds)) == len(users)
    assert seeds == [seed_for_user(user) for user in users]
    assert seed_for_user(None) == seed_for_user("") == session_mod._DEFAULT_SEED


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
