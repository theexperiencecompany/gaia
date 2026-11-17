# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "telethon>=1.45",
#     "pyyaml>=6.0",
#     "httpx>=0.27",
# ]
# ///
"""Live Telegram edge suite: the founder's real Telegram account talks to the dev bot, the real API and model answer.

Not CI: it needs a real account, a running stack and a real model. Run it against a stack you already started:

    mise e2e:telegram                      # every scenario in tools/telegram-edge/scenarios/
    mise e2e:telegram burst-unrelated stop-mid-work
    mise e2e:telegram --list

Needs: the tgsend session (~/.local/share/gaia-tg/gaia.session, `tgsend.py login` once) and the Keychain items
agent/TELEGRAM_API_ID and agent/TELEGRAM_API_HASH. The Telegram account must be linked to the stack's dev user
(dev@gaia.local), because approvals are switched on and todos are read through the API's dev bypass:
TG_EDGE_API (default http://localhost:8900/api/v1).

Restart scenarios run only when TG_EDGE_BOT_STOP and TG_EDGE_BOT_START hold the shell commands that stop and
start the bot (for the Rex pane the founder uses, `rex send -s <session> -b <block> $'\\003'` and the same `rex
send` with the start command); otherwise they are reported as skipped.

Each scenario starts with /new, runs its steps, waits until nothing changes, then every invariant in
edge_invariants.py and the scenario's own expectations are checked. Output: report.json (full transcripts) and
report.txt (one line per scenario plus every violation) under ~/.local/share/gaia-tg/edge-runs/<UTC time>/.
Exit code 1 when any scenario has a failing violation.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets
import sys
import time

from edge_invariants import Violation, check_invariants
from edge_scenarios import Scenario, Todo, check_expectations, load_scenarios
from edge_telegram import Recorder, attach, connect
from edge_transcript import Transcript
import httpx
from telethon import TelegramClient
from telethon.tl.types import User

API = os.environ.get("TG_EDGE_API", "http://localhost:8900/api/v1")
RUNS_DIR = Path.home() / ".local/share/gaia-tg/edge-runs"
BOT_STOP = os.environ.get("TG_EDGE_BOT_STOP", "")
BOT_START = os.environ.get("TG_EDGE_BOT_START", "")
QUIET_BEFORE_START_S = 8.0
QUIET_BEFORE_START_TIMEOUT_S = 120.0
DEFAULT_QUIET_S = 6.0
DEFAULT_REPLY_TIMEOUT_S = 120.0
DEFAULT_WAIT_FOR_TIMEOUT_S = 90.0
WAIT_TICK_S = 0.2


class StepTimeoutError(Exception):
    """A wait step saw nothing it waited for; the rest of the scenario depends on it."""


def api(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    """Call the stack's API as its dev-bypass user, failing loud on any error."""
    resp = httpx.request(method, f"{API}{path}", json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise TypeError(f"{method} {path} returned {data!r}")
    return data


def todos_for(nonce: str) -> list[Todo]:
    """Every todo whose title carries the run's nonce."""
    data = api("GET", f"/todos?q={nonce}&mode=text&per_page=100")["data"]
    if not isinstance(data, list):
        raise TypeError(f"/todos returned {data!r}")
    return [t for t in data if isinstance(t, dict)]


async def wait_until_quiet(recorder: Recorder, quiet: float, timeout: float) -> None:
    """Wait until nothing visible changed for `quiet` seconds."""
    deadline = time.monotonic() + timeout
    while recorder.quiet_for() < quiet:
        if time.monotonic() > deadline:
            recorder.mark("quiet_timeout", f"still changing after {timeout:g}s")
            return
        await asyncio.sleep(WAIT_TICK_S)


async def wait_reply(recorder: Recorder, quiet: float, timeout: float) -> None:
    """Wait for any visible answer to my last message, then for the chat to go quiet."""
    last = recorder.t.sent[-1]
    deadline = time.monotonic() + timeout
    while not recorder.t.bot_after(last.sent_at) and last.first_reaction_at is None:
        if time.monotonic() > deadline:
            recorder.mark("reply_timeout", f"nothing after {last.id} within {timeout:g}s")
            return
        await asyncio.sleep(WAIT_TICK_S)
    await wait_until_quiet(recorder, quiet, max(deadline - time.monotonic(), quiet))


async def wait_for(recorder: Recorder, target: str, timeout: float) -> None:
    """Wait for an approval prompt or any new bubble after my last message; raise when none comes."""
    since = recorder.t.sent[-1].sent_at
    deadline = time.monotonic() + timeout
    while True:
        seen = (
            recorder.has_prompt_after(since)
            if target == "approval_prompt"
            else bool(recorder.t.bot_after(since))
        )
        if seen:
            return
        if time.monotonic() > deadline:
            recorder.mark("step_timeout", f"no {target} within {timeout:g}s")
            raise StepTimeoutError(f"no {target} within {timeout:g}s")
        await asyncio.sleep(WAIT_TICK_S)


async def shell(command: str) -> None:
    """Run an operator-provided shell command, failing loud on a non-zero exit."""
    proc = await asyncio.create_subprocess_shell(command)
    if await proc.wait() != 0:
        raise RuntimeError(f"command failed: {command}")


@dataclass
class StepContext:
    """What every step handler acts on: the client, the bot, the recording, tools to restore."""

    client: TelegramClient
    peer: User
    recorder: Recorder
    restored: set[str] = field(default_factory=set)


def _options(value: object) -> dict[str, object]:
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


async def _send(ctx: StepContext, step: dict[str, object]) -> None:
    ctx.recorder.sent(await ctx.client.send_message(ctx.peer, str(step["send"])))


async def _burst(ctx: StepContext, step: dict[str, object]) -> None:
    texts = step["burst"]
    if not isinstance(texts, list):
        raise TypeError("burst takes a list of texts")
    for i, text in enumerate(texts):
        if i:
            await asyncio.sleep(float(str(step.get("gap", 0.4))))
        ctx.recorder.sent(await ctx.client.send_message(ctx.peer, str(text)))


async def _sleep(_: StepContext, step: dict[str, object]) -> None:
    await asyncio.sleep(float(str(step["sleep"])))


async def _wait_reply(ctx: StepContext, step: dict[str, object]) -> None:
    opts = _options(step["wait_reply"])
    quiet = float(str(opts.get("quiet", DEFAULT_QUIET_S)))
    await wait_reply(ctx.recorder, quiet, float(str(opts.get("timeout", DEFAULT_REPLY_TIMEOUT_S))))


async def _wait_for(ctx: StepContext, step: dict[str, object]) -> None:
    timeout = float(str(step.get("timeout", DEFAULT_WAIT_FOR_TIMEOUT_S)))
    await wait_for(ctx.recorder, str(step["wait_for"]), timeout)


async def _set_tool_ask(ctx: StepContext, step: dict[str, object]) -> None:
    opts = _options(step["set_tool_ask"])
    tool = str(opts["tool"])
    api("PUT", f"/approvals/tools/{tool}", {"ask": opts["ask"]})
    ctx.restored.add(tool)
    ctx.recorder.mark("set_tool_ask", f"{tool}={opts['ask']}")


async def _restart_bot(ctx: StepContext, step: dict[str, object]) -> None:
    ctx.recorder.mark("bot_stop")
    await shell(BOT_STOP)
    await asyncio.sleep(float(str(_options(step["restart_bot"]).get("down", 5))))
    await shell(BOT_START)
    ctx.recorder.mark("bot_start")


StepHandler = Callable[[StepContext, dict[str, object]], Awaitable[None]]
STEP_HANDLERS: dict[str, StepHandler] = {
    "send": _send,
    "burst": _burst,
    "sleep": _sleep,
    "wait_reply": _wait_reply,
    "wait_for": _wait_for,
    "set_tool_ask": _set_tool_ask,
    "restart_bot": _restart_bot,
}


async def run_scenario(
    client: TelegramClient, peer: User, scenario: Scenario, nonce: str
) -> dict[str, object]:
    """Run one scenario and return its result: transcript, latencies, violations."""
    t = Transcript(scenario.name)
    if scenario.fresh:
        await client.send_message(peer, "/new")
    settle = Recorder(client, peer, Transcript("settle"), after_id=0)
    handlers = attach(client, peer, settle)
    await wait_until_quiet(settle, QUIET_BEFORE_START_S, QUIET_BEFORE_START_TIMEOUT_S)
    for h in handlers:
        client.remove_event_handler(h)
    latest = await client.get_messages(peer, limit=1)
    recorder = Recorder(client, peer, t, after_id=latest[0].id if latest else 0)
    handlers = attach(client, peer, recorder)
    poller = asyncio.create_task(recorder.poll_forever())
    ctx = StepContext(client, peer, recorder)
    try:
        for step in scenario.steps:
            kind = next(k for k in STEP_HANDLERS if k in step)
            await STEP_HANDLERS[kind](ctx, step)
        await wait_until_quiet(recorder, scenario.settle_s, DEFAULT_REPLY_TIMEOUT_S)
    except StepTimeoutError:
        await wait_until_quiet(recorder, scenario.settle_s, DEFAULT_REPLY_TIMEOUT_S)
    finally:
        for tool in ctx.restored:
            api("PUT", f"/approvals/tools/{tool}", {"ask": None})
        await recorder.refresh_ids([s.id for s in t.sent])
        poller.cancel()
        for h in handlers:
            client.remove_event_handler(h)
        t.ended_at = recorder.now()
    violations = check_invariants(t, scenario.budgets)
    violations += [
        Violation("step_timeout", m.detail)
        for m in t.marks
        if m.kind in {"step_timeout", "reply_timeout"}
    ]
    violations += check_expectations(
        scenario,
        t,
        todos_for(nonce)
        if any(e.kind in {"todos", "approval_numbers"} for e in scenario.expect)
        else [],
        nonce,
    )
    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "passed": not [v for v in violations if v.severity == "fail"],
        "first_response_s": {s.id: _latency(t, s.id) for s in t.sent},
        "violations": [v.__dict__ for v in violations],
        "transcript": t.to_json(),
    }


def _latency(t: Transcript, sent_id: int) -> float | None:
    sent = next(s for s in t.sent if s.id == sent_id)
    times = [m.created_at for m in t.bot_after(sent.sent_at)]
    if sent.first_reaction_at is not None:
        times.append(sent.first_reaction_at)
    return round(min(times) - sent.sent_at, 2) if times else None


def summary_line(result: dict[str, object]) -> str:
    """One human line per scenario, then its violations indented."""
    status = "PASS" if result["passed"] else "FAIL"
    lat = result["first_response_s"]
    latencies = (
        ", ".join(f"{v}s" if v is not None else "-" for v in lat.values())
        if isinstance(lat, dict)
        else ""
    )
    lines = [f"{status}  {result['scenario']}  (first response: {latencies})"]
    violations = result["violations"]
    if isinstance(violations, list):
        lines += [
            f"      [{v['severity']}] {v['invariant']}: {v['message']}  {json.dumps(v['evidence'], ensure_ascii=False)[:300]}"
            for v in violations
        ]
    return "\n".join(lines)


async def main() -> int:
    """Parse arguments, run the chosen scenarios in order, write the reports."""
    parser = argparse.ArgumentParser(
        prog="telegram-edge",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("names", nargs="*", help="scenario names to run (default: all)")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument(
        "--out", type=Path, default=RUNS_DIR / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    args = parser.parse_args()
    nonce = "e" + secrets.token_hex(3)
    scenarios = load_scenarios(nonce)
    if args.list:
        for s in scenarios:
            print(f"{s.name:28} {s.description}")
        return 0
    unknown = set(args.names) - {s.name for s in scenarios}
    if unknown:
        raise SystemExit(f"unknown scenarios: {sorted(unknown)}")
    chosen = [s for s in scenarios if not args.names or s.name in args.names]
    args.out.mkdir(parents=True, exist_ok=True)
    client, peer = await connect()
    results: list[dict[str, object]] = []
    try:
        for s in chosen:
            if s.needs_restart and not (BOT_STOP and BOT_START):
                results.append(
                    {
                        "scenario": s.name,
                        "skipped": "TG_EDGE_BOT_STOP / TG_EDGE_BOT_START not set",
                        "passed": True,
                    }
                )
                print(f"SKIP  {s.name}  (no bot restart commands)", flush=True)
                continue
            result = await run_scenario(client, peer, s, nonce)
            results.append(result)
            print(summary_line(result), flush=True)
            (args.out / "report.json").write_text(
                json.dumps(
                    {"nonce": nonce, "api": API, "results": results}, indent=2, ensure_ascii=False
                )
            )
    finally:
        await client.disconnect()
    text = "\n".join(
        summary_line(r) if "skipped" not in r else f"SKIP  {r['scenario']}  ({r['skipped']})"
        for r in results
    )
    (args.out / "report.txt").write_text(f"nonce {nonce}\n{text}\n")
    print(f"\nreport: {args.out}/report.txt and report.json")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
