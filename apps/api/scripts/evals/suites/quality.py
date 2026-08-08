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
(BubbleBoundary, ToolCard), plus gates that exist in ``expected``
(communicate, tool_call_correctness, suggestion, openui), plus a real
suggestion check (3-4 non-empty items, each <=50 chars, from the
``follow_up_actions`` frame).
``overall`` is the mean of the applied scores; the RubricJudge LLM pass runs
at finalize time (1 call per case).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import uuid

import httpx
import yaml

from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.scorers import NOTHING_TO_INSPECT, produced_nothing
from scripts.evals.core.types import Case, CaseRun, ProviderError

DEV_API_BASE = os.environ.get("EVALS_DEV_API_BASE", "http://localhost:9460")
CHAT_STREAM_URL = f"{DEV_API_BASE}/api/v1/chat-stream"
DEV_USERS_URL = f"{DEV_API_BASE}/api/v1/dev/users"
DEV_USER_HEADER = "X-Dev-User"
QUALITY_EMAIL = "quality.eval@gaia.local"
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
        self._email: str | None = None
        self._pending_email: str = QUALITY_EMAIL
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

        # A case owns its user: reset the identity so _ensure_user mints a new
        # one rather than reusing the previous case's account and its state.
        self._email = None
        self._pending_email = self.case_email(case)

        try:
            async with asyncio.timeout(deadline):
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    await self._ensure_user(client, provider)
                    for index, turn_text in enumerate(turns):
                        turn_id = f"quality-{case.id}-{index}-{uuid.uuid4().hex[:6]}"
                        payload: TurnPayload = {
                            "message": turn_text,
                            "conversation_id": conversation_id,
                            "messages": transcript + [{"role": "user", "content": turn_text}],
                            "turn_id": turn_id,
                        }
                        turn = await self._stream_turn(client, payload, provider)
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

    async def _ensure_user(self, client: httpx.AsyncClient, provider: ProviderConfig) -> None:
        if self._email:
            return
        resp = await client.post(DEV_USERS_URL, json={"email": self._pending_email})
        if resp.status_code not in (200, 201):
            raise ProviderError(
                provider.name,
                f"dev users endpoint failed: HTTP {resp.status_code}: {(resp.text or '')[:200]}",
            )
        self._email = self._pending_email

    async def _stream_turn(
        self,
        client: httpx.AsyncClient,
        payload: TurnPayload,
        provider: ProviderConfig,
    ) -> TurnRecord:
        frames: list[Frame] = []
        clean = False
        try:
            async with client.stream(
                "POST",
                CHAT_STREAM_URL,
                json=payload,
                headers={DEV_USER_HEADER: self._email},
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


# A policy rule runs from its number to the next numbered rule (or a blank-line
# break), because several rules carry their real content in indented
# sub-bullets — rule 5's "stats/KPIs, timeline, charts → :::openui" forcing
# clause is a sub-bullet, and a line-only regex would quote the bare header
# "Structured data shown inline:" and grade nothing.
_POLICY_RULE_RE = re.compile(r"^[ \t]*(\d)\.[ \t]+(.*?)(?=^[ \t]*\d\.[ \t]|\n\n)", re.M | re.S)

#: Directions a case can take on the OpenUI surface policy, via
#: ``expected.openui_policy``. Each maps to the policy rule that decides it.
OPENUI_POLICY_DIRECTIONS = ("required", "forbidden", "suppressed")


def _policy_text() -> tuple[str, list[str]]:
    """The SHIPPED OpenUI surface policy and its suppressed-tool list.

    Imported inside the function on purpose. ``__main__`` imports every suite
    module eagerly, and this pulls in app settings (Infisical, validators) —
    at module scope a failure here would take down every suite's run, not just
    this one.
    """
    from app.agents.prompts.openui_prompts import OPENUI_SUPPRESSED_TOOLS, OPENUI_SURFACE_POLICY

    return OPENUI_SURFACE_POLICY, list(OPENUI_SUPPRESSED_TOOLS)


def _policy_rule(policy: str, number: int) -> str:
    """One numbered rule, verbatim, from the shipped policy.

    Raises when the rule is missing rather than falling back to a default: if
    someone renumbers or deletes a rule in the prompt, these evals must break
    loudly at load time. A rubric that silently keeps grading a rule the
    product no longer ships is measuring a spec we do not have.
    """
    for found, text in _POLICY_RULE_RE.findall(policy):
        if int(found) == number:
            return " ".join(text.split())
    raise ValueError(
        f"OpenUI surface policy has no rule {number} — the prompt changed shape. "
        f"Re-derive the openui cases against the new policy instead of pinning a stale one."
    )


def openui_policy_criteria(direction: str) -> list[str]:
    """Judge criteria composed from the real OpenUI prompt, not paraphrased.

    The rubric quotes the shipped ``OPENUI_SURFACE_POLICY`` verbatim, so an
    edit to the prompt changes what these cases grade — automatically, with no
    YAML to update. That is the whole point: a hand-written rubric drifts from
    the prompt and then measures a spec we stopped shipping.
    """
    if direction not in OPENUI_POLICY_DIRECTIONS:
        raise ValueError(
            f"unknown openui_policy {direction!r}; expected one of {OPENUI_POLICY_DIRECTIONS}"
        )
    policy, suppressed = _policy_text()
    quoted = "The agent's own shipped OpenUI surface policy says, verbatim:"
    if direction == "required":
        return [
            f'{quoted} "{_policy_rule(policy, 5)}" Judge ONLY whether the reply obeys that rule '
            f"for this request. For the visual types it names this is stated as a forcing rule, "
            f"not a preference.",
            "Any :::openui fence in the reply is closed by a matching ::: and its body is an "
            "openui-lang expression (root = Component(...)), not prose, JSON, or a code block.",
            "The prose and the component are layers of one reply: the words carry the lead-in and "
            "the takeaway, the component carries the data. Neither duplicates the other.",
        ]
    if direction == "forbidden":
        return [
            f'{quoted} "{_policy_rule(policy, 3)}" Judge whether the reply obeys it.',
            f'{quoted} "Never put :::openui inside greetings, opinions, or plain conversational '
            f'replies." The reply must contain NO :::openui fence at all.',
            "The reply does not reach for a component, a table, or a structured layout where a "
            "plain sentence is the correct answer.",
        ]
    return [
        f'{quoted} "{_policy_rule(policy, 1)}" The tools that already render a native card are: '
        f"{', '.join(suppressed)}.",
        "The reply emits NO :::openui fence duplicating a native tool card, and adds at most a "
        "short conversational line alongside it.",
    ]


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
    except ValueError as e:
        raise ValueError(f"{case_id}: {e}") from e
    judge = expected.setdefault("judge", {})
    judge["criteria"] = list(judge.get("criteria") or []) + derived


@register_suite("quality")
class QualitySuite(Suite):
    name = "quality"
    project = "gaia-quality"
    label = "Quality"

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
                cases.append(
                    Case(
                        id=case_id,
                        ticket=row.pop("ticket", ""),
                        prompt=row.pop("prompt", ""),
                        expected=expected,
                        tags=row.pop("tags", []),
                        setup=row.pop("setup", {}),
                    )
                )
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
    ):
        return self._transport.run(case, cfg, tracker, provider)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        from scripts.evals.core.scorers import (
            BubbleBoundary,
            CommunicateGate,
            DelegationGate,
            MustNotCommunicate,
            NoForbiddenToolCalls,
            OpenUICheck,
            ToolCallCorrectness,
            ToolCard,
        )

        expected = case.expected
        scores: dict[str, float] = {}
        scores["bubble_boundary"] = BubbleBoundary().score(messages=run.messages).value
        scores["tool_card"] = (
            ToolCard()
            .score(tool_calls=run.tool_calls, messages=run.messages, output=run.text)
            .value
        )
        emoji_value, emoji_reason = _emoji_discipline_check(run)
        scores["emoji_discipline"] = emoji_value
        run.raw.append({"type": "emoji_check", "value": emoji_value, "reason": emoji_reason})
        if expected.get("communicate"):
            scores["communicate"] = (
                CommunicateGate()
                .score(output=run.text, messages=run.messages, expected=expected)
                .value
            )
        if expected.get("tool_calls"):
            scores["tool_call_correctness"] = (
                ToolCallCorrectness()
                .score(output=run.text, tool_calls=run.tool_calls, expected=expected)
                .value
            )
        if expected.get("must_not_call_tools"):
            scores["no_forbidden_tools"] = (
                NoForbiddenToolCalls()
                .score(output=run.text, tool_calls=run.tool_calls, expected=expected)
                .value
            )
        if expected.get("must_not_communicate"):
            scores["must_not_communicate"] = (
                MustNotCommunicate()
                .score(output=run.text, messages=run.messages, expected=expected)
                .value
            )
        if expected.get("delegation"):
            scores["delegation"] = (
                DelegationGate()
                .score(output=run.text, tool_calls=run.tool_calls, expected=expected)
                .value
            )
        if expected.get("suggestions"):
            value, reason = _suggestion_check(run)
            scores["suggestion"] = value
            run.raw.append({"type": "suggestion_check", "value": value, "reason": reason})
        if "openui" in expected:
            scores["openui"] = OpenUICheck().score(output=run.text, expected=expected).value
        applied = list(scores.values())
        scores["overall"] = round(sum(applied) / len(applied), 3) if applied else 0.0
        return scores

    def finalize_scorers(self, cfg: EvalConfig) -> list:
        from scripts.evals.core.providers import judge_model
        from scripts.evals.core.scorers import (
            BubbleBoundary,
            CommunicateGate,
            RubricJudge,
            ToolCard,
        )

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
