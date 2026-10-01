"""Jev's tab and decisions as a burst sees them, scripted: shared by the loop and run tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.constants.browser import JevOperation
from app.services.browser.jev.decision import Decision
from app.services.browser.jev.gateway import JevEvaluation
from app.services.browser.jev.page import PageAction, PageState, StalePage

BUTTON = PageAction(id="e1", node=1, kind="click", label="Next", role="button", value="")
FIELD = PageAction(id="e2", node=2, kind="fill", label="Name", role="textbox", value="")
PASSWORD = PageAction(id="e3", node=3, kind="secret", label="Password", role="password", value="")
BACK = PageAction(id="go_back", kind="back", label="Go back to Site", entry=1)
ENTER = PageAction(id="enter", kind="enter", node=2, label="Press Enter in Name")


def page_state(url: str = "https://site.test/a", text: str = "page", **extra: Any) -> PageState:
    return PageState(
        url=url,
        title="Site",
        text=text,
        text_cut=extra.get("text_cut", False),
        actions=[BUTTON, FIELD, PASSWORD],
        page_key=url,
        guards={},
        frames=extra.get("frames", []),
        fingerprint=f"{url}|{text}",
    )


class FakePage:
    """The tab as Jev drives it: each input moves to the next scripted state.

    act_raises is one error for every input, or one outcome per input (None executes it).
    new_tab is a page the first input opens in a tab of its own; unsettled makes every
    read after an input fail as a page that never settles; holds is what a field holds
    after text is put into it (by default, the text); read_fails is the read after which
    every read raises an error, and navigate_fails the error every navigation raises.
    """

    def __init__(
        self,
        *states: PageState,
        act_raises: Exception | list[Exception | None] | None = None,
        new_tab: PageState | None = None,
        unsettled: bool = False,
        holds: str | None = None,
        read_fails: tuple[int, Exception] | None = None,
        navigate_fails: Exception | None = None,
    ) -> None:
        self._states: Iterator[PageState] = iter(states)
        self.current = next(self._states)
        self.typed: list[str | None] = []
        self.acted: list[str] = []
        self._act_raises = act_raises
        self.navigated: list[str] = []
        self._new_tab = new_tab
        self.followed = 0
        self._unsettled = unsettled
        self._holds = holds
        self._inputs = 0
        self._reads = 0
        self._read_fails = read_fails
        self._navigate_fails = navigate_fails

    def _moved(self) -> None:
        self._inputs += 1
        self.current = next(self._states, self.current)

    async def observe(self) -> PageState:
        self._reads += 1
        if self._unsettled and self._inputs:
            raise StalePage("The page did not settle.")
        if self._read_fails is not None and self._reads > self._read_fails[0]:
            raise self._read_fails[1]
        return self.current

    async def fresh(self, page: PageState, action: PageAction | None = None) -> bool:
        return page.fingerprint == self.current.fingerprint

    async def act(self, action: PageAction, page: PageState, text: str | None = None) -> str | None:
        raises = self._act_raises
        outcome = raises.pop(0) if isinstance(raises, list) else raises
        if outcome is not None:
            raise outcome
        if not await self.fresh(page):
            raise StalePage("The page changed since this decision.")
        self.acted.append(action["id"])
        self.typed.append(text)
        self._moved()
        if text is None:
            return None
        return text if self._holds is None else self._holds

    async def navigate(self, url: str) -> None:
        if self._navigate_fails is not None:
            raise self._navigate_fails
        self.navigated.append(url)
        self._moved()

    async def follow_new_tab(self) -> bool:
        self.followed += 1
        if self._new_tab is None:
            return False
        self.current, self._new_tab = self._new_tab, None
        return True

    async def body_text(self, limit: int) -> str:
        return self.current.text[:limit]

    async def screenshot(self) -> str:
        return "c2hvdA=="


def decision(
    operation: JevOperation, target: PageAction | None = None, url: str | None = None
) -> Decision:
    return Decision(
        operation=operation,
        target=target,
        url=url,
        latency_ms=5,
        evaluation=JevEvaluation(answers={}, provider="openrouter"),
    )
