"""The buttons a bot card carries, minted as the card leaves for the bot.

Each actionable object on a card (the approval, each email draft) gains a
bot_actions map of verb to action id, so the bot renders a button per object
without knowing what the tap does. Only objects a
tap can still act on get one.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.services.bot.card_action_store import (
    ApprovalCardAction,
    CardActionKind,
    SendEmailCardAction,
    mint_card_action,
)


@dataclass(frozen=True)
class ButtonScope:
    """Whose buttons these are, where the card is shown, and the stored card they sit on."""

    user_id: str
    conversation_id: str | None
    card_id: str


#: The key each actionable object carries its button ids under.
BOT_ACTIONS_KEY = "bot_actions"
#: The key a settled object keeps its spent button id under (card_settle).
BOT_TAPPED_KEY = "bot_tapped"
#: The approval status a tap can still decide.
_PENDING = "pending"
#: How much of a long card title the model's record of a tap quotes.
_SUBJECT_MAX_CHARS = 80


class _ApprovalCard(BaseModel):
    approval_id: str | None = None
    status: str | None = None
    summary: str | None = None


class _EmailDraft(BaseModel):
    #: The compose card stores recipients as a list or a comma-separated string.
    to: list[str] | str | None = None
    subject: str | None = None
    body: str | None = None
    cc: list[str] | str | None = None
    bcc: list[str] | str | None = None
    thread_id: str | None = None
    draft_id: str | None = None


async def approval_buttons(data: Mapping[str, object], scope: ButtonScope) -> dict[str, object]:
    """Add Approve and Deny to a still-pending approval card."""
    approval = _ApprovalCard.model_validate(data)
    approval_id = approval.approval_id
    if approval.status != _PENDING or approval_id is None:
        return dict(data)
    subject = f'the approval "{_clip(approval.summary)}"'
    actions: dict[str, str] = {}
    decisions: tuple[tuple[str, Literal[CardActionKind.APPROVE, CardActionKind.DENY]], ...] = (
        ("approve", CardActionKind.APPROVE),
        ("deny", CardActionKind.DENY),
    )
    for verb, kind in decisions:
        action_id = await mint_card_action(
            ApprovalCardAction(
                kind=kind,
                approval_id=approval_id,
                user_id=scope.user_id,
                conversation_id=scope.conversation_id,
                card_id=scope.card_id,
                subject=subject,
            )
        )
        if action_id is not None:
            actions[verb] = action_id
    return _with_actions(data, actions)


async def email_draft_buttons(drafts: list[object], scope: ButtonScope) -> list[object]:
    """Add Send to each email draft on a compose card."""
    return [await _draft_with_button(draft, scope) for draft in drafts]


async def _draft_with_button(draft: object, scope: ButtonScope) -> object:
    if not isinstance(draft, dict):
        return draft
    fields = _EmailDraft.model_validate(draft)
    to = _addresses(fields.to)
    if not to:
        return draft
    subject_line = fields.subject or ""
    action_id = await mint_card_action(
        SendEmailCardAction(
            kind=CardActionKind.SEND_EMAIL,
            to=to,
            subject_line=subject_line,
            body=fields.body or "",
            cc=_addresses(fields.cc) or None,
            bcc=_addresses(fields.bcc) or None,
            thread_id=fields.thread_id or None,
            draft_id=fields.draft_id or None,
            user_id=scope.user_id,
            conversation_id=scope.conversation_id,
            card_id=scope.card_id,
            subject=f'the email draft to {", ".join(to)} "{_clip(subject_line)}"',
        )
    )
    return _with_actions(draft, {"send": action_id} if action_id else {})


def _with_actions(obj: Mapping[str, object], actions: Mapping[str, str]) -> dict[str, object]:
    return {**obj, BOT_ACTIONS_KEY: dict(actions)} if actions else dict(obj)


def _addresses(value: list[str] | str | None) -> list[str]:
    parts = value.split(",") if isinstance(value, str) else (value or [])
    return [part.strip() for part in parts if part.strip()]


def _clip(value: str | None) -> str:
    text = str(value or "").strip()
    return text if len(text) <= _SUBJECT_MAX_CHARS else f"{text[: _SUBJECT_MAX_CHARS - 3]}..."


def carries_buttons(value: object) -> bool:
    """Whether any object in a card's data carries a button."""
    if isinstance(value, dict):
        return bool(value.get(BOT_ACTIONS_KEY)) or any(carries_buttons(v) for v in value.values())
    if isinstance(value, list):
        return any(carries_buttons(item) for item in value)
    return False
