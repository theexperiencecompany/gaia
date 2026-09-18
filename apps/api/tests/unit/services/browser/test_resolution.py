"""Tests for conversational handoff resolution — chat replies resume/stop a task."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.constants.browser import HandoffDecision, HandoffStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import HandoffRecord
from app.services.browser import resolution as res_mod
from app.services.browser.exceptions import BrowserHandoffNotOwned
from app.services.browser.resolution import (
    HandoffReplyDecision,
    _interpret,
    _prompt,
    keyword_reply_decision,
    resolve_handoff_from_message,
)


class _FakeLog:
    """Records log.warning calls so tests can pin the exact message and kwargs."""

    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []

    def warning(self, message: str, /, **kwargs: Any) -> None:
        self.warning_calls.append((message, kwargs))


def _pending(monkeypatch, action: str, note: str | None = None):
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
        res_mod,
        "_interpret",
        AsyncMock(return_value=HandoffReplyDecision(action=action, note=note)),
    )


async def test_continue_reply_resolves(monkeypatch):
    _pending(monkeypatch, "continue")
    resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    action = await resolve_handoff_from_message("c1", "u1", "yep I paid, go on")
    assert action == "continue"
    resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1", message=None)


async def test_cancel_reply_resolves(monkeypatch):
    _pending(monkeypatch, "cancel")
    resolve = AsyncMock(return_value=HandoffStatus.CANCELLED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    action = await resolve_handoff_from_message("c1", "u1", "no, stop it")
    assert action == "cancel"
    resolve.assert_awaited_once_with("h1", HandoffDecision.CANCEL, "u1", message=None)


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
    resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1", message=None)


async def test_interpret_returns_llm_decision_on_success(monkeypatch):
    ainvoke = AsyncMock(return_value=HandoffReplyDecision(action="cancel"))
    monkeypatch.setattr(res_mod, "ainvoke_structured_gemini", ainvoke)

    decision = await _interpret("no, stop it", "pay")

    assert decision == HandoffReplyDecision(action="cancel")
    args, kwargs = ainvoke.call_args
    assert args[0] is HandoffReplyDecision
    assert args[1] == _prompt("no, stop it", "pay")
    assert kwargs["label"] == "browser_handoff_conversational_resolve"


def _classifier_down(monkeypatch) -> _FakeLog:
    monkeypatch.setattr(
        res_mod, "ainvoke_structured_gemini", AsyncMock(side_effect=RuntimeError("llm down"))
    )
    fake_log = _FakeLog()
    monkeypatch.setattr(res_mod, "log", fake_log)
    return fake_log


async def test_a_failed_classifier_degrades_to_the_keyword_rule_and_still_says_so(monkeypatch):
    """Regression: any classifier failure became unrelated, so the user's 'done' started a new turn."""
    fake_log = _classifier_down(monkeypatch)

    decision = await _interpret("no, stop it", "pay")

    assert decision == HandoffReplyDecision(action="cancel")
    assert fake_log.warning_calls == [
        (
            f"{LogTag.BROWSER} Browser handoff resolve failed, using the keyword rule",
            {"error_type": "RuntimeError"},
        )
    ]


async def test_a_go_ahead_still_resolves_when_the_classifier_is_down(monkeypatch):
    """The real _interpret runs here: the degrade must survive the whole resolve path."""
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
    _classifier_down(monkeypatch)
    resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    action = await resolve_handoff_from_message(
        "c1", "u1", "done, skip the login and just tell me the page title"
    )

    assert action == "continue"
    resolve.assert_awaited_once_with(
        "h1",
        HandoffDecision.CONTINUE,
        "u1",
        message="skip the login and just tell me the page title",
    )


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (
            "done, skip the login and just tell me the page title",
            ("continue", "skip the login and just tell me the page title"),
        ),
        ("Done.", ("continue", None)),
        ("okay", ("continue", None)),
        ("yes go on", ("continue", "go on")),
        ("stop", ("cancel", None)),
        ("Cancel!", ("cancel", None)),
        ("no", ("cancel", None)),
        ("what's the weather", ("unrelated", None)),
        ("", ("unrelated", None)),
    ],
)
def test_the_keyword_rule_reads_the_first_word_and_keeps_the_rest(reply, expected):
    action, note = expected

    assert keyword_reply_decision(reply) == HandoffReplyDecision(action=action, note=note)


def test_prompt_includes_the_message_and_the_handoff_reason():
    text = _prompt("yep I paid, go on", "confirm the $50 payment")

    assert text == (
        "A browser automation task is paused, waiting for the user to finish a "
        "sensitive step themselves in the live browser: 'confirm the $50 payment'\n\n"
        "The user just sent this message:\n'yep I paid, go on'\n\n"
        "Is the user telling the assistant to CONTINUE (they finished the step / "
        "gave the go-ahead), to CANCEL (stop the task), or is this an UNRELATED "
        "new request? Reply with action='continue', 'cancel', or 'unrelated', and "
        "put anything the user asks for beyond the go-ahead itself in 'note', "
        "verbatim — null when the reply is only an acknowledgement."
    )


async def test_note_typed_with_the_reply_reaches_the_run(monkeypatch):
    """The words after the go-ahead are instructions for the paused run, not chatter."""
    _pending(monkeypatch, "continue", note="skip the login and just tell me the title")
    resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    await resolve_handoff_from_message(
        "c1", "u1", "done, skip the login and just tell me the title"
    )

    resolve.assert_awaited_once_with(
        "h1",
        HandoffDecision.CONTINUE,
        "u1",
        message="skip the login and just tell me the title",
    )


async def test_bare_acknowledgement_carries_no_note(monkeypatch):
    _pending(monkeypatch, "continue", note=None)
    resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    await resolve_handoff_from_message("c1", "u1", "done")

    resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1", message=None)


async def test_blank_note_is_not_forwarded_as_an_empty_message(monkeypatch):
    _pending(monkeypatch, "continue", note="   ")
    resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    await resolve_handoff_from_message("c1", "u1", "done")

    resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1", message=None)
