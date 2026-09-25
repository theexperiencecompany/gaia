"""Jev's tab and decisions as a burst sees them, scripted: shared by the loop and run tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.constants.browser import JevOperation
from app.services.browser.jev.decision import Decision
from app.services.browser.jev.gateway import JevEvaluation
from app.services.browser.jev.page import PageAction, PageState

BUTTON = PageAction(id="e1", node=1, kind="click", label="Next", role="button")
FIELD = PageAction(id="e2", node=2, kind="fill", label="Name", role="textbox", value="")
PASSWORD = PageAction(id="e3", node=3, kind="secret", label="Password", role="password", value="")


def page_state(url: str = "https://site.test/a", text: str = "page", **extra: Any) -> PageState:
    return PageState(
        url=url,
        title="Site",
        text=text,
        actions=[BUTTON, FIELD, PASSWORD],
        marker=None,
        page_key=None,
        guards={},
        frames=extra.get("frames", []),
        fingerprint=f"{url}|{text}",
    )


class FakePage:
    """The tab as Jev drives it: each input moves to the next scripted state."""

    def __init__(self, *states: PageState, act_raises: Exception | None = None) -> None:
        self._states: Iterator[PageState] = iter(states)
        self.current = next(self._states)
        self.typed: list[str | None] = []
        self._act_raises = act_raises
        self.navigated: list[str] = []

    async def observe(self) -> PageState:
        return self.current

    async def fresh(self, page: PageState, action: PageAction | None = None) -> bool:
        return page is self.current

    async def act(self, action: PageAction, page: PageState, text: str | None = None) -> None:
        if self._act_raises is not None:
            raise self._act_raises
        self.typed.append(text)
        self.current = next(self._states, self.current)

    async def navigate(self, url: str) -> None:
        self.navigated.append(url)
        self.current = next(self._states, self.current)

    async def go_back(self) -> None:
        self.current = next(self._states, self.current)

    async def press_enter(self) -> None:
        self.current = next(self._states, self.current)

    async def tab_ids(self) -> set[str]:
        return set()

    async def follow_new_tab(self, tabs: set[str]) -> bool:
        return False

    async def body_text(self, limit: int) -> str:
        return self.current.text[:limit]

    async def screenshot(self) -> str:
        return "c2hvdA=="


def decision(
    operation: JevOperation, action_id: str | None = None, url: str | None = None
) -> Decision:
    return Decision(
        operation=operation,
        action_id=action_id,
        url=url,
        confidence=0.9,
        latency_ms=5,
        evaluation=JevEvaluation(answers={}, provider="openrouter"),
    )
