"""The real Telegram client side: log in as the founder, talk only to the dev bot, record everything it shows."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import time

from edge_invariants import is_approval_prompt
from edge_transcript import BotMessage, Mark, ReactionState, SentMessage, TextState, Transcript
from telethon import TelegramClient, events
from telethon.tl.custom.message import Message
from telethon.tl.types import UpdateMessageReactions, User

BOT_USERNAME = "gaia_dev_e2e_8842_bot"
SESSION = (
    Path.home() / ".local/share/gaia-tg/gaia"
)  # Telethon appends .session; shared with tgsend.py
POLL_S = 2.0


def keychain(name: str) -> str:
    """Read agent/<name> from the login Keychain, as tgsend.py does."""
    out = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", f"agent/{name}", "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise SystemExit(
            f"missing Keychain item agent/{name} (see ~/.local/share/gaia-tg/README.md)"
        )
    return out.stdout.strip()


def _emojis(m: Message) -> tuple[str, ...]:
    if not m.reactions or not m.reactions.results:
        return ()
    return tuple(
        str(getattr(r.reaction, "emoticon", None) or getattr(r.reaction, "document_id", "?"))
        for r in m.reactions.results
    )


class Recorder:
    """Records every bot bubble and reaction after a starting message id, from live events and a poll."""

    def __init__(
        self, client: TelegramClient, peer: User, transcript: Transcript, after_id: int
    ) -> None:
        """Start a recording for one scenario; nothing at or before after_id is recorded."""
        self.client = client
        self.peer = peer
        self.t = transcript
        self.after_id = after_id
        self.t0 = time.monotonic()
        self.last_change = self.t0
        self._bot: dict[int, BotMessage] = {}
        self._sent: dict[int, SentMessage] = {}

    def now(self) -> float:
        """Seconds since the scenario started."""
        return round(time.monotonic() - self.t0, 3)

    def observe(self, m: Message) -> None:
        """Fold one observed message state into the transcript."""
        if m.id <= self.after_id:
            return
        if m.out:
            sent = self._sent.get(m.id)
            emojis = _emojis(m)
            previous = sent.reactions[-1].emojis if sent and sent.reactions else ()
            if sent is not None and emojis != previous:
                sent.reactions.append(ReactionState(self.now(), emojis))
                self.last_change = time.monotonic()
            return
        text = m.message or ""
        bubble = self._bot.get(m.id)
        if bubble is None:
            reply_to = m.reply_to.reply_to_msg_id if m.reply_to else None
            bubble = BotMessage(m.id, self.now(), reply_to)
            self._bot[m.id] = bubble
            self.t.bot.append(bubble)
            self.t.bot.sort(key=lambda b: b.id)
        if not bubble.states or bubble.states[-1].text != text:
            bubble.states.append(TextState(self.now(), text))
            bubble.entity_kinds = sorted({type(e).__name__ for e in m.entities or []})
            self.last_change = time.monotonic()

    def deleted(self, ids: list[int]) -> None:
        """Mark bot bubbles the user saw disappear."""
        for i in ids:
            if i in self._bot and self._bot[i].deleted_at is None:
                self._bot[i].deleted_at = self.now()
                self.last_change = time.monotonic()

    def sent(self, m: Message) -> None:
        """Record a message I just sent."""
        s = SentMessage(m.id, m.message or "", self.now())
        self._sent[m.id] = s
        self.t.sent.append(s)
        self.last_change = time.monotonic()

    def mark(self, kind: str, detail: str = "") -> None:
        """Put a runner action on the timeline."""
        self.t.marks.append(Mark(self.now(), kind, detail))

    async def poll_forever(self) -> None:
        """Re-read the chat every POLL_S, catching reaction changes and edits no event reported."""
        while True:
            for m in await self.client.get_messages(self.peer, min_id=self.after_id, limit=100):
                self.observe(m)
            await asyncio.sleep(POLL_S)

    async def refresh_ids(self, ids: list[int]) -> None:
        """Re-read specific messages (a reaction on one of mine can be older than the poll window)."""
        for m in await self.client.get_messages(self.peer, ids=ids):
            if m is not None:
                self.observe(m)

    def quiet_for(self) -> float:
        """Seconds since anything visible last changed."""
        return time.monotonic() - self.last_change

    def has_prompt_after(self, at: float) -> bool:
        """Whether an approval prompt appeared after a moment."""
        return any(is_approval_prompt(b) for b in self.t.bot_after(at))


async def connect() -> tuple[TelegramClient, User]:
    """Connect with the saved tgsend session and resolve the dev bot, refusing any other peer."""
    client = TelegramClient(
        str(SESSION), int(keychain("TELEGRAM_API_ID")), keychain("TELEGRAM_API_HASH")
    )
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit(
            "not logged in: run `tgsend.py login` first (~/.local/share/gaia-tg/README.md)"
        )
    peer = await client.get_entity(BOT_USERNAME)
    if not isinstance(peer, User) or not peer.bot or (peer.username or "").lower() != BOT_USERNAME:
        raise SystemExit(f"refusing: resolved peer is not @{BOT_USERNAME}")
    return client, peer


def attach(client: TelegramClient, peer: User, recorder: Recorder) -> list[object]:
    """Wire live Telethon events into a recorder; return the handlers so they can be removed."""

    async def on_message(event: events.NewMessage.Event | events.MessageEdited.Event) -> None:
        recorder.observe(event.message)

    async def on_deleted(event: events.MessageDeleted.Event) -> None:
        recorder.deleted(list(event.deleted_ids))

    async def on_reactions(update: UpdateMessageReactions) -> None:
        await recorder.refresh_ids([update.msg_id])

    handlers: list[tuple[object, object]] = [
        (on_message, events.NewMessage(chats=peer)),
        (on_message, events.MessageEdited(chats=peer)),
        (on_deleted, events.MessageDeleted()),
        (on_reactions, events.Raw(UpdateMessageReactions)),
    ]
    for callback, event in handlers:
        client.add_event_handler(callback, event)
    return [callback for callback, _ in handlers]
