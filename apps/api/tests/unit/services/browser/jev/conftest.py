"""Jev's tab and decisions as a burst sees them, scripted: shared by the loop and run tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.constants.browser import JevOperation
from app.services.browser.jev.decision import Decision
from app.services.browser.jev.gateway import JevEvaluation
from app.services.browser.jev.page import PageAction, PageState, StalePage

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
    """The tab as Jev drives it: each input moves to the next scripted state.

    act_raises is one error for every input, or one outcome per input (None executes it).
    new_tab is a page the first input opens in a tab of its own; unsettled makes every
    read after an input fail as a page that never settles.
    """

    def __init__(
        self,
        *states: PageState,
        act_raises: Exception | list[Exception | None] | None = None,
        new_tab: PageState | None = None,
        unsettled: bool = False,
    ) -> None:
        self._states: Iterator[PageState] = iter(states)
        self.current = next(self._states)
        self.typed: list[str | None] = []
        self.acted: list[str] = []
        self._act_raises = act_raises
        self.navigated: list[str] = []
        self.went_back = 0
        self.entered = 0
        self._new_tab = new_tab
        self._tabs = {"tab-1"}
        self.followed: list[set[str]] = []
        self._unsettled = unsettled
        self._inputs = 0

    def _moved(self) -> None:
        self._inputs += 1
        if self._new_tab is not None:
            self._tabs.add("tab-2")
        self.current = next(self._states, self.current)

    async def observe(self) -> PageState:
        if self._unsettled and self._inputs:
            raise StalePage("The page did not settle.")
        return self.current

    async def fresh(self, page: PageState, action: PageAction | None = None) -> bool:
        return page.fingerprint == self.current.fingerprint

    async def act(self, action: PageAction, page: PageState, text: str | None = None) -> None:
        raises = self._act_raises
        outcome = raises.pop(0) if isinstance(raises, list) else raises
        if outcome is not None:
            raise outcome
        if not await self.fresh(page):
            raise StalePage("The page changed since this decision.")
        self.acted.append(action["id"])
        self.typed.append(text)
        self._moved()

    async def navigate(self, url: str) -> None:
        self.navigated.append(url)
        self._moved()

    async def go_back(self) -> None:
        self.went_back += 1
        self._moved()

    async def press_enter(self) -> None:
        self.entered += 1
        self._moved()

    async def tab_ids(self) -> set[str]:
        return set(self._tabs)

    async def follow_new_tab(self, tabs: set[str]) -> bool:
        self.followed.append(tabs)
        if self._new_tab is None or not self._tabs - tabs:
            return False
        self.current, self._new_tab = self._new_tab, None
        return True

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
