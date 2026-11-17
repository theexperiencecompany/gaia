"""Where a message GAIA sends on its own goes: one chat app's DM, or the GAIA app alone.

A run that reports to the user resolves this once, before its reply is written, and keeps it on
the entry that woke it, so the prompt it is written under and the place it is sent never disagree.
"""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from app.constants.chat import ConversationSource

#: Why a platform was chosen: the user wrote there within the active window, or it led their order.
ChatChannelBasis = Literal["recent_activity", "priority"]

#: Why nothing goes to a chat app: the user is active in the GAIA app, or no chat app is usable.
InAppReason = Literal["active_in_app", "no_chat_app"]

_STORED = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True, config=_STORED)
class ChatChannel:
    """The platform a proactive message goes to, the account it reaches, and the rule that chose it."""

    source: ConversationSource
    platform_user_id: Annotated[str, Field(min_length=1)]
    basis: ChatChannelBasis
    #: The chat app the user is active on but that cannot be messaged (muted or no account id).
    unreachable_active: ConversationSource | None = None
    kind: Literal["chat_app"] = "chat_app"


@dataclass(frozen=True, slots=True, config=_STORED)
class InApp:
    """A proactive message that stays in the GAIA app, and why."""

    reason: InAppReason
    #: The chat app the user is active on but that cannot be messaged (muted or no account id).
    unreachable_active: ConversationSource | None = None
    kind: Literal["in_app"] = "in_app"


ProactiveTarget = Annotated[ChatChannel | InApp, Field(discriminator="kind")]
