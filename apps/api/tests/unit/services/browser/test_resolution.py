"""Tests for conversational handoff resolution — chat replies resume/stop a task."""

from unittest.mock import AsyncMock

from app.constants.browser import HandoffDecision, HandoffStatus
from app.schemas.browser import HandoffRecord
from app.services.browser import resolution as res_mod
from app.services.browser.resolution import HandoffReplyDecision, resolve_handoff_from_message


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
    monkeypatch.setattr(res_mod, "get_conversation_pending_handoff", AsyncMock(return_value=None))
    assert await resolve_handoff_from_message("c1", "u1", "hi") is None
