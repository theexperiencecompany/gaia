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
``follow_up_actions`` frame — core's Suggestion is a placeholder, see report).
``overall`` is the mean of the applied scores; the RubricJudge LLM pass runs
at finalize time (1 call per case).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid

import httpx
import yaml

from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import Suite, register_suite
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
            raw.append({"type": "main_response_complete"})
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


class ChatStreamTransport:
    """Multi-turn SSE transport over the real chat-stream endpoint."""

    def __init__(self) -> None:
        self._email: str | None = None
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
        setup_turns = case.setup.get("turns") if isinstance(case.setup, dict) else None
        turns = (
            [str(t) for t in setup_turns]
            if setup_turns
            else [t.strip() for t in case.prompt.split(TURN_SEPARATOR) if t.strip()]
        )
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

    async def _ensure_user(self, client: httpx.AsyncClient, provider: ProviderConfig) -> None:
        if self._email:
            return
        resp = await client.post(DEV_USERS_URL, json={"email": QUALITY_EMAIL})
        if resp.status_code not in (200, 201):
            raise ProviderError(
                provider.name,
                f"dev users endpoint failed: HTTP {resp.status_code}: {(resp.text or '')[:200]}",
            )
        self._email = QUALITY_EMAIL

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

    Core's Suggestion scorer is a placeholder that always passes — the suite
    overrides it with this check. Reads ``raw`` (the follow_up_actions frame
    summary), which the finalize replay does not carry yet (see report).
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
                cases.append(
                    Case(
                        id=case_id,
                        ticket=row.pop("ticket", ""),
                        prompt=row.pop("prompt", ""),
                        expected=expected,
                        tags=row.pop("tags", []),
                        setup=row,
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
            OpenUICheck,
            ToolCallCorrectness,
            ToolCard,
        )

        expected = case.expected
        scores: dict[str, float] = {}
        scores["bubble_boundary"] = BubbleBoundary().score(messages=run.messages).value
        scores["tool_card"] = ToolCard().score(tool_calls=run.tool_calls).value
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
