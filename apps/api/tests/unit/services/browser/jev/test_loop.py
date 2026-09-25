"""A Jev burst: why it stops, what it hands the agent, and that no secret leaves the page."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.constants.browser import (
    JEV_STALE_LIMIT,
    JEV_UNCHANGED_LIMIT,
    JevOperation,
    JevStop,
)
from app.services.browser.jev import loop as loop_mod
from app.services.browser.jev.decision import NONE_VALUE, Decision
from app.services.browser.jev.gateway import JevEvaluation
from app.services.browser.jev.loop import BurstContext, JevRunner
from app.services.browser.jev.page import (
    NavigationFailed,
    PageUnresponsive,
    StalePage,
)
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.ledger import RunLedger
from tests.unit.services.browser.jev.conftest import (
    FakePage,
    decision,
    page_state,
)

pytestmark = pytest.mark.unit

SECRET = "hunter2-secret"


class _Stalls:
    def __init__(self, notes: list[str] | None = None) -> None:
        self._notes = notes or []

    def take(self) -> list[str]:
        taken, self._notes = self._notes, []
        return taken


def _runner(
    monkeypatch: pytest.MonkeyPatch,
    page: FakePage,
    *decisions: Decision,
    value: str = NONE_VALUE,
    stalls: _Stalls | None = None,
    user_waiting: bool = False,
    secrets: RunSecrets | None = None,
) -> JevRunner:
    queue = list(decisions)

    async def _decide(*args: Any, **kwargs: Any) -> Decision:
        return queue.pop(0)

    async def _choose(*args: Any, **kwargs: Any) -> tuple[str, JevEvaluation]:
        return value, JevEvaluation(answers={}, provider="openrouter")

    async def _never() -> bool:
        return False

    async def _waiting() -> bool:
        return user_waiting

    monkeypatch.setattr(loop_mod, "decide", _decide)
    monkeypatch.setattr(loop_mod, "choose_value", _choose)
    return JevRunner(
        page=page,  # type: ignore[arg-type]  # the tab, scripted
        client=MagicMock(model="jev"),
        text_model=MagicMock(),
        run=BurstContext(
            ledger=RunLedger(),
            secrets=secrets or RunSecrets({}, []),
            stalls=stalls or _Stalls(),  # type: ignore[arg-type]  # the one method the loop reads
            should_stop=_never,
            user_waiting=_waiting,
        ),
    )


async def test_a_burst_ends_when_jev_judges_the_goal_done_and_reports_what_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state(), page_state(url="https://site.test/b", text="done page"))
    runner = _runner(
        monkeypatch, page, decision(JevOperation.CLICK, "e1"), decision(JevOperation.DONE)
    )

    result = await runner.burst("go next", None)

    assert result.stop is JevStop.DONE
    assert [step.label for step in result.steps] == ["Next"]
    assert result.progressed is True
    assert result.url == "https://site.test/b"
    assert [v.url for v in runner.visited] == ["https://site.test/a", "https://site.test/b"]


async def test_actions_that_change_nothing_end_the_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage(*[page_state()] * (JEV_UNCHANGED_LIMIT + 1))
    runner = _runner(monkeypatch, page, *[decision(JevOperation.CLICK, "e1")] * JEV_UNCHANGED_LIMIT)

    result = await runner.burst("go next", None)

    assert result.stop is JevStop.NO_PROGRESS
    assert result.progressed is False


async def test_going_back_and_forth_between_two_moves_ends_the_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = page_state(), page_state(url="https://site.test/b")
    page = FakePage(a, b, a, b, a)
    back_and_forth = [
        decision(JevOperation.CLICK, "e1"),
        decision(JevOperation.GO_BACK),
    ] * 2
    runner = _runner(monkeypatch, page, *back_and_forth)

    result = await runner.burst("go next", None)

    assert result.stop is JevStop.CYCLE


async def test_a_page_that_keeps_changing_under_each_decision_ends_the_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state(), act_raises=StalePage("moved"))
    runner = _runner(monkeypatch, page, *[decision(JevOperation.CLICK, "e1")] * JEV_STALE_LIMIT)

    result = await runner.burst("go next", None)

    assert result.stop is JevStop.STALE
    assert result.steps == []


async def test_a_user_message_hands_the_run_back_before_another_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(monkeypatch, FakePage(page_state()), user_waiting=True)

    result = await runner.burst("go next", None)

    assert result.stop is JevStop.USER_MESSAGE


async def test_a_visible_captcha_frame_hands_the_run_back(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = {
        "src": "https://www.google.com/recaptcha/api2/anchor?k=x",
        "same_origin": False,
        "visible": True,
    }
    runner = _runner(monkeypatch, FakePage(page_state(frames=[frame])))

    result = await runner.burst("go next", None)

    assert result.stop is JevStop.CAPTCHA
    assert result.hidden_frames == [frame["src"]]


async def test_a_page_the_browser_stopped_loading_ends_the_burst_with_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = "https://slow.test/ did not respond within 15 s"
    page = FakePage(page_state(), page_state())
    runner = _runner(monkeypatch, page, decision(JevOperation.CLICK, "e1"), stalls=_Stalls([note]))

    result = await runner.burst("go next", None)

    assert (result.stop, result.detail) == (JevStop.LOAD_STALLED, note)


async def test_an_address_that_cannot_be_opened_ends_the_burst_on_the_page_it_was_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())

    async def _fails(url: str) -> None:
        raise NavigationFailed("net::ERR_NAME_NOT_RESOLVED")

    page.navigate = _fails  # type: ignore[method-assign]  # this one tab's navigation fails
    runner = _runner(monkeypatch, page, decision(JevOperation.NAVIGATE, url="https://gone.test/"))

    result = await runner.burst("open gone.test", None)

    assert result.stop is JevStop.NAVIGATION_FAILED
    assert "https://gone.test/" in result.detail
    assert result.url == "https://site.test/a"


async def test_a_field_the_goal_gives_no_value_for_asks_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(monkeypatch, FakePage(page_state()), decision(JevOperation.TYPE_TEXT, "e2"))

    result = await runner.burst("fill the form", None)

    assert result.stop is JevStop.NEEDS_INPUT


async def test_a_tab_that_stops_answering_ends_the_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage(
        page_state(), act_raises=PageUnresponsive("Runtime.evaluate got no answer in 20s")
    )
    runner = _runner(monkeypatch, page, decision(JevOperation.CLICK, "e1"))

    result = await runner.burst("go next", None)

    assert result.stop is JevStop.UNRESPONSIVE


async def test_a_secret_is_typed_into_the_page_and_never_into_what_the_agent_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = RunSecrets({"password": SECRET}, ["site.test"])
    landed = page_state(url=f"https://site.test/b?pw={SECRET}", text=f"welcome {SECRET}")
    page = FakePage(page_state(), landed)
    runner = _runner(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, "e3"),
        decision(JevOperation.DONE),
        value="<secret>password</secret>",
        secrets=secrets,
    )

    result = await runner.burst("log in with <secret>password</secret>", None)

    assert page.typed == [SECRET]
    assert SECRET not in repr(result)
    assert result.steps[0].text == "<secret>password</secret>"


async def test_a_password_field_with_no_stored_secret_is_left_to_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Jev types into a password field only a secret the run was given; the agent
    # types anything else, and the run learns it as a secret there.
    page = FakePage(page_state())
    runner = _runner(monkeypatch, page, decision(JevOperation.TYPE_TEXT, "e3"), value=NONE_VALUE)

    result = await runner.burst('log in with password "gaia-test-123"', None)

    assert result.stop is JevStop.NEEDS_INPUT
    assert page.typed == []


def test_a_burst_that_never_changed_the_page_did_not_progress() -> None:
    step = loop_mod.JevStep(
        operation=JevOperation.CLICK,
        label="Next",
        ident="",
        href="",
        text=None,
        url="https://site.test/a",
        page_changed=False,
        decision_ms=5,
    )
    result = loop_mod.BurstResult(
        goal="g",
        stop=JevStop.NO_PROGRESS,
        detail="",
        steps=[step],
        url="",
        title="",
        text="",
        opened=[],
        hidden_frames=[],
    )

    assert result.progressed is False
    assert replace(result, steps=[replace(step, page_changed=True)]).progressed is True
