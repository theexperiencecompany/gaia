"""Ownership suite: does GAIA treat a request as a responsibility it closes?

Each case is one rung of the ambiguity ladder or one ownership failure mode:

* **l0_act / l1_default**: clear (or safely defaultable) and harmless. Act, ask
  nothing, confirm briefly.
* **l2_ask_one**: readings with different outcomes. Ask ONE question, create
  nothing on a guess.
* **l3_approval**: irreversible or destructive. Prepare and confirm; the seeded
  data must still be there afterwards.
* **l4_goal**: the underlying goal is unclear. Ask what outcome they want, take
  no action, push no direction.
* **followup**: work that needs future attention. A durable follow-up (tracked
  todo with a wake source, or a reminder) must exist, and nothing unfinished is
  claimed done.
* **over_proactive**: nothing was asked. No follow-ups invented, short reply.

Transport is the live chat-stream wire (the quality transport's frame parsing),
plus what that wire cannot show: the executor's delivered answer, read back
from the saved conversation, and the durable follow-ups, read back from
GET /todos (tracked label) and GET /reminders as a diff against what existed
before the first turn.

Not exercised: a follow-up actually firing later (the harness has no clock
control), and approval cards (the comprehension family here runs with HIL off,
which is the shipped default; the hil suite owns the armed gate).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import os
from pathlib import Path
import re
import time
from typing import Any, ClassVar
import uuid

import httpx

from scripts.evals.core.cases import load_case_files
from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.dev_users import dev_client, provision
from scripts.evals.core.gates import ExtraGates, score_gates
from scripts.evals.core.live_chat import DELEGATION_TOOL, bot_messages_after
from scripts.evals.core.providers import EvalConfig, ProviderConfig, judge_model
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.scorers import (
    CommunicateGate,
    DelegationGate,
    EndStateEquality,
    MustNotCommunicate,
    RubricJudge,
    produced_nothing,
)
from scripts.evals.core.types import Case, CaseRun, ProviderError
from scripts.evals.suites.quality import (
    DEV_API_BASE,
    REACTION_KIND,
    ChatStreamTransport,
    TurnPayload,
    turns_for,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ownership"
API = f"{DEV_API_BASE}/api/v1"
TRACKED_LABEL = "gaia-tracked"
ACTIVE_REMINDER_STATUSES = frozenset({"scheduled", "executing"})
DELIVERED_KIND = "delivered"
# Executor work (research, planning) outlives the comms default of 75s.
DELIVERY_WAIT_S = float(os.environ.get("EVALS_OWNERSHIP_DELIVERY_WAIT_S", "240"))
DELIVERY_POLL_S = 4.0
_QUESTION = re.compile(r"[^?.!\n]*\?")

Followup = dict[str, Any]


def _spec(case: Case) -> dict[str, Any]:
    block = case.expected.get("ownership")
    return block if isinstance(block, dict) else {}


def _final_reply(run: CaseRun) -> str:
    """Everything the user read after their last message: the ack plus any delivered answer."""
    tail: list[str] = []
    for message in run.messages:
        if message.get("role") == "user":
            tail = []
        elif message.get("role") == "assistant" and message.get("kind") != REACTION_KIND:
            tail.append(str(message.get("content") or ""))
    return "\n".join(part for part in tail if part.strip()).strip()


def _is_echo(run: CaseRun, reply: str) -> bool:
    users = {
        str(m.get("content") or "").strip().lower() for m in run.messages if m.get("role") == "user"
    }
    return reply.strip().lower() in users


def _inspectable_reply(run: CaseRun) -> str | None:
    """The final reply, or None when the run said nothing or only parroted the user.

    A tap-back with no words is a real reply (the comms prompt's REACT) and reads
    as an empty one: no words, no questions.
    """
    if produced_nothing(run.messages, run.tool_calls, run.text):
        return None
    reply = _final_reply(run)
    if not reply:
        return "" if _reacted_last(run) else None
    if _is_echo(run, reply):
        return None
    return reply


def _reacted_last(run: CaseRun) -> bool:
    reacted = False
    for message in run.messages:
        if message.get("role") == "user":
            reacted = False
        elif message.get("kind") == REACTION_KIND:
            reacted = True
    return reacted


def executor_brief_gate(case: Case, run: CaseRun) -> float:
    """A call_executor brief carries the user's specifics and a definition of done."""
    brief = _spec(case).get("brief") or {}
    terms = [str(t).lower() for t in brief.get("terms") or []]
    min_criteria = int(brief.get("min_criteria", 1))
    for call in run.tool_calls:
        if call.get("name") != DELEGATION_TOOL:
            continue
        args = call.get("args") or {}
        criteria = [str(c) for c in args.get("acceptance_criteria") or [] if str(c).strip()]
        haystack = " ".join([str(args.get("task") or ""), *criteria]).lower()
        if len(criteria) >= min_criteria and all(term in haystack for term in terms):
            return 1.0
    return 0.0


def question_budget_gate(case: Case, run: CaseRun) -> float:
    """The final reply asks between min and max questions (L0 asks none, L2/L4 exactly one)."""
    reply = _inspectable_reply(run)
    if reply is None:
        return 0.0
    budget = _spec(case).get("questions") or {}
    asked = len(_QUESTION.findall(reply))
    return 1.0 if int(budget.get("min", 0)) <= asked <= int(budget.get("max", 0)) else 0.0


def reply_brevity_gate(case: Case, run: CaseRun) -> float:
    """The final reply stays within the case's word budget."""
    reply = _inspectable_reply(run)
    if reply is None:
        return 0.0
    return 1.0 if len(reply.split()) <= int(_spec(case)["max_words"]) else 0.0


def followup_gate(case: Case, run: CaseRun) -> float:
    """required: a new follow-up with a wake source exists; forbidden: none was created.

    followup_kind: todo demands a tracked todo, the one follow-up GAIA itself wakes on; a reminder only
    pings the user, so it satisfies a plain "remind me" and never a "check back".
    """
    followups = (run.end_state or {}).get("followups")
    if not isinstance(followups, list) or produced_nothing(run.messages, run.tool_calls, run.text):
        return 0.0
    spec = _spec(case)
    if spec["followup"] == "forbidden":
        return 1.0 if not followups else 0.0
    term = str(spec.get("followup_contains") or "").lower()
    prefix = f"{spec['followup_kind']}:" if spec.get("followup_kind") else ""
    return (
        1.0
        if any(
            f["wake"] and f["id"].startswith(prefix) and term in str(f["title"]).lower()
            for f in followups
        )
        else 0.0
    )


class OwnershipTransport(ChatStreamTransport):
    """Chat-stream turns, the delivered executor answer, and the durable follow-ups they left."""

    def __init__(self) -> None:
        super().__init__()
        self.user_prefix = "ownership"

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        deadline = float(os.environ.get("EVALS_CASE_TIMEOUT_S", "420"))
        turns = turns_for(case)
        if not turns:
            raise ProviderError(provider.name, f"case {case.id} has no turns")
        transcript: list[dict[str, str]] = []
        tool_calls: list[dict[str, Any]] = []
        final_turn_tool_calls: list[dict[str, Any]] = []
        raw: list[dict[str, Any]] = []
        conversation_id: str | None = None
        error: str | None = None
        end_state: dict[str, Any] | None = None
        start = time.monotonic()

        try:
            async with asyncio.timeout(deadline):
                email = self.case_email(case)
                await provision(DEV_API_BASE, email)
                async with dev_client(email) as client:
                    client.timeout = self._timeout
                    seeded = await self._seed(client, case, provider)
                    before = {f["id"] for f in await self._followups(client)} | {
                        f"todo:{row['id']}" for row in await self._todos(client)
                    }
                    for index, turn_text in enumerate(turns):
                        payload: TurnPayload = {
                            "message": turn_text,
                            "conversation_id": conversation_id,
                            "messages": transcript + [{"role": "user", "content": turn_text}],
                            "turn_id": f"own-{case.id[:44]}-{index}-{uuid.uuid4().hex[:8]}",
                        }
                        turn = await self._stream_turn(client, payload, provider, email)
                        conversation_id = turn["conversation_id"] or conversation_id
                        transcript.append({"role": "user", "content": turn_text})
                        if turn["text"]:
                            transcript.append({"role": "assistant", "content": turn["text"]})
                        if turn["reaction"]:
                            transcript.append(
                                {
                                    "role": "assistant",
                                    "content": f"[reaction: {turn['reaction']}]",
                                    "kind": REACTION_KIND,
                                }
                            )
                        tool_calls.extend(turn["tool_calls"])
                        final_turn_tool_calls = turn["tool_calls"]
                        raw.extend(turn["raw"])
                        error = error or turn["error"]
                        delegated = any(c["name"] == DELEGATION_TOOL for c in turn["tool_calls"])
                        if delegated and conversation_id:
                            delivered = await self._await_result(
                                client, conversation_id, turn_text, turn["text"]
                            )
                            raw.append({"type": "delivered", "chars": len(delivered)})
                            if delivered:
                                transcript.append(
                                    {
                                        "role": "assistant",
                                        "content": delivered,
                                        "kind": DELIVERED_KIND,
                                    }
                                )
                    end_state = await self._end_state(client, case, seeded, before)
        except TimeoutError:
            error = f"case timed out after {deadline:.0f}s"
        except httpx.HTTPError as e:
            raise ProviderError(provider.name, f"ownership transport failed: {e}") from e

        # A reaction is what the user saw, so it is the run's output too: the
        # shared absence gates read run.text to tell "did nothing" from "replied".
        text = " ".join(m["content"] for m in transcript if m["role"] == "assistant").strip()
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=transcript,
            tool_calls=tool_calls,
            final_turn_tool_calls=final_turn_tool_calls,
            end_state=end_state,
            text=text,
            raw=raw,
            tokens_in=estimate_tokens(
                " ".join(m["content"] for m in transcript if m["role"] == "user")
            ),
            tokens_out=estimate_tokens(text),
            duration_s=time.monotonic() - start,
            error=error[:300] if error else None,
        )

    async def _await_result(
        self, client: httpx.AsyncClient, conversation_id: str, user_text: str, ack: str
    ) -> str:
        """Wait for the executor's result to land as a bot message after the streamed ack.

        Not live_chat.await_delivery: it returns as soon as a tool card is saved,
        which here is often before the result, and it assumes the ack is a saved
        message, which a reaction-only ack is not.
        """
        deadline = time.monotonic() + DELIVERY_WAIT_S
        last = ""
        while time.monotonic() < deadline:
            await asyncio.sleep(DELIVERY_POLL_S)
            resp = await client.get(f"{API}/conversations/{conversation_id}")
            resp.raise_for_status()
            payload = resp.json()
            messages = payload.get("conversation", payload).get("messages") or []
            texts = [
                text
                for message in bot_messages_after(messages, user_text)
                if (text := str(message.get("response") or "").strip()) and text != ack.strip()
            ]
            current = "\n".join(texts)
            if current and current == last:
                return current
            last = current
        return last

    async def _seed(
        self, client: httpx.AsyncClient, case: Case, provider: ProviderConfig
    ) -> list[str]:
        """Create the case's starting todos through the real API; return their ids."""
        ids: list[str] = []
        for title in (case.setup.get("seed") or {}).get("todos") or []:
            resp = await client.post(f"{API}/todos", json={"title": str(title)})
            if resp.status_code != 201:
                raise ProviderError(
                    provider.name, f"seed todo failed: HTTP {resp.status_code}: {resp.text[:200]}"
                )
            ids.append(str(resp.json()["id"]))
        return ids

    async def _todos(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        resp = await client.get(f"{API}/todos", params={"per_page": 100, "mode": "text"})
        resp.raise_for_status()
        return list(resp.json().get("data") or [])

    async def _followups(self, client: httpx.AsyncClient) -> list[Followup]:
        """Every tracked todo and reminder the user has, with whether it will wake on its own."""
        todos = await client.get(
            f"{API}/todos", params={"labels": TRACKED_LABEL, "per_page": 100, "mode": "text"}
        )
        todos.raise_for_status()
        reminders = await client.get(f"{API}/reminders")
        reminders.raise_for_status()
        found: list[Followup] = [
            {
                "id": f"todo:{row['id']}",
                "title": row.get("title") or "",
                "wake": not row.get("completed")
                and bool(
                    row.get("scheduled_at")
                    or row.get("recurrence")
                    or row.get("trigger_subscriptions")
                ),
            }
            for row in todos.json().get("data") or []
            if TRACKED_LABEL in (row.get("labels") or [])
        ]
        found.extend(
            {
                "id": f"reminder:{row['id']}",
                "title": (row.get("payload") or {}).get("title") or "",
                "wake": row.get("status") in ACTIVE_REMINDER_STATUSES,
            }
            for row in reminders.json()
        )
        return found

    async def _end_state(
        self,
        client: httpx.AsyncClient,
        case: Case,
        seeded: list[str],
        before: set[str],
    ) -> dict[str, Any]:
        """Follow-ups created during the case, plus the todo keys the case asserts."""
        state: dict[str, Any] = {
            "followups": [f for f in await self._followups(client) if f["id"] not in before]
        }
        wanted = case.expected.get("end_state") or {}
        if not wanted:
            return state
        open_todos = [row for row in await self._todos(client) if not row.get("completed")]
        for key in wanted:
            if key == "seeded_intact":
                open_ids = {str(row["id"]) for row in open_todos}
                state[key] = all(todo_id in open_ids for todo_id in seeded)
            elif key == "todos_containing":
                term = str(case.setup["verify"]["todos_containing"]).lower()
                state[key] = sum(
                    1
                    for row in open_todos
                    if f"todo:{row['id']}" not in before
                    and TRACKED_LABEL not in (row.get("labels") or [])
                    and term in str(row.get("title") or "").lower()
                )
            else:
                raise RuntimeError(f"ownership end_state: no projection for key {key!r}")
        return state


@register_suite("ownership")
class OwnershipSuite(Suite):
    name = "ownership"
    project = "gaia-ownership"
    label = "Ownership & ambiguity ladder"

    EXTRA_GATES: ClassVar[ExtraGates] = {
        "executor_brief": executor_brief_gate,
        "question_budget": question_budget_gate,
        "reply_brevity": reply_brevity_gate,
        "followup": followup_gate,
    }

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._cases: list[Case] | None = None
        self._transport = OwnershipTransport()

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        if self._cases is None:
            self._cases = load_case_files(DATA_DIR, self.name, self.EXTRA_GATES)
        return self._cases

    def transport(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> Awaitable[CaseRun]:
        return self._transport.run(case, cfg, tracker, provider)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        return score_gates(case, run, self.EXTRA_GATES)

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        return [
            DelegationGate(),
            CommunicateGate(),
            MustNotCommunicate(),
            EndStateEquality(),
            RubricJudge(
                base_url=os.environ.get("DEV_LLM_BASE_URL", ""),
                api_key=os.environ.get("DEV_LLM_API_KEY", ""),
                model=judge_model(cfg),
            ),
        ]
