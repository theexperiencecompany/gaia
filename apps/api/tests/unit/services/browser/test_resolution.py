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
    resolve_handoff_from_message,
)


class _FakeLog:
    """Records log.warning calls so tests can pin the exact message and kwargs."""

    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []

    def warning(self, message: str, /, **kwargs: Any) -> None:
        self.warning_calls.append((message, kwargs))


_PENDING = HandoffRecord(
    status=HandoffStatus.PENDING, user_id="u1", conversation_id="c1", reason="pay"
)


def _handoff_store(monkeypatch, records: dict[str, HandoffRecord]) -> None:
    """Serve handoff records by id, as the store does: an unknown id finds nothing."""

    async def _get(handoff_id: str) -> HandoffRecord | None:
        return records.get(handoff_id)

    monkeypatch.setattr(res_mod, "get_handoff", _get)


def _pending(monkeypatch, action: str, note: str | None = None):
    monkeypatch.setattr(res_mod, "get_conversation_pending_handoff", AsyncMock(return_value="h1"))
    _handoff_store(monkeypatch, {"h1": _PENDING})
    monkeypatch.setattr(
        res_mod,
        "ainvoke_structured_gemini",
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
    monkeypatch.setattr(res_mod, "ainvoke_structured_gemini", interpret)

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
    monkeypatch.setattr(res_mod, "ainvoke_structured_gemini", interpret)

    assert await resolve_handoff_from_message("c1", "u1", "hi") is None
    interpret.assert_not_awaited()


async def test_not_owned_returns_none_without_raising(monkeypatch):
    _pending(monkeypatch, "continue")
    resolve = AsyncMock(side_effect=BrowserHandoffNotOwned())
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)
    fake_log = _FakeLog()
    monkeypatch.setattr(res_mod, "log", fake_log)

    action = await resolve_handoff_from_message("c1", "u1", "yep I paid, go on")
    assert action is None
    resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1", message=None)
    assert fake_log.warning_calls == [
        (
            f"{LogTag.BROWSER} Handoff reply ignored: the handoff belongs to another user",
            {"browser": {"handoff_id": "h1"}, "user_id": "u1"},
        )
    ]


async def test_the_classifier_reads_the_reply_against_the_paused_step(monkeypatch):
    """Without the step's reason and the user's words it cannot tell "done" from "stop"."""
    monkeypatch.setattr(res_mod, "get_conversation_pending_handoff", AsyncMock(return_value="h1"))
    _handoff_store(
        monkeypatch,
        {
            "h1": HandoffRecord(
                status=HandoffStatus.PENDING,
                user_id="u1",
                conversation_id="c1",
                reason="Enter the card's 3-D Secure code",
            )
        },
    )
    classify = AsyncMock(return_value=HandoffReplyDecision(action="unrelated"))
    monkeypatch.setattr(res_mod, "ainvoke_structured_gemini", classify)

    await resolve_handoff_from_message("c1", "u1", "entered the code, carry on")

    schema, prompt = classify.await_args.args
    assert schema is HandoffReplyDecision
    assert "Enter the card's 3-D Secure code" in prompt
    assert "entered the code, carry on" in prompt
    assert classify.await_args.kwargs == {"label": "browser_handoff_conversational_resolve"}


@pytest.mark.regression
async def test_a_reply_the_classifier_could_not_read_leaves_the_handoff_pending(monkeypatch):
    """Regression: a classifier outage fell back to reading the first word, so "ok, one sec" finished the handoff."""
    monkeypatch.setattr(res_mod, "get_conversation_pending_handoff", AsyncMock(return_value="h1"))
    _handoff_store(monkeypatch, {"h1": _PENDING})
    monkeypatch.setattr(
        res_mod, "ainvoke_structured_gemini", AsyncMock(side_effect=RuntimeError("llm down"))
    )
    resolve = AsyncMock()
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    with pytest.raises(RuntimeError):
        await resolve_handoff_from_message("c1", "u1", "ok, one sec")

    resolve.assert_not_awaited()


async def test_a_redirect_resumes_the_run_with_the_whole_instruction(monkeypatch):
    """Regression: a reply that declines the step but says what to do instead stranded the run."""
    note = "never mind the login, just tell me what the github.com homepage headline says"
    _pending(monkeypatch, "redirect", note=note)
    resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
    monkeypatch.setattr(res_mod, "resolve_handoff", resolve)

    action = await resolve_handoff_from_message("c1", "u1", note)

    assert action == "redirect"
    resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1", message=note)


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
