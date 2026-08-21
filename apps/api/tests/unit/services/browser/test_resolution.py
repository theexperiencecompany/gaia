"""Tests for conversational handoff resolution — chat replies resume/stop a task."""

from typing import Any
from unittest.mock import AsyncMock

from app.constants.browser import HandoffDecision, HandoffStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import HandoffRecord
from app.services.browser import resolution as res_mod
from app.services.browser.exceptions import BrowserHandoffNotOwned
from app.services.browser.resolution import (
    HandoffReplyDecision,
    _interpret,
    _prompt,
    resolve_handoff_from_message,
)


class _FakeLog:
    """Records `log.warning` calls so tests can pin the exact message and kwargs."""

    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []

    def warning(self, message: str, /, **kwargs: Any) -> None:
        self.warning_calls.append((message, kwargs))


def _pending(monkeypatch, action: str):
    monkeypatch.setattr(res_mod, "get_conversation_pending_handoff", AsyncMock(return_value="h1"))
    monkeypatch.setattr(
        res_mod,
        "get_handoff",
        AsyncMock(
            return_value=HandoffRecord(
                status=HandoffStatus.PENDING, user_id="u1", conversation_id="c1", reason="pay"
            )
        ),
    )
    monkeypatch.setattr(
        res_mod, "_interpret", AsyncMock(return_value=HandoffReplyDecision(action=action))
    )


async def test_continue_reply_resolves(monkeypatch):
    _pending(monkeypatch, "continue")
    resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    action = await resolve_handoff_from_message("c1", "u1", "yep I paid, go on")
    assert action == "continue"
    resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1")


async def test_cancel_reply_resolves(monkeypatch):
    _pending(monkeypatch, "cancel")
    resolve = AsyncMock(return_value=HandoffStatus.CANCELLED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    action = await resolve_handoff_from_message("c1", "u1", "no, stop it")
    assert action == "cancel"
    resolve.assert_awaited_once_with("h1", HandoffDecision.CANCEL, "u1")


async def test_unrelated_reply_does_not_resolve(monkeypatch):
    _pending(monkeypatch, "unrelated")
    resolve = AsyncMock()
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    action = await resolve_handoff_from_message("c1", "u1", "what's the weather?")
    assert action == "unrelated"
    resolve.assert_not_awaited()


async def test_nothing_pending_returns_none(monkeypatch):
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(res_mod, "get_conversation_pending_handoff", lookup)
    assert await resolve_handoff_from_message("c1", "u1", "hi") is None
    lookup.assert_awaited_once_with("c1")


async def test_handoff_record_missing_returns_none(monkeypatch):
    monkeypatch.setattr(res_mod, "get_conversation_pending_handoff", AsyncMock(return_value="h1"))
    monkeypatch.setattr(res_mod, "get_handoff", AsyncMock(return_value=None))
    interpret = AsyncMock()
    monkeypatch.setattr(res_mod, "_interpret", interpret)

    assert await resolve_handoff_from_message("c1", "u1", "hi") is None
    interpret.assert_not_awaited()


async def test_handoff_already_resolved_returns_none(monkeypatch):
    monkeypatch.setattr(res_mod, "get_conversation_pending_handoff", AsyncMock(return_value="h1"))
    monkeypatch.setattr(
        res_mod,
        "get_handoff",
        AsyncMock(
            return_value=HandoffRecord(
                status=HandoffStatus.COMPLETED, user_id="u1", conversation_id="c1", reason="pay"
            )
        ),
    )
    interpret = AsyncMock()
    monkeypatch.setattr(res_mod, "_interpret", interpret)

    assert await resolve_handoff_from_message("c1", "u1", "hi") is None
    interpret.assert_not_awaited()


async def test_interpret_called_with_message_and_handoff_reason(monkeypatch):
    _pending(monkeypatch, "unrelated")
    monkeypatch.setattr(res_mod, "resolve_handoff", AsyncMock())

    await resolve_handoff_from_message("c1", "u1", "yep I paid, go on")
    res_mod._interpret.assert_awaited_once_with("yep I paid, go on", "pay")


async def test_get_handoff_called_with_pending_handoff_id(monkeypatch):
    _pending(monkeypatch, "unrelated")
    monkeypatch.setattr(res_mod, "resolve_handoff", AsyncMock())

    await resolve_handoff_from_message("c1", "u1", "hi")
    res_mod.get_handoff.assert_awaited_once_with("h1")


async def test_not_owned_returns_none_without_raising(monkeypatch):
    _pending(monkeypatch, "continue")
    resolve = AsyncMock(side_effect=BrowserHandoffNotOwned())
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    action = await resolve_handoff_from_message("c1", "u1", "yep I paid, go on")
    assert action is None
    resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1")


async def test_interpret_returns_llm_decision_on_success(monkeypatch):
    ainvoke = AsyncMock(return_value=HandoffReplyDecision(action="cancel"))
    monkeypatch.setattr(res_mod, "ainvoke_structured", ainvoke)

    decision = await _interpret("no, stop it", "pay")

    assert decision == HandoffReplyDecision(action="cancel")
    args, kwargs = ainvoke.call_args
    assert args[0] is HandoffReplyDecision
    assert args[1] == _prompt("no, stop it", "pay")
    assert kwargs["label"] == "browser_handoff_conversational_resolve"


async def test_interpret_falls_back_to_unrelated_on_llm_failure(monkeypatch):
    monkeypatch.setattr(
        res_mod, "ainvoke_structured", AsyncMock(side_effect=RuntimeError("llm down"))
    )
    fake_log = _FakeLog()
    monkeypatch.setattr(res_mod, "log", fake_log)

    decision = await _interpret("no, stop it", "pay")

    assert decision == HandoffReplyDecision(action="unrelated")
    assert fake_log.warning_calls == [
        (
            f"{LogTag.BROWSER} Browser handoff resolve failed, treating as unrelated",
            {"error_type": "RuntimeError"},
        )
    ]


def test_prompt_includes_the_message_and_the_handoff_reason():
    text = _prompt("yep I paid, go on", "confirm the $50 payment")

    assert text == (
        "A browser automation task is paused, waiting for the user to finish a "
        "sensitive step themselves in the live browser: 'confirm the $50 payment'\n\n"
        "The user just sent this message:\n'yep I paid, go on'\n\n"
        "Is the user telling the assistant to CONTINUE (they finished the step / "
        "gave the go-ahead), to CANCEL (stop the task), or is this an UNRELATED "
        "new request? Reply with action='continue', 'cancel', or 'unrelated'."
    )
