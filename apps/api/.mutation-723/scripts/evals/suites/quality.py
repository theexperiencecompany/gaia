"""Quality suite — does GAIA sound human and behave well?

Drives the REAL comms → executor path via ``POST /api/v1/chat-stream`` (SSE)
against the live dev API (``EVALS_DEV_API_BASE``, default
http://localhost:9460), authenticated through the dev bypass (``X-Dev-User``
header, user minted via ``POST /api/v1/dev/users``). This is the same wire the
web frontend consumes — tool cards, follow-up suggestions, streaming text —
so the suite observes the exact user-facing surface.

Wire format (verified Aug 2026, see ``_parse_frames``):
- each frame is an ``id:`` line + ``data: <json>`` line + blank line;
  the stream ends with a bare ``data: [DONE]`` line;
- ``response`` frames carry text CHUNKS — concatenate them;
- ``tool_data`` with ``tool_name == "tool_calls_data"`` carries the real tool
  call (nested ``data.tool_name`` + ``data.inputs``) — deduped by tool_call_id;
- ``follow_up_actions`` frames exist only for turns that did NOT delegate to
  the executor (delegated turns deliver suggestions out-of-band via WebSocket
  + Mongo); the suggestion gate therefore applies to non-delegated cases only;
- no token usage is reported in any frame — tokens are estimated via
  ``core.cost.estimate_tokens`` (noted in ``raw``);
- for delegated turns the SSE text is the comms ack; the executor's final
  answer lands in MongoDB / the WebSocket payload, so ``communicate`` strings
  are matched against what the stream actually carries (documented per case).

Multi-turn cases split ``case.prompt`` on ``"\\n---\\n"`` and send each turn
through the same conversation: turn 1 gets a fresh conversation id (from the
``conversation_initialized`` frame), later turns reuse it and send the
accumulated transcript as ``messages``.

Scoring is deterministic at runtime (no LLM): structural checks always
(BubbleBoundary, ToolCard), the prompt-derived absolutes always
(emoji_discipline plus ``core.prompt_gates`` — dashes, banned chatbot phrases,
internal machinery, routing markers — whose banned lists are read out of
``COMMS_AGENT_PROMPT`` itself rather than copied here), plus gates that exist
in ``expected`` (communicate, tool_call_correctness, suggestion, openui), plus
a real suggestion check (3-4 non-empty items, each <=50 chars, from the
``follow_up_actions`` frame).
``overall`` is the mean of the applied scores; the RubricJudge LLM pass runs
at finalize time (1 call per case).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import os
from pathlib import Path
import re
import time
from typing import Any, ClassVar
import uuid

import httpx
import yaml

from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.gates import ExtraGates, known_gates, score_gates, validate_gates
from scripts.evals.core.prompt_contracts import ClauseResolutionError, contract_criteria
from scripts.evals.core.prompt_gates import PROMPT_GATES
from scripts.evals.core.providers import EvalConfig, ProviderConfig, judge_model
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.scorers import (
    NOTHING_TO_INSPECT,
    BubbleBoundary,
    CommunicateGate,
    OpenUICheck,
    RubricJudge,
    ToolCard,
    produced_nothing,
)
from scripts.evals.core.types import Case, CaseRun, ProviderError

DEV_API_BASE = os.environ.get("EVALS_DEV_API_BASE", "http://localhost:9460")
CHAT_STREAM_URL = f"{DEV_API_BASE}/api/v1/chat-stream"
DEV_USERS_URL = f"{DEV_API_BASE}/api/v1/dev/users"
DEV_USER_HEADER = "X-Dev-User"
TURN_SEPARATOR = "\n---\n"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "quality"

# Type aliases: ANN401 bans `Any` in annotations but not in aliases; these
# name the wire shapes without polluting every signature.
Frame = dict[str, Any]
TurnRecord = dict[str, Any]
TurnPayload = dict[str, Any]


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def turns_for(case: Case) -> list[str]:
    """The user turns this case sends, in order.

    A case declares its turns either as ``setup.turns`` (a YAML list) or by
    separating them in ``prompt`` with a line of ``---``. Named and public so
    the mapping from case data to what actually reaches the wire is testable
    without an API — a silent disagreement here runs a multi-turn case as a
    single turn and grades the agent on a conversation it never had.
    """
    setup_turns = case.setup.get("turns") if isinstance(case.setup, dict) else None
    if setup_turns:
        return [str(t).strip() for t in setup_turns if str(t).strip()]
    return [t.strip() for t in case.prompt.split(TURN_SEPARATOR) if t.strip()]


def _parse_frames(frames: list[Frame]) -> TurnRecord:
    """Reduce the raw SSE frame list into a turn record.

    Returns ``conversation_id``, ``text`` (concatenated response chunks),
    ``tool_calls`` (deduped by tool_call_id), ``follow_up_actions`` (last
    frame wins), ``error`` (first error frame), and ``raw`` — a compact,
    truncated frame summary stored on the CaseRun for journaling.
    """
    conversation_id: str | None = None
    chunks: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    seen_call_ids: set[str] = set()
    follow_up_actions: list[str] | None = None
    error: str | None = None
    raw: list[dict[str, Any]] = []

    for frame in frames:
        if isinstance(frame.get("response"), str):
            chunks.append(frame["response"])
            continue
        if "stream_id" in frame:
            conversation_id = frame.get("conversation_id") or conversation_id
            raw.append(
                {
                    "type": "init",
                    "conversation_id": conversation_id,
                    "user_message_id": frame.get("user_message_id"),
                    "bot_message_id": frame.get("bot_message_id"),
                    "stream_id": frame.get("stream_id"),
                }
            )
            continue
        if isinstance(frame.get("conversation_description"), str):
            raw.append(
                {"type": "conversation_description", "detail": frame["conversation_description"]}
            )
            continue
        if "main_response_complete" in frame:
            usage = frame.get("usage")
            raw.append(
                {
                    "type": "main_response_complete",
                    "usage": usage if isinstance(usage, dict) else None,
                }
            )
            continue
        if "follow_up_actions" in frame:
            actions = frame["follow_up_actions"]
            if isinstance(actions, list):
                follow_up_actions = [a for a in actions if isinstance(a, str)]
            raw.append({"type": "follow_up_actions", "actions": follow_up_actions})
            continue
        if "tool_data" in frame:
            entries = frame["tool_data"]
            if not isinstance(entries, list):
                entries = [entries]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                outer = entry.get("tool_name", "")
                data = entry.get("data")
                if outer == "tool_calls_data" and isinstance(data, dict):
                    name = data.get("tool_name", "")
                    inputs = data.get("inputs", {})
                    call_id = data.get("tool_call_id")
                    if call_id and call_id not in seen_call_ids:
                        seen_call_ids.add(call_id)
                        tool_calls.append(
                            {
                                "name": name,
                                "args": inputs if isinstance(inputs, dict) else {},
                            }
                        )
                    raw.append(
                        {
                            "type": "tool_data",
                            "tool_name": name,
                            "detail": _truncate(json.dumps(inputs), 200),
                        }
                    )
                else:
                    raw.append(
                        {
                            "type": "tool_data",
                            "tool_name": outer,
                            "detail": _truncate(json.dumps(data), 200),
                        }
                    )
            continue
        if "tool_output" in frame:
            payload = frame["tool_output"]
            if isinstance(payload, dict):
                raw.append(
                    {
                        "type": "tool_output",
                        "tool_call_id": payload.get("tool_call_id"),
                        "detail": _truncate(str(payload.get("output", "")), 200),
                    }
                )
            continue
        if isinstance(frame.get("subagent_start"), dict):
            start = frame["subagent_start"]
            raw.append(
                {
                    "type": "subagent_start",
                    "subagent_id": start.get("subagent_id"),
                    "name": start.get("subagent_name"),
                    "agent_type": start.get("agent_type"),
                }
            )
            continue
        if isinstance(frame.get("subagent_end"), dict):
            end = frame["subagent_end"]
            raw.append(
                {
                    "type": "subagent_end",
                    "subagent_id": end.get("subagent_id"),
                    "duration_ms": end.get("duration_ms"),
                }
            )
            continue
        if isinstance(frame.get("error"), str):
            error = error or frame["error"]
            raw.append({"type": "error", "detail": _truncate(frame["error"], 300)})
            continue
        if isinstance(frame.get("progress"), str):
            raw.append({"type": "progress", "detail": _truncate(frame["progress"], 120)})
            continue
        if "reasoning" in frame:
            raw.append({"type": "reasoning", "n_chars": len(json.dumps(frame["reasoning"]))})
            continue
        if isinstance(frame.get("keepalive"), bool):
            raw.append({"type": "keepalive"})
            continue
        if isinstance(frame.get("model_fallback"), dict):
            raw.append(
                {"type": "model_fallback", "detail": json.dumps(frame["model_fallback"])[:120]}
            )
            continue
        if "todo_progress" in frame:
            raw.append({"type": "todo_progress"})
            continue
        if "file_data" in frame:
            raw.append(
                {"type": "file_data", "detail": _truncate(json.dumps(frame["file_data"]), 200)}
            )
            continue
        raw.append({"type": "unknown", "detail": _truncate(json.dumps(frame), 200)})

    return {
        "conversation_id": conversation_id,
        "text": "".join(chunks),
        "tool_calls": tool_calls,
        "follow_up_actions": follow_up_actions,
        "error": error,
        "raw": raw,
    }


def _aggregate_usage(raw: list[dict[str, object]]) -> tuple[int, int]:
    """Sum per-model input/output tokens from main_response_complete frames."""
    total_in = 0
    total_out = 0
    for entry in raw:
        if entry.get("type") != "main_response_complete":
            continue
        usage = entry.get("usage")
        if not isinstance(usage, dict):
            continue
        for model_data in usage.values():
            if not isinstance(model_data, dict):
                continue
            total_in += int(model_data.get("input_tokens", 0) or 0)
            total_out += int(model_data.get("output_tokens", 0) or 0)
    return total_in, total_out


class ChatStreamTransport:
    """Multi-turn SSE transport over the real chat-stream endpoint."""

    def __init__(self) -> None:
        self.user_prefix: str = "quality"
        self._timeout = httpx.Timeout(connect=15.0, read=900.0, write=30.0, pool=15.0)

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg
        deadline = float(os.environ.get("EVALS_CASE_TIMEOUT_S", "300"))
        turns = turns_for(case)
        if not turns:
            raise ProviderError(provider.name, "case prompt has no turns")
        transcript: list[dict[str, str]] = []
        tool_calls: list[dict[str, Any]] = []
        raw: list[dict[str, Any]] = []
        text_parts: list[str] = []
        follow_up_actions: list[str] | None = None
        conversation_id: str | None = None
        error: str | None = None
        start = time.monotonic()

        try:
            async with asyncio.timeout(deadline):
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    email = await self._mint_user(client, provider, self.case_email(case))
                    for index, turn_text in enumerate(turns):
                        # turn_id is a SafePathId (<=64 chars); long case ids
                        # overflowed it and 422'd every turn. Trim the readable
                        # part and let the uuid carry uniqueness.
                        turn_id = f"q-{case.id[:44]}-{index % 100}-{uuid.uuid4().hex[:8]}"
                        payload: TurnPayload = {
                            "message": turn_text,
                            "conversation_id": conversation_id,
                            "messages": transcript + [{"role": "user", "content": turn_text}],
                            "turn_id": turn_id,
                        }
                        turn = await self._stream_turn(client, payload, provider, email)
                        conversation_id = turn["conversation_id"] or conversation_id
                        transcript.append({"role": "user", "content": turn_text})
                        if turn["text"]:
                            transcript.append({"role": "assistant", "content": turn["text"]})
                        text_parts.append(turn["text"])
                        tool_calls.extend(turn["tool_calls"])
                        raw.extend(turn["raw"])
                        if turn["error"]:
                            error = error or turn["error"]
                        if turn["follow_up_actions"] is not None:
                            follow_up_actions = turn["follow_up_actions"]
        except TimeoutError:
            error = f"case timed out after {deadline:.0f}s"
        except httpx.HTTPError as e:
            raise ProviderError(provider.name, f"chat-stream transport failed: {e}") from e

        text = " ".join(part for part in text_parts if part).strip()
        if error:
            return CaseRun(
                case_id=case.id,
                provider=provider.name,
                model=provider.model,
                messages=transcript,
                tool_calls=tool_calls,
                text=text,
                raw=raw,
                duration_s=time.monotonic() - start,
                error=f"stream error frame: {error[:200]}",
            )

        tokens_in, tokens_out = _aggregate_usage(raw)
        if tokens_in == 0 and tokens_out == 0:
            tokens_in = estimate_tokens(
                " ".join(m["content"] for m in transcript if m["role"] == "user")
            )
            tokens_out = estimate_tokens(
                " ".join(m["content"] for m in transcript if m["role"] == "assistant")
            )
        tracker.add_manual(provider.name, tokens_in, tokens_out)
        raw.append(
            {
                "type": "usage",
                "estimated": True,
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "note": "chat-stream frames carry no token usage; estimated via core.cost.estimate_tokens",
            }
        )
        if follow_up_actions is not None:
            raw.append({"type": "follow_up_actions_final", "actions": follow_up_actions})
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=transcript,
            tool_calls=tool_calls,
            text=text,
            raw=raw,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_s=time.monotonic() - start,
        )

    def case_email(self, case: Case) -> str:
        """A fresh identity per case.

        One shared account let every case inherit the previous one's todos,
        reminders and — worst — the agent's MEMORY of them, accumulating across
        every case AND every historical run. That made results order-dependent
        (``--only`` disagreed with a full run), let a later case answer from
        memory instead of doing the work, and made concurrency impossible
        because two cases would write over each other. capability, gaia_bench
        and hil already mint per case; this brings the live-chat suites in line.
        """
        return f"{self.user_prefix}-{case.id[:40]}-{uuid.uuid4().hex[:8]}@gaia.local"

    async def _mint_user(
        self, client: httpx.AsyncClient, provider: ProviderConfig, email: str
    ) -> str:
        """Create this case's user and RETURN it.

        Deliberately returns rather than storing on self: one transport instance
        serves every case in a run, so instance state is shared state. Holding
        the identity here let a concurrent case overwrite it mid-run, and the
        first case's next turn then posted to a conversation another user owned
        ("404: Conversation not found or does not belong to the user").
        """
        resp = await client.post(DEV_USERS_URL, json={"email": email})
        if resp.status_code not in (200, 201):
            raise ProviderError(
                provider.name,
                f"dev users endpoint failed: HTTP {resp.status_code}: {(resp.text or '')[:200]}",
            )
        return email

    async def _stream_turn(
        self,
        client: httpx.AsyncClient,
        payload: TurnPayload,
        provider: ProviderConfig,
        email: str,
    ) -> TurnRecord:
        frames: list[Frame] = []
        clean = False
        try:
            async with client.stream(
                "POST",
                CHAT_STREAM_URL,
                json=payload,
                headers={DEV_USER_HEADER: email},
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise ProviderError(
                        provider.name,
                        f"chat-stream HTTP {resp.status_code}: {(body or '')[:200]}",
                    )
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        clean = True
                        break
                    try:
                        frames.append(json.loads(data))
                    except ValueError:
                        frames.append({"raw": _truncate(data, 200)})
        except (httpx.ReadError, httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            if not frames:
                raise ProviderError(provider.name, f"chat-stream connection failed: {e}") from e

        turn = _parse_frames(frames)
        turn["raw"].append({"type": "stream_ended", "clean": clean})
        if not clean:
            turn["raw"].append({"type": "stream_note", "detail": "stream closed before [DONE]"})
        if not frames:
            raise ProviderError(provider.name, "chat-stream returned no frames")
        if not clean and not turn["text"] and not turn["tool_calls"]:
            raise ProviderError(provider.name, "stream ended before any response or tool frames")
        return turn


def _suggestion_check(run: CaseRun) -> tuple[float, str]:
    """Real suggestion gate: last follow_up_actions frame, 3-4 short items.

    Reads ``raw`` (the follow_up_actions frame summary), which the finalize
    replay does not carry yet (see report).
    """
    actions: list[str] | None = None
    for frame in reversed(run.raw):
        if frame.get("type") == "follow_up_actions":
            actions = frame.get("actions")
            break
    if actions is None:
        return 0.0, "no follow_up_actions frame in stream"
    if not actions:
        return 0.0, "follow_up_actions frame was empty"
    if not 3 <= len(actions) <= 4:
        return 0.0, f"{len(actions)} suggestions (expected 3-4)"
    bad = [a for a in actions if not a.strip() or len(a) > 50]
    if bad:
        return 0.0, f"bad suggestion item(s): {bad[:3]}"
    return 1.0, f"{len(actions)} suggestions, all non-empty and <=50 chars"


# Pictographic ranges only. Deliberately excludes U+2100-27BF (™, ←, ✓, ▶) and
# the U+FE0F variation selector: those appear in ordinary punctuation and would
# make the check fire on text carrying no emoji at all.
_EMOJI_PATTERN = re.compile(
    "[\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f900-\U0001f9ff"  # supplemental symbols & pictographs
    "\U0001fa70-\U0001faff"  # extended-A (🩵, 🫶)
    "☀-⛿]"  # miscellaneous symbols (☀, ⚡)
)


def _emoji_discipline_check(run: CaseRun) -> tuple[float, str]:
    """The assistant must not use an emoji before the user has used one.

    A verbatim prompt rule ("Emojis EXTREMELY RARE, and NEVER use one before
    the user has used one first"), and therefore deterministically gradeable —
    no rubric judge required. Walks the transcript in order so a case where the
    user does open with an emoji correctly permits the reply to answer in kind.

    Caught live: a plain-English "add a todo to water the plants" came back as
    "aight, add kar raha hoon Inbox me 🌱" — the case passed every structural
    gate it had, because none of them could see this.
    """
    if produced_nothing(run.messages, run.tool_calls, run.text):
        return 0.0, NOTHING_TO_INSPECT
    user_has_emojied = False
    for message in run.messages:
        content = str(message.get("content") or "")
        if message.get("role") == "user":
            user_has_emojied = user_has_emojied or bool(_EMOJI_PATTERN.search(content))
            continue
        if message.get("role") != "assistant" or user_has_emojied:
            continue
        found = _EMOJI_PATTERN.findall(content)
        if found:
            return 0.0, f"assistant used {''.join(found[:4])} before the user used any emoji"
    return 1.0, "no emoji before the user's first"


class OpenUIPolicyError(ValueError):
    """A case's ``openui_policy`` cannot be resolved against the shipped prompt.

    Its own error type so the case-id prefix is only ever attached to failures
    that really are the case's fault. Catching bare ``ValueError`` here meant a
    pydantic ``ValidationError`` — which IS a ValueError — got relabelled as a
    broken case, so a missing env var read as "quality-openui-…: 1 validation
    error for DevelopmentSettings".
    """


#: Directions a case can take on the OpenUI surface policy, via
#: ``expected.openui_policy``, each mapped to the shipped prompt clauses that
#: decide it.
#:
#: These used to be hand-written prose beside a second, suite-local extractor
#: that sliced ``OPENUI_SURFACE_POLICY`` by rule number. Two mechanisms for one
#: job is one too many, and the prose half drifted the moment the prompt moved:
#: the "forbidden" rubric carried its own frozen copy of "Never put :::openui
#: inside greetings…", so rewording that rule in the prompt would leave the
#: judge grading the old sentence forever. Every criterion is now a registered
#: clause, which means the CI gate in ``tests/unit/evals/test_prompt_contracts``
#: fails the moment one of them stops matching the prompt we ship.
OPENUI_POLICY_CONTRACTS: dict[str, tuple[str, ...]] = {
    "required": (
        "openui.rule_structured_data",
        "openui.prose_and_component_are_layers",
        "openui.how_to_emit",
    ),
    "forbidden": (
        "openui.rule_plain_text",
        "openui.never_openui_in_conversation",
    ),
    "suppressed": ("openui.rule_native_card",),
}

OPENUI_POLICY_DIRECTIONS = tuple(OPENUI_POLICY_CONTRACTS)


def openui_policy_criteria(direction: str) -> list[str]:
    """Judge criteria composed from the real OpenUI prompt, not paraphrased.

    The rubric quotes the shipped ``OPENUI_SURFACE_POLICY`` verbatim, so an edit
    to the prompt changes what these cases grade — automatically, with no YAML
    to update. ``rule_native_card`` carries the suppressed-tool list itself
    (``OPENUI_SURFACE_POLICY`` interpolates ``OPENUI_SUPPRESSED_TOOLS`` into the
    rule), so the criterion names today's tools without this suite holding a
    second copy of the list.
    """
    refs = OPENUI_POLICY_CONTRACTS.get(direction)
    if refs is None:
        raise OpenUIPolicyError(
            f"unknown openui_policy {direction!r}; expected one of {OPENUI_POLICY_DIRECTIONS}"
        )
    return contract_criteria(list(refs))


def _apply_openui_policy_criteria(case_id: str, expected: TurnPayload) -> None:
    """Append policy-derived criteria to a case that opts in.

    Cases declare ``openui_policy: required|forbidden|suppressed`` and get the
    shipped policy's own words appended to their rubric. Case-specific criteria
    written in YAML are kept — they say what THIS request is, the imported ones
    say what the product promises.
    """
    direction = expected.get("openui_policy")
    if not direction:
        return
    try:
        derived = openui_policy_criteria(str(direction))
    except ClauseResolutionError as e:
        raise ClauseResolutionError(f"{case_id}: {e}") from e
    except OpenUIPolicyError as e:
        # Deliberately narrow. This used to catch ValueError, and pydantic's
        # ValidationError is a ValueError — so a misconfigured environment
        # (E2B_DOMAIN injected empty) surfaced as "quality-openui-...: 1
        # validation error for DevelopmentSettings", blaming a case for the
        # machine's config. A config failure must propagate as itself.
        raise OpenUIPolicyError(f"{case_id}: {e}") from e
    judge = expected.setdefault("judge", {})
    judge["criteria"] = list(judge.get("criteria") or []) + derived


def _reject_unfalsifiable_openui_gate(case: Case) -> None:
    """``openui`` as a gate on a case declaring ``openui: false`` cannot go red.

    ``OpenUICheck`` returns 1.0 without reading anything in that branch, so the
    gate carries the authority of a hard check while being incapable of failing
    — worse than no gate at all. Neither the forgery sweep nor the inert check
    can see it: the gate does produce a value, it just always produces 1.0.
    """
    expected = case.expected
    if "openui" in case.gates and not expected.get("openui"):
        raise ValueError(
            f"quality case {case.id}: gates 'openui' while declaring openui="
            f"{expected.get('openui')!r}. OpenUICheck scores 1.0 unconditionally there, so the "
            f"gate can never fail. Record it as a metric (drop it from score.gates), or set "
            f"openui: true if a fence really is required."
        )


def _tool_card_gate(case: Case, run: CaseRun) -> float:
    del case
    return ToolCard().score(tool_calls=run.tool_calls, messages=run.messages, output=run.text).value


def _openui_gate(case: Case, run: CaseRun) -> float:
    return OpenUICheck().score(output=run.text, expected=case.expected).value


def _recorded(
    name: str, check: Callable[[CaseRun], tuple[float, str]]
) -> Callable[[Case, CaseRun], float]:
    """Adapt a ``(run) -> (value, reason)`` check to the gate signature.

    The reason is journaled on the run so the report can explain a red gate;
    that side effect is why these are not plain lambdas.
    """

    def gate(case: Case, run: CaseRun) -> float:
        del case
        value, reason = check(run)
        run.raw.append({"type": f"{name}_check", "value": value, "reason": reason})
        return value

    return gate


#: Gates this suite adds to the shared set in ``core/gates.py``. Everything else
#: a case may declare comes from there, so a name means the same thing in every
#: suite instead of being re-implemented here.
QUALITY_GATES: ExtraGates = {
    "tool_card": _tool_card_gate,
    "openui": _openui_gate,
    "emoji_discipline": _recorded("emoji", _emoji_discipline_check),
    "suggestion": _recorded("suggestion", _suggestion_check),
    **{name: _recorded(name, check) for name, check in PROMPT_GATES.items()},
}

#: Recorded on every case, gated or not. The prompt-derived ones are here
#: because the prompt states each as an absolute with no exceptions — "NEVER use
#: em dashes", the banned-phrase list, ONE ENTITY, the routing markers. A case
#: does not opt in to a rule that applies to every reply, and their inputs are
#: read out of the live prompt, so extending it extends the gate with no eval
#: change.
ALWAYS_SCORED: tuple[str, ...] = (
    "bubble_boundary",
    "tool_card",
    "emoji_discipline",
    *PROMPT_GATES,
)

#: A gate also recorded as a metric when the ``expected`` field that gives it
#: meaning is present, even on a case that does not gate it.
METRIC_WHEN_PRESENT: dict[str, str] = {
    "communicate": "communicate",
    "tool_call_correctness": "tool_calls",
    "no_forbidden_tools": "must_not_call_tools",
    "must_not_communicate": "must_not_communicate",
    "delegation": "delegation",
    "suggestion": "suggestions",
    "openui": "openui",
}

#: ``openui: false`` used to be recorded too, on the reasoning that "no fence
#: belongs here" is a real claim. It is — but ``OpenUICheck`` does not check it:
#: that branch returns 1.0 without reading the output. Recording it fed a
#: constant 1.0 into ``overall``, lifting the mean of every case that declared
#: it and making a suite look better the more of these it accumulated. Only the
#: ``openui: true`` branch reads anything, so only that branch is measured.
#: (``_reject_unfalsifiable_openui_gate`` separately stops it being a gate.)


@register_suite("quality")
class QualitySuite(Suite):
    name = "quality"
    project = "gaia-quality"
    label = "Quality"

    EXTRA_GATES: ClassVar[ExtraGates] = QUALITY_GATES

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._cases: list[Case] | None = None
        self._transport = ChatStreamTransport()

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        if self._cases is not None:
            return self._cases
        cases: list[Case] = []
        seen_ids: set[str] = set()
        for path in sorted(DATA_DIR.glob("*.yaml")):
            rows = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError(f"{path}: expected a YAML list of cases")
            for row in rows:
                row = dict(row)
                case_id = row.pop("id")
                if case_id in seen_ids:
                    raise ValueError(f"duplicate case id {case_id!r} in {path}")
                seen_ids.add(case_id)
                expected = row.pop("expected")
                _apply_openui_policy_criteria(case_id, expected)
                case = Case(
                    id=case_id,
                    ticket=row.pop("ticket", ""),
                    prompt=row.pop("prompt", ""),
                    expected=expected,
                    tags=row.pop("tags", []),
                    setup=row.pop("setup", {}),
                )
                validate_gates(self.name, case.id, case.gates, self.EXTRA_GATES)
                _reject_unfalsifiable_openui_gate(case)
                cases.append(case)
        if not cases:
            raise ValueError(f"no quality cases found in {DATA_DIR}")
        self._cases = cases
        return cases

    def transport(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> Awaitable[CaseRun]:
        return self._transport.run(case, cfg, tracker, provider)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        """Suite metrics, then the declared gates through the shared dispatcher.

        The two are separate on purpose. A METRIC is recorded because the case
        carries the field that gives it meaning, and it shows up in the report;
        a GATE decides pass/fail. Routing the gates through ``score_gates``
        guarantees every declared one has an entry — a missing key is read back
        as 0.0 by the runner, which is how capability shipped a case that could
        never pass.
        """
        available = known_gates(self.EXTRA_GATES)
        scores = {name: available[name](case, run) for name in ALWAYS_SCORED}
        for gate, field in METRIC_WHEN_PRESENT.items():
            if case.expected.get(field):
                scores[gate] = available[gate](case, run)
        gate_scores = score_gates(case, run, self.EXTRA_GATES)
        gate_scores.pop("overall", None)
        scores.update(gate_scores)
        scores["overall"] = round(sum(scores.values()) / len(scores), 3) if scores else 0.0
        return scores

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        return [
            CommunicateGate(),
            BubbleBoundary(),
            ToolCard(),
            RubricJudge(
                base_url=os.environ.get("DEV_LLM_BASE_URL", ""),
                api_key=os.environ.get("DEV_LLM_API_KEY", ""),
                model=judge_model(cfg),
            ),
        ]
