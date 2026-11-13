"""HIL suite — does GAIA actually stop and ask, and does it understand?

Two families, one transport.

**The gate family** drives the REAL human-in-the-loop machinery end to end, over
plain HTTP, with nothing simulated:

1. mint a fresh dev user per case (POST /api/v1/dev/users) — HIL preferences
   and tool overrides are per-user, so a shared identity would leak one case's
   always_tool write into the next case's policy;
2. arm the gate (PUT /api/v1/approvals/preferences with mode and
   tool_overrides). This matters: HIL_DEFAULT_MODE is always_allow
   (app/models/hil_models.py), so HIL is OFF until a user turns it on — a
   suite that skipped this step would prove nothing and pass everything;
3. send the turn (POST /api/v1/conversations/{id}/messages) and follow the
   conversation's events (core.live_chat). When a gated call is reached,
   services/hil/gate.decide_tool_call pauses the work and logs an
   ApprovalRequested entry, so the events show the approval pending and the
   work still live, with nothing executed;
4. answer it (POST /api/v1/approvals/{approval_id}/decision), which logs an
   ApprovalDecided entry and resumes the work;
5. keep following the same events until the work's write-up settles, then read
   the REAL effect back from the domain API (GET /api/v1/todos,
   GET /api/v1/notifications).

Which tools are gated is not invented either. send_notification is one of the
three code-reviewed destructive built-ins (agents/tools/core/registry.py), so
mode: always_ask alone gates it. Everything else is gated the way a user
would gate it, through tool_overrides — the same per-user map the settings UI
writes and services/hil/policy.resolve_policy reads first.

**The comprehension family** needs no gate: underspecified, self-contradictory
and multi-step requests where the agent has to restate what it is about to do, or
ask one question, before acting. Those run with mode: always_allow and are
gated on what was said and on what was NOT called.

The approval statuses a case gates on (cards) are what the events showed, in
order: pending when requested, then the decision, or a card's own status when the
gate settled it without asking (auto_approved).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import os
from pathlib import Path
import time
from typing import Any
import uuid

import httpx

from scripts.evals.core.cases import load_case_files
from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.gates import score_gates
from scripts.evals.core.live_chat import PENDING, TurnReader, called_tools, follow, send_message
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

# Whole-case budget. Larger than the quality suite's: a HIL case is a turn that
# pauses, an out-of-band decision, and a second run that has to finish.
CASE_TIMEOUT_S = float(os.environ.get("EVALS_HIL_TIMEOUT_S", "420"))
# Its own budget, not a fraction of the case timeout: a card that never
# settles (see approval_gate.yaml) otherwise spends 3.5 minutes per case failing.
RESUME_TIMEOUT_S = float(os.environ.get("EVALS_HIL_RESUME_TIMEOUT_S", "90"))

Card = dict[str, Any]


def _url(path: str) -> str:
    return f"{DEV_API_BASE}/api/v1{path}"


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
        error: str | None = None
        start = time.monotonic()

        try:
            async with asyncio.timeout(CASE_TIMEOUT_S):
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    await self._mint_user(client, email, provider)
                    client.headers[DEV_USER_HEADER] = email
                    await self._arm_gate(client, case, provider)
                    conversation_id = str(uuid.uuid4())
                    readers = [
                        await self._send(client, conversation_id, turn_text)
                        for turn_text in self._turns(case, provider)
                    ]
                    await self._decide(client, case, conversation_id, readers, raw)
                    for reader in readers:
                        turn = reader.turn()
                        transcript.append({"role": "user", "content": turn.message})
                        answer = "\n".join(
                            [*([] if turn.is_empty else [turn.reply]), *turn.delivered]
                        )
                        if answer:
                            transcript.append({"role": "assistant", "content": answer})
                            texts.append(answer)
                        tool_calls.extend(called_tools(turn.tool_data))
                        cards.extend(seen.model_dump() for seen in turn.approvals)
                        error = error or turn.error
                    end_state = await self._end_state(client, case, cards, texts)
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
        # Estimates only — the HIL endpoints report no usage. Deliberately not
        # pushed through tracker.add_manual: that would stamp a chars/4 guess
        # "metered", which is how 14-token cases once passed for real.
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
        self, client: httpx.AsyncClient, case: Case, provider: ProviderConfig
    ) -> None:
        """Write the case's HIL preferences, failing loud since an unarmed gate turns every gate case into a green run that proved nothing."""
        hil = case.setup.get("hil")
        if not isinstance(hil, dict):
            raise ProviderError(provider.name, f"case {case.id} has no setup.hil block")
        resp = await client.put(
            _url("/approvals/preferences"),
            json={"mode": hil["mode"], "tool_overrides": hil.get("tool_overrides") or {}},
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

    async def _send(self, client: httpx.AsyncClient, conversation_id: str, text: str) -> TurnReader:
        """Send one turn and follow it until it is settled or waiting on an approval."""
        accepted = await send_message(client, DEV_API_BASE, conversation_id, text)
        reader = TurnReader(text, accepted.message_id, stop_at_approval=True)
        await follow(
            client,
            DEV_API_BASE,
            conversation_id,
            reader,
            after=accepted.seq - 1,
            delivery_wait_seconds=CASE_TIMEOUT_S,
        )
        return reader

    # -- the decision --------------------------------------------------------

    async def _decide(
        self,
        client: httpx.AsyncClient,
        case: Case,
        conversation_id: str,
        readers: list[TurnReader],
        raw: list[dict[str, Any]],
    ) -> None:
        """Answer the pending approval and follow the resumed work until its write-up settles.

        Does nothing when the case declares no decision, and also when the gate never
        paused: the missing approval is exactly what the cards end-state assertion is
        there to catch, so it is recorded, not raised.
        """
        decision = case.setup.get("decision")
        if not isinstance(decision, dict):
            return
        waiting = [reader for reader in readers if reader.awaiting_approval]
        if not waiting:
            raw.append({"type": "decision_skipped", "reason": "no pending approval"})
            return
        reader = waiting[-1]
        turn = reader.turn()
        latest = {seen.approval_id: seen.status for seen in turn.approvals}
        pending = next(ap for ap, status in latest.items() if status == PENDING)
        resp = await client.post(
            _url(f"/approvals/{pending}/decision"),
            json={
                "decision": decision["kind"],
                "feedback": decision.get("feedback"),
                "scope": decision.get("scope", "once"),
            },
        )
        raw.append(
            {
                "type": "decision",
                "approval_id": pending,
                "kind": decision["kind"],
                "http_status": resp.status_code,
                "body": (resp.text or "")[:200],
            }
        )
        if resp.status_code != 200:
            return
        try:
            async with asyncio.timeout(RESUME_TIMEOUT_S):
                await follow(
                    client,
                    DEV_API_BASE,
                    conversation_id,
                    reader,
                    after=turn.last_seq,
                    delivery_wait_seconds=RESUME_TIMEOUT_S,
                )
        except TimeoutError:
            raw.append({"type": "resume_followed", "settled": False})
            print(
                f"    [hil] {pending[:8]} work NEVER settled within {RESUME_TIMEOUT_S:.0f}s "
                "— the end_state gate below reports what did/did not happen"
            )
            return
        raw.append({"type": "resume_followed", "settled": reader.settled})

    # -- the world afterwards ------------------------------------------------

    async def _end_state(
        self,
        client: httpx.AsyncClient,
        case: Case,
        cards: list[Card],
        texts: list[str],
    ) -> dict[str, Any]:
        """Project only the end-state keys this case actually asserts."""
        wanted = case.expected.get("end_state")
        if not isinstance(wanted, dict):
            return {}
        verify = case.setup.get("verify") or {}
        projected: dict[str, Any] = {}
        for key in wanted:
            if key == "cards":
                projected[key] = [str(card.get("status")) for card in cards]
            elif key == "approvals":
                projected[key] = len({str(card.get("approval_id")) for card in cards})
            elif key == "todos_containing":
                term = str(verify["todos_containing"]).lower()
                resp = await client.get(_url("/todos"))
                rows = resp.json().get("data") or [] if resp.status_code == 200 else []
                projected[key] = sum(1 for row in rows if term in str(row.get("title", "")).lower())
            elif key == "notifications":
                resp = await client.get(_url("/notifications"))
                rows = resp.json().get("notifications") or [] if resp.status_code == 200 else []
                projected[key] = len(rows)
            elif key == "notifications_containing":
                # Count alone is satisfied by the agent's own notifications
                # (observed: a "Confirm notification channel" question), so
                # match the body/title to prove the APPROVED action happened.
                term = str(verify["notifications_containing"]).lower()
                resp = await client.get(_url("/notifications"))
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
