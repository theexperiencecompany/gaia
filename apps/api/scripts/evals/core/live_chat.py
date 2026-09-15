"""One way to send a chat turn against a running API and read the reply back.

Three harnesses (``chat_quality``, ``adversarial_users``,
``first_question_personas``) each grew their own ``_send_turn`` against the same
``/api/v1/chat-stream`` endpoint, and two more scripts imported one of those
copies from a *sibling script* to avoid a fourth. The copies had drifted in ways
that changed what a run measured, not just how it was written: one dropped the
retracted handoff preamble and two did not, one polled for the delegated answer
and one silently graded the ack instead.

So the differences are kept as arguments rather than as forks. Every knob below
is one behaviour a copy actually had; nothing here is speculative. A script that
wants the old shape passes the flags for it, and the shape is then visible in one
line at the call site instead of buried eighty lines down a private function.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import time
from uuid import uuid4

import httpx
from pydantic import BaseModel

#: A stream that carried no prose at all. Scripts test replies against this
#: sentinel, so it has to be one string, not one per harness.
NO_TEXT_REPLY = "[no text in stream]"

#: Defaults for polling the saved conversation after a delegated turn.
DELIVERY_WAIT_SECONDS = 75.0
DELIVERY_POLL_SECONDS = 3.0

#: The tool name that means comms handed this turn to the executor: the real
#: answer will arrive on the saved conversation, not on this stream.
DELEGATION_TOOL = "call_executor"


class Turn(BaseModel):
    """One exchange, plus the evidence GAIA did a thing rather than talked about it."""

    message: str
    reply: str = ""
    #: ``tool_name`` of every ``tool_data`` entry. A connect card arrives as
    #: ``integration_connection_required``; a created reminder as the reminder
    #: tool's own name.
    tools: list[str] = []
    #: Every distinct top-level key seen on an SSE frame. Captured generically so
    #: a frame kind added upstream still shows up here instead of being dropped.
    frame_kinds: list[str] = []
    #: True when the answer arrived on the saved conversation, not the stream.
    delegated: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.reply.strip() or self.reply.strip() == NO_TEXT_REPLY


def frame_tool_names(frame: dict, *, include_nested: bool = True) -> list[str]:
    """Every tool name in one SSE frame's ``tool_data``, which is an entry or a list.

    ``include_nested`` also unwraps the tool a ``tool_calls_data`` announcement
    carries (its ``data`` is one step dict). ``first_question_personas`` read only
    the outer name, so that stays available rather than being quietly widened:
    unwrapping adds names to the tool list the judge is shown, which can flip a
    "did it actually do the thing" criterion.
    """
    payload = frame.get("tool_data")
    entries = payload if isinstance(payload, list) else [payload]
    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("tool_name"), str):
            continue
        names.append(entry["tool_name"])
        if not include_nested:
            continue
        inner = entry.get("data")
        if entry["tool_name"] == "tool_calls_data" and isinstance(inner, dict):
            inner_name = inner.get("tool_name") or inner.get("name")
            if isinstance(inner_name, str):
                names.append(inner_name)
    return names


def assemble(
    lines: list[str],
    *,
    include_nested_tool_names: bool = True,
    drop_discarded_boundary: bool = True,
    collect_frame_kinds: bool = False,
) -> tuple[str, list[str], list[str]]:
    """Fold raw SSE lines into ``(reply, tools, frame_kinds)``.

    Split out from the request so the assembly rules — which are the part that
    decides what a run measures — are testable without an API. Non-``data:``
    lines, undecodable payloads and non-dict frames are skipped rather than
    raising: a stream that ends mid-frame is a slow lane, not a failed eval.
    """
    chunks: list[str] = []
    tools: list[str] = []
    kinds: list[str] = []
    for line in lines:
        if not line.startswith("data: "):
            continue
        try:
            frame = json.loads(line[len("data: ") :])
        except json.JSONDecodeError:
            continue
        if not isinstance(frame, dict):
            continue
        if collect_frame_kinds:
            kinds.extend(key for key in frame if frame[key] is not None)
        # A discarded boundary retracts the text streamed since the last one (the
        # handoff preamble); the web and the bots drop it on this frame, so the
        # harness must too or it reads as duplicated text.
        boundary = frame.get("message_boundary")
        if drop_discarded_boundary and isinstance(boundary, dict) and boundary.get("discarded"):
            chunks.clear()
        if isinstance(frame.get("response"), str):
            chunks.append(frame["response"])
        tools.extend(frame_tool_names(frame, include_nested=include_nested_tool_names))
    reply = "".join(chunks).strip() or NO_TEXT_REPLY
    return reply, tools, sorted(set(kinds))


def bot_messages_after(messages: list[dict], user_text: str) -> list[dict]:
    """Bot messages saved after the LAST user message equal to ``user_text``.

    Last, not first: a scenario may send the same words twice, and the turn being
    graded is the most recent one.
    """
    idx = None
    for i, message in enumerate(messages):
        if (
            message.get("type") == "user"
            and (message.get("response") or "").strip() == user_text.strip()
        ):
            idx = i
    if idx is None:
        return []
    return [message for message in messages[idx + 1 :] if message.get("type") == "bot"]


async def await_delivery(
    client: httpx.AsyncClient,
    api_url: str,
    conversation_id: str,
    user_text: str,
    *,
    wait_seconds: float = DELIVERY_WAIT_SECONDS,
    poll_seconds: float = DELIVERY_POLL_SECONDS,
) -> tuple[str, list[str]]:
    """Poll the saved conversation until the delegated answer lands (or the budget ends)."""
    deadline = time.monotonic() + wait_seconds
    last_seen = ""
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_seconds)
        try:
            resp = await client.get(
                f"{api_url}/api/v1/conversations/{conversation_id}", timeout=30.0
            )
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        payload = resp.json()
        convo = payload.get("conversation", payload) if isinstance(payload, dict) else {}
        messages = convo.get("messages") or []
        bots = bot_messages_after(messages, user_text)
        texts = [(message.get("response") or "").strip() for message in bots]
        delivered = [text for text in texts[1:] if text] if len(texts) > 1 else []
        tool_names = [
            entry.get("tool_name")
            for message in bots
            for entry in (message.get("tool_data") or [])
            if isinstance(entry, dict)
        ]
        real_tools = [name for name in tool_names if name and name != "tool_calls_data"]
        if delivered and "\n".join(delivered) == last_seen:
            return last_seen, real_tools
        if delivered:
            last_seen = "\n".join(delivered)
        elif real_tools:
            return "", real_tools
    return last_seen, []


@dataclass(frozen=True)
class TurnOptions:
    """How one harness wants a turn read back.

    Every field is one behaviour a copy of ``_send_turn`` actually had; nothing
    here is speculative. Frozen because a harness's turn shape is fixed for the
    whole run — a mutable options object shared across turns is a way for turn 7
    to be read differently from turn 1 and for nobody to notice.

    The defaults are ``chat_quality``'s behaviour, which is the shape three of
    the five scripts want; the other two say how they differ at the call site,
    in one visible line, instead of eighty lines down a private function.
    """

    #: Budget for the whole streamed turn. Harness-specific: the adversarial
    #: personas wait on the executor and needed 300s where 60s timed out 33/35.
    timeout: float = 180.0
    #: Also unwrap the tool a ``tool_calls_data`` announcement carries.
    include_nested_tool_names: bool = True
    #: Drop text retracted by a discarded ``message_boundary`` (the handoff preamble).
    drop_discarded_boundary: bool = True
    #: Record every distinct top-level SSE frame key on the ``Turn``.
    collect_frame_kinds: bool = False
    #: Poll the saved conversation when the turn was delegated to the executor.
    poll_for_delivery: bool = True
    #: Separator between the streamed ack and the later delivered answer.
    delivered_prefix: str = "\n\n[delivered later] "
    #: Drop the "no text in stream" sentinel when a delivered answer replaces it.
    drop_sentinel_before_delivery: bool = False
    delivery_wait_seconds: float = DELIVERY_WAIT_SECONDS
    delivery_poll_seconds: float = DELIVERY_POLL_SECONDS


async def send_turn(
    client: httpx.AsyncClient,
    api_url: str,
    message: str,
    conversation_id: str,
    history: list[dict[str, str]],
    options: TurnOptions = TurnOptions(),
) -> Turn:
    """One comms turn against the running API, joined from its SSE frames.

    ``history`` is the prior turns of THIS conversation in the shape the endpoint
    expects; the new user message is appended to it. Sharing the conversation id
    across turns is what makes turn 2 a follow-up rather than a second cold open.

    A non-200 comes back as a ``Turn`` whose reply carries the status and body
    rather than as an exception: one persona hitting a 402 should show up as one
    bad row in the report, not as a dead run.
    """
    messages = [*history, {"role": "user", "content": message}]
    body = {
        "message": message,
        "messages": messages,
        "conversation_id": conversation_id,
        "turn_id": str(uuid4()),
    }
    async with client.stream(
        "POST", f"{api_url}/api/v1/chat-stream", json=body, timeout=options.timeout
    ) as response:
        if response.status_code != 200:
            await response.aread()
            return Turn(
                message=message,
                reply=f"[HTTP {response.status_code}] {response.text[:300]}",
            )
        lines = [line async for line in response.aiter_lines()]

    reply, tools, kinds = assemble(
        lines,
        include_nested_tool_names=options.include_nested_tool_names,
        drop_discarded_boundary=options.drop_discarded_boundary,
        collect_frame_kinds=options.collect_frame_kinds,
    )
    delegated = DELEGATION_TOOL in tools
    if delegated and options.poll_for_delivery:
        delivered, more_tools = await await_delivery(
            client,
            api_url,
            conversation_id,
            message,
            wait_seconds=options.delivery_wait_seconds,
            poll_seconds=options.delivery_poll_seconds,
        )
        if delivered:
            head = "" if options.drop_sentinel_before_delivery and reply == NO_TEXT_REPLY else reply
            reply = (head + options.delivered_prefix + delivered).strip()
            tools.extend(more_tools)
        else:
            reply = reply + "\n\n[nothing delivered within budget]"
    return Turn(
        message=message,
        reply=reply,
        tools=tools,
        frame_kinds=kinds,
        delegated=delegated,
    )
