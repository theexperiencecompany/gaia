"""HIL suite — does GAIA actually stop and ask, and does it understand?

Two families, one transport.

**The gate family** drives the REAL human-in-the-loop machinery end to end, over
plain HTTP, with nothing simulated:

1. mint a fresh dev user per case (``POST /api/v1/dev/users``) — HIL preferences
   and tool overrides are per-user, so a shared identity would leak one case's
   ``always_tool`` write into the next case's policy;
2. arm the gate (``PUT /api/v1/approvals/preferences`` with ``mode`` and
   ``tool_overrides``). This matters: ``HIL_DEFAULT_MODE`` is ``always_allow``
   (``app/models/hil_models.py``), so HIL is OFF until a user turns it on — a
   suite that skipped this step would prove nothing and pass everything;
3. send the turn to ``POST /api/v1/chat-stream``. When a gated call is reached,
   ``services/hil/gate.decide_tool_call`` raises LangGraph's ``interrupt()``;
   ``bridge.publish_approval_request`` puts an ``approval_request`` card on the
   turn's stream, and the pause signals the executor done — so the SSE response
   ends with the card in it and nothing executed;
4. answer it (``POST /api/v1/approvals/{approval_id}/decision``), which resumes
   the run on a NEW ``queued_*`` stream;
5. re-read ``GET /api/v1/conversations/{id}`` until the card settles, and read the
   REAL effect back from the domain API (``GET /api/v1/todos``,
   ``GET /api/v1/notifications``).

Which tools are gated is not invented either. ``send_notification`` is one of the
three code-reviewed destructive built-ins (``agents/tools/core/registry.py``), so
``mode: always_ask`` alone gates it. Everything else is gated the way a user
would gate it, through ``tool_overrides`` — the same per-user map the settings UI
writes and ``services/hil/policy.resolve_policy`` reads first.

**The comprehension family** needs no gate: underspecified, self-contradictory
and multi-step requests where the agent has to restate what it is about to do, or
ask one question, before acting. Those run with ``mode: always_allow`` and are
gated on what was said and on what was NOT called.

Known boundary — say it out loud: the resumed run publishes on a stream this
client never sees (its id is announced over WebSocket only), so everything after
the decision is read from Mongo through the conversations API and from the domain
APIs. That is the durable end state, not the live frames; the frame-level
behaviour of a resume is pinned by ``tests/e2e/test_hil_streaming.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid

import httpx

from scripts.evals.core.cases import load_case_files
from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.gates import score_gates
from scripts.evals.core.providers import EvalConfig, ProviderConfig, judge_model
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.scorers import (
    CommunicateGate,
    EndStateEquality,
    MustNotCommunicate,
    NoForbiddenToolCalls,
    RubricJudge,
)
from scripts.evals.core.types import Case, CaseRun, ProviderError

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "hil"
DEV_API_BASE = os.environ.get("EVALS_DEV_API_BASE", "http://localhost:9460")
DEV_USER_HEADER = "X-Dev-User"
APPROVAL_CARD_TOOL = "approval_request"

# Whole-case budget. Larger than the quality suite's: a HIL case is a turn that
# pauses, an out-of-band decision, and a second run that has to finish.
CASE_TIMEOUT_S = float(os.environ.get("EVALS_HIL_TIMEOUT_S", "420"))
# How long to wait for a decided approval's card to settle in the conversation.
# Its own budget, not a fraction of the case timeout: a card that will never
# settle (see the send_notification finding in approval_gate.yaml) otherwise
# spends 3.5 minutes per case failing. A settle is normally seen in one or two
# polls — the create_tracked_todo path lands in ~3-6s.
RESUME_TIMEOUT_S = float(os.environ.get("EVALS_HIL_RESUME_TIMEOUT_S", "90"))
RESUME_POLL_INTERVAL_S = 3.0

Frame = dict[str, Any]
Card = dict[str, Any]


def _url(path: str) -> str:
    return f"{DEV_API_BASE}/api/v1{path}"


def _reduce(frames: list[Frame]) -> dict[str, Any]:
    """The parts of a turn this suite gates on: id, text, calls, approval cards.

    Deliberately narrower than ``quality._parse_frames``: that reduction exists to
    journal a readable summary of every frame kind, and truncates ``tool_data``
    payloads to 200 chars — which would cut an approval card's ``status`` off.
    """
    conversation_id: str | None = None
    chunks: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    cards: list[Card] = []
    error: str | None = None

    for frame in frames:
        if isinstance(frame.get("response"), str):
            chunks.append(frame["response"])
        elif "stream_id" in frame:
            conversation_id = frame.get("conversation_id") or conversation_id
        elif isinstance(frame.get("error"), str):
            error = error or frame["error"]
        elif "tool_data" in frame:
            entries = frame["tool_data"]
            for entry in entries if isinstance(entries, list) else [entries]:
                if not isinstance(entry, dict):
                    continue
                data = entry.get("data")
                if not isinstance(data, dict):
                    continue
                if entry.get("tool_name") == APPROVAL_CARD_TOOL:
                    cards.append(data)
                elif entry.get("tool_name") == "tool_calls_data":
                    tool_calls.append(
                        {
                            "name": data.get("tool_name"),
                            "args": data.get("inputs")
                            if isinstance(data.get("inputs"), dict)
                            else {},
                        }
                    )
    return {
        "conversation_id": conversation_id,
        "text": "".join(chunks),
        "tool_calls": tool_calls,
        "cards": cards,
        "error": error,
    }


class HilTransport:
    """One HIL case: arm the gate, drive the turn, decide, read the world back."""

    def __init__(self) -> None:
        self._timeout = httpx.Timeout(connect=15.0, read=900.0, write=30.0, pool=15.0)

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        email = f"hil-{uuid.uuid4().hex[:10]}@gaia.local"
        transcript: list[dict[str, str]] = []
        tool_calls: list[dict[str, Any]] = []
        cards: list[Card] = []
        raw: list[dict[str, Any]] = []
        texts: list[str] = []
        conversation_id: str | None = None
        error: str | None = None
        start = time.monotonic()

        try:
            async with asyncio.timeout(CASE_TIMEOUT_S):
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    await self._mint_user(client, email, provider)
                    await self._arm_gate(client, email, case, provider)
                    for index, turn in enumerate(self._turns(case, provider)):
                        payload = {
                            "message": turn,
                            "conversation_id": conversation_id,
                            "messages": transcript + [{"role": "user", "content": turn}],
                            "turn_id": f"hil-{case.id}-{index}-{uuid.uuid4().hex[:6]}",
                        }
                        reduced = await self._stream_turn(client, email, payload, provider)
                        conversation_id = reduced["conversation_id"] or conversation_id
                        transcript.append({"role": "user", "content": turn})
                        if reduced["text"]:
                            transcript.append({"role": "assistant", "content": reduced["text"]})
                        texts.append(reduced["text"])
                        tool_calls.extend(reduced["tool_calls"])
                        cards.extend(reduced["cards"])
                        error = error or reduced["error"]
                    decided = await self._decide(client, email, case, cards, conversation_id, raw)
                    if decided is not None:
                        cards.extend(decided["cards"])
                        if decided["text"]:
                            transcript.append({"role": "assistant", "content": decided["text"]})
                            texts.append(decided["text"])
                    end_state = await self._end_state(client, email, case, cards, texts)
        except TimeoutError:
            error = f"case timed out after {CASE_TIMEOUT_S:.0f}s"
            end_state = None
        except httpx.HTTPError as e:
            raise ProviderError(provider.name, f"hil transport failed: {e}") from e

        text = " ".join(part for part in texts if part).strip()
        raw.append({"type": "approval_cards", "cards": cards})
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
                error=error[:300],
            )
        # Estimates only — the HIL endpoints report no usage. Deliberately NOT
        # pushed through tracker.add_manual: that books into the per-case meter,
        # and the runner would then stamp the figure "metered". A chars/4 guess
        # entering the trusted channel is how 14-token cases passed for real.
        tokens_in = estimate_tokens(
            " ".join(m["content"] for m in transcript if m["role"] == "user")
        )
        tokens_out = estimate_tokens(
            " ".join(m["content"] for m in transcript if m["role"] == "assistant")
        )
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=transcript,
            tool_calls=tool_calls,
            end_state=end_state,
            text=text,
            raw=raw,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_s=time.monotonic() - start,
        )

    # -- setup ---------------------------------------------------------------

    def _turns(self, case: Case, provider: ProviderConfig) -> list[str]:
        turns = [
            str(turn) for turn in (case.setup.get("turns") or [case.prompt]) if str(turn).strip()
        ]
        if not turns:
            raise ProviderError(provider.name, f"case {case.id} has no turns")
        return turns

    async def _mint_user(
        self, client: httpx.AsyncClient, email: str, provider: ProviderConfig
    ) -> None:
        resp = await client.post(_url("/dev/users"), json={"email": email})
        if resp.status_code not in (200, 201):
            raise ProviderError(
                provider.name,
                f"dev users endpoint failed: HTTP {resp.status_code}: {(resp.text or '')[:200]}",
            )

    async def _arm_gate(
        self, client: httpx.AsyncClient, email: str, case: Case, provider: ProviderConfig
    ) -> None:
        """Write the case's HIL preferences. Fails loud — an unarmed gate would
        turn every gate case into a green run that proved nothing."""
        hil = case.setup.get("hil")
        if not isinstance(hil, dict):
            raise ProviderError(provider.name, f"case {case.id} has no setup.hil block")
        resp = await client.put(
            _url("/approvals/preferences"),
            json={"mode": hil["mode"], "tool_overrides": hil.get("tool_overrides") or {}},
            headers={DEV_USER_HEADER: email},
        )
        if resp.status_code != 200:
            raise ProviderError(
                provider.name,
                f"could not arm HIL: HTTP {resp.status_code}: {(resp.text or '')[:200]}",
            )
        applied = resp.json()
        if applied.get("mode") != hil["mode"]:
            raise ProviderError(
                provider.name, f"HIL mode did not stick: asked {hil['mode']}, got {applied}"
            )

    # -- the turn ------------------------------------------------------------

    async def _stream_turn(
        self,
        client: httpx.AsyncClient,
        email: str,
        payload: dict[str, Any],
        provider: ProviderConfig,
    ) -> dict[str, Any]:
        frames: list[Frame] = []
        async with client.stream(
            "POST",
            _url("/chat-stream"),
            json=payload,
            headers={DEV_USER_HEADER: email},
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise ProviderError(
                    provider.name, f"chat-stream HTTP {resp.status_code}: {body[:200]}"
                )
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    frames.append(json.loads(data))
                except ValueError:
                    continue
        if not frames:
            raise ProviderError(provider.name, "chat-stream returned no frames")
        return _reduce(frames)

    # -- the decision --------------------------------------------------------

    async def _decide(
        self,
        client: httpx.AsyncClient,
        email: str,
        case: Case,
        cards: list[Card],
        conversation_id: str | None,
        raw: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Answer the pending approval and wait for the resumed run to land.

        Returns ``None`` when the case declares no decision, and also when the
        gate never paused — the missing card is exactly what the ``cards``
        end-state assertion is there to catch, so it is recorded, not raised.
        """
        decision = case.setup.get("decision")
        if not isinstance(decision, dict) or conversation_id is None:
            return None
        pending = next((c for c in cards if c.get("status") == "pending"), None)
        if pending is None:
            raw.append({"type": "decision_skipped", "reason": "no pending approval card"})
            return None
        approval_id = str(pending["approval_id"])
        resp = await client.post(
            _url(f"/approvals/{approval_id}/decision"),
            json={
                "decision": decision["kind"],
                "feedback": decision.get("feedback"),
                "scope": decision.get("scope", "once"),
            },
            headers={DEV_USER_HEADER: email},
        )
        raw.append(
            {
                "type": "decision",
                "approval_id": approval_id,
                "kind": decision["kind"],
                "http_status": resp.status_code,
                "body": (resp.text or "")[:200],
            }
        )
        if resp.status_code != 200:
            return None
        return await self._await_resume(client, email, conversation_id, approval_id, raw)

    async def _await_resume(
        self,
        client: httpx.AsyncClient,
        email: str,
        conversation_id: str,
        approval_id: str,
        raw: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Poll the conversation until this approval's card settles.

        The resumed run publishes on a ``queued_*`` stream whose id is announced
        over WebSocket only, so Mongo — re-read through the conversations API — is
        the observable an HTTP client has. ``publish_decision`` writes the settled
        card onto that run's session, and the executor drain persists it.
        """
        deadline = time.monotonic() + RESUME_TIMEOUT_S
        settled: list[Card] = []
        text = ""
        while time.monotonic() < deadline:
            await asyncio.sleep(RESUME_POLL_INTERVAL_S)
            cards, text = await self._conversation_state(client, email, conversation_id)
            settled = [
                c
                for c in cards
                if c.get("approval_id") == approval_id and c.get("status") != "pending"
            ]
            if settled:
                break
        raw.append({"type": "resume_polled", "settled": bool(settled)})
        if settled:
            print(f"    [hil] {approval_id[:8]} card settled → {settled[-1].get('status')}")
        else:
            print(
                f"    [hil] {approval_id[:8]} card NEVER settled within {RESUME_TIMEOUT_S:.0f}s "
                "— the end_state gate below reports what did/did not happen"
            )
        return {"cards": settled, "text": text}

    async def _conversation_state(
        self, client: httpx.AsyncClient, email: str, conversation_id: str
    ) -> tuple[list[Card], str]:
        """Every approval card and the latest bot message text, from Mongo."""
        resp = await client.get(
            _url(f"/conversations/{conversation_id}"), headers={DEV_USER_HEADER: email}
        )
        if resp.status_code != 200:
            return [], ""
        messages = resp.json().get("messages") or []
        cards: list[Card] = []
        text = ""
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("type") == "bot" and message.get("response"):
                text = str(message["response"])
            for entry in message.get("tool_data") or []:
                if isinstance(entry, dict) and entry.get("tool_name") == APPROVAL_CARD_TOOL:
                    data = entry.get("data")
                    if isinstance(data, dict):
                        cards.append(data)
        return cards, text

    # -- the world afterwards ------------------------------------------------

    async def _end_state(
        self,
        client: httpx.AsyncClient,
        email: str,
        case: Case,
        cards: list[Card],
        texts: list[str],
    ) -> dict[str, Any]:
        """Project only the end-state keys this case actually asserts."""
        wanted = case.expected.get("end_state")
        if not isinstance(wanted, dict):
            return {}
        verify = case.setup.get("verify") or {}
        headers = {DEV_USER_HEADER: email}
        projected: dict[str, Any] = {}
        for key in wanted:
            if key == "cards":
                projected[key] = [str(card.get("status")) for card in cards]
            elif key == "approvals":
                projected[key] = len({str(card.get("approval_id")) for card in cards})
            elif key == "todos_containing":
                term = str(verify["todos_containing"]).lower()
                resp = await client.get(_url("/todos"), headers=headers)
                rows = resp.json().get("data") or [] if resp.status_code == 200 else []
                projected[key] = sum(1 for row in rows if term in str(row.get("title", "")).lower())
            elif key == "notifications":
                resp = await client.get(_url("/notifications"), headers=headers)
                rows = resp.json().get("notifications") or [] if resp.status_code == 200 else []
                projected[key] = len(rows)
            elif key == "notifications_containing":
                # Count is not enough to prove the APPROVED action happened: the
                # agent sends notifications of its own (observed: a "Confirm
                # notification channel" question), and a bare `notifications: 1`
                # is satisfied by that instead. Match the body/title so only the
                # user's own payload can satisfy the gate.
                term = str(verify["notifications_containing"]).lower()
                resp = await client.get(_url("/notifications"), headers=headers)
                rows = resp.json().get("notifications") or [] if resp.status_code == 200 else []
                projected[key] = sum(
                    1
                    for row in rows
                    if term
                    in f"{(row.get('content') or {}).get('title', '')} "
                    f"{(row.get('content') or {}).get('body', '')}".lower()
                )
            elif key == "answer_contains":
                term = str(wanted[key]).lower()
                joined = " ".join(texts).lower()
                projected[key] = term if term in joined else ""
            else:
                raise RuntimeError(f"hil end_state: no projection for key {key!r}")
        return projected


@register_suite("hil")
class HilSuite(Suite):
    name = "hil"
    project = "gaia-hil"
    label = "HIL & comprehension"

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._cases: list[Case] | None = None
        self._transport = HilTransport()

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        if self._cases is None:
            self._cases = load_case_files(DATA_DIR, self.name)
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
        return score_gates(case, run)

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        return [
            EndStateEquality(),
            CommunicateGate(),
            MustNotCommunicate(),
            NoForbiddenToolCalls(),
            RubricJudge(
                base_url=os.environ.get("DEV_LLM_BASE_URL", ""),
                api_key=os.environ.get("DEV_LLM_API_KEY", ""),
                model=judge_model(cfg),
            ),
        ]
