#!/usr/bin/env python3
"""Benchmark a multi-turn agent conversation against a running GAIA API.

Single-turn timings say almost nothing: per-turn cost in a real conversation
ranges over an order of magnitude depending on whether the model happens to
flail, so any A/B read off one run is noise. This drives a fixed script several
times per arm and reports the spread alongside the median.

The metric that actually explains cost is REDUNDANT tool calls — the same tool
invoked with the same arguments twice in one turn. Tokens track
`llm_calls x context_size`, so a loop is what makes a turn expensive, not the
architecture being compared.

Usage (the caller owns the server; flip config and re-run per arm):

    mise dev --agent                       # or boot uvicorn yourself
    scripts/dev/agent_bench.py run --label activation --runs 3
    # ...restart the API with the other configuration...
    scripts/dev/agent_bench.py run --label handoff --runs 3
    scripts/dev/agent_bench.py compare activation handoff

Token totals need LangSmith tracing on (LANGSMITH_TRACING=true) and the
langsmith SDK importable; without it the run still records turns, tools and
latency, and the token column reads "n/a".
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import statistics
import time
from typing import Any
import urllib.request

OUT_DIR = Path(__file__).resolve().parents[2] / ".context" / "bench"

#: A conversation that spans three integrations and, crucially, has follow-up
#: turns that depend on earlier ones — that is where a design that strands
#: information in a subagent shows up as re-fetching.
DEFAULT_SCENARIO = [
    "What's on my calendar today?",
    "Any emails I should deal with before those?",
    "Do I have any open pull requests assigned to me on github?",
    "Draft a reply to that most recent email saying I'll look at it tomorrow morning.",
    "Actually also block 30 minutes tomorrow morning to review that PR.",
    "Ok so summarize everything I need to do today and tomorrow.",
]

#: Light single-integration tasks that fit the server's 300s request cap on
#: slow free-tier models, while still exercising activate/handoff + retrieve.
LIGHT_TASKS = [
    "What is my most recent email? Just the sender and subject.",
    "What's on my calendar today?",
    "Add a todo to my GAIA todo list: buy oat milk tomorrow.",
]

#: Single-shot tasks that force subagent machinery (spawn/activate/retrieve) so
#: one executor-direct call exercises the path without any comms turns. Each
#: keeps its own conversation_id, so runs are independent and order-free.
SUBAGENT_TASKS = [
    "Find the 3 most recent emails about invoices, and for each sender check my calendar for any meeting with them this week. Summarize who owes what and when we next meet.",
    "Look at my open github pull requests, then search my email for any discussion of the oldest one, and draft a status reply.",
    "What are my top 5 largest todos by subtask count? For each, check whether there's a related calendar event this week.",
    "Search my email for the most recent newsletter, pull out the 3 main links, and fetch each page to summarize.",
    "Across calendar, email and github, what needs my attention first tomorrow morning? Rank the top 3 with reasons.",
]

#: Frames the UI emits that are not model tool calls.
_UI_FRAMES = {"tool_calls_data"}


def _post(api: str, body: dict[str, Any], user: str, timeout: int) -> str:
    if not api.startswith(("http://", "https://")):
        raise ValueError(f"--api must be an http(s) URL, got {api!r}")
    req = urllib.request.Request(  # noqa: S310  # scheme validated above; dev tool, local API
        api,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "X-Dev-User": user},
    )
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")  # noqa: S310


#: How far past a tool_name to look for its arguments. A window rather than a
#: consuming match: matching greedily would swallow the next tool_name and
#: silently under-count every call after the first.
_ARGS_WINDOW = 400


def _tool_calls(raw: str) -> list[tuple[str, str]]:
    """(name, args) for each model tool call, in order."""
    calls: list[tuple[str, str]] = []
    for m in re.finditer(r'"tool_name":\s*"([a-zA-Z_]+)"', raw):
        name = m.group(1)
        if name in _UI_FRAMES:
            continue
        window = raw[m.end() : m.end() + _ARGS_WINDOW]
        args = re.search(r'"inputs":\s*(\{(?:[^{}]|\{[^{}]*\})*\})', window)
        calls.append((name, args.group(1) if args else ""))
    return calls


def _redundant(calls: list[tuple[str, str]]) -> int:
    """Calls that repeat an identical (name, args) pair already made this turn."""
    seen: set[tuple[str, str]] = set()
    dupes = 0
    for call in calls:
        if call in seen:
            dupes += 1
        else:
            seen.add(call)
    return dupes


def _reply_text(raw: str) -> str:
    parts = re.findall(r'"response":\s*"((?:[^"\\]|\\.)*)"', raw)
    return "".join(json.loads('"' + p + '"') for p in parts)


def _load_api_env() -> None:
    """Seed LANGSMITH_* from apps/api/.env so the bench needn't export them."""
    import os

    env_path = Path(__file__).resolve().parents[2] / "apps" / "api" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key.startswith("LANGSMITH_"):
            os.environ.setdefault(key, value)


def _resolve_user_id(api: str, user: str, timeout: int) -> str | None:
    """Id of the dev user, so token attribution can exclude other worktrees'
    traces sharing the LangSmith project. /dev/users is find-or-create."""
    try:
        base = api.split("/api/v1/")[0]
        raw = _post(base + "/api/v1/dev/users", {"email": user}, user, timeout)
        return json.loads(raw).get("id")
    except Exception:
        return None


def _tokens_between(start: datetime, end: datetime, user_id: str | None = None) -> int | None:
    """Sum of root-trace tokens in the window, or None when tracing is unavailable.

    Prefers the `langsmith` CLI (no SDK import, works off env auth); falls back
    to the SDK when the CLI is missing.
    """
    import os
    import subprocess

    _load_api_env()
    project = os.environ.get("LANGSMITH_PROJECT")
    if not project:
        return None
    try:
        out = subprocess.run(
            [
                "langsmith",
                "trace",
                "list",
                "--project",
                project,
                "--since",
                start.isoformat(),
                "--format",
                "json",
                "--include-metadata",
                "--limit",
                "100",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if out.returncode == 0 and out.stdout.strip():
            try:
                rows = json.loads(out.stdout)
            except json.JSONDecodeError:
                rows = []
            runs = rows if isinstance(rows, list) else [rows]
            # --since already bounds the window; sum root-trace tokens.
            # Filter to our user's traces: the project is shared across
            # worktrees, and an unfiltered sum once attributed 1.6M mostly
            # foreign tokens to a single email lookup.
            total = 0
            for r in runs:
                if not isinstance(r, dict):
                    continue
                if user_id:
                    md = r.get("custom_metadata") or {}
                    if md.get("user_id") != user_id:
                        continue
                usage = r.get("token_usage") or {}
                total += usage.get("total_tokens") or 0
            return total
    except Exception as exc:  # a metrics backend must never fail the bench
        print(f"  ! langsmith CLI lookup failed ({type(exc).__name__}); trying SDK")
    try:
        from langsmith import Client
    except ImportError:
        return None
    try:
        client = Client()
        roots = [
            r
            for r in client.list_runs(project_name=project, start_time=start, is_root=True)
            if r.start_time.replace(tzinfo=UTC) <= end
        ]
        return sum(r.total_tokens or 0 for r in roots)
    except Exception as exc:  # a metrics backend must never fail the bench
        print(f"  ! token lookup failed ({type(exc).__name__}); reporting n/a")
        return None


def run_executor_once(
    api: str, user: str, task: str, timeout: int, user_id: str | None = None
) -> dict[str, Any]:
    """One executor-direct call (no comms): POST /dev/executor, parse one turn."""
    import uuid

    started = datetime.now(UTC)
    body: dict[str, Any] = {
        "email": user,
        "task": task,
        "conversation_id": uuid.uuid4().hex,
    }
    t0 = time.time()
    try:
        raw = _post(api, body, user, timeout)
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  task FAILED after {elapsed:.1f}s: {type(exc).__name__}", flush=True)
        ended = datetime.now(UTC)
        return {
            "task": task[:60],
            "seconds": round(elapsed, 1),
            "error": f"{type(exc).__name__}",
            "started": started.isoformat(),
            "ended": ended.isoformat(),
            "total_tokens": _tokens_between(started, ended, user_id),
        }
    elapsed = time.time() - t0
    try:
        payload = json.loads(raw)
        reply = payload.get("message", "")
        converged = payload.get("converged", True)
    except json.JSONDecodeError:
        reply, converged = raw, True
    ended = datetime.now(UTC)
    # Executor-direct responses carry no SSE tool frames; count tool mentions in
    # the wide-event-free payload minimally — turns/tools come from LangSmith.
    return {
        "task": task[:60],
        "seconds": round(elapsed, 1),
        "reply_chars": len(reply),
        "converged": converged,
        "started": started.isoformat(),
        "ended": ended.isoformat(),
        "total_tokens": _tokens_between(started, ended, user_id),
    }


def run_once(
    api: str, user: str, scenario: list[str], timeout: int, user_id: str | None = None
) -> dict[str, Any]:
    history: list[dict[str, str]] = []
    conversation_id: str | None = None
    turns: list[dict[str, Any]] = []
    started = datetime.now(UTC)

    for index, prompt in enumerate(scenario, 1):
        body: dict[str, Any] = {
            "message": prompt,
            "messages": [*history, {"role": "user", "content": prompt}],
            "comms_model": "custom",
            "executor_model": "custom",
            "use_default_models": False,
        }
        if conversation_id:
            body["conversation_id"] = conversation_id

        t0 = time.time()
        raw = _post(api, body, user, timeout)
        elapsed = time.time() - t0

        found = re.search(r'"conversation_id":\s*"([^"]+)"', raw)
        if found:
            conversation_id = found.group(1)
        reply = _reply_text(raw)
        history += [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": reply},
        ]

        calls = _tool_calls(raw)
        turns.append(
            {
                "turn": index,
                "seconds": round(elapsed, 1),
                "tool_calls": len(calls),
                "redundant_tool_calls": _redundant(calls),
                "tools": [name for name, _ in calls],
            }
        )
        print(
            f"  turn{index} {elapsed:6.1f}s calls={len(calls):3} "
            f"redundant={turns[-1]['redundant_tool_calls']:2}",
            flush=True,
        )

    ended = datetime.now(UTC)
    return {
        "conversation_id": conversation_id,
        "total_seconds": round(sum(t["seconds"] for t in turns), 1),
        "tool_calls": sum(t["tool_calls"] for t in turns),
        "redundant_tool_calls": sum(t["redundant_tool_calls"] for t in turns),
        "total_tokens": _tokens_between(started, ended, user_id),
        "turns": turns,
    }


def _save(path, args: argparse.Namespace, results: list) -> None:
    path.write_text(
        json.dumps(
            {"label": args.label, "mode": args.mode, "model": args.model, "runs": results},
            indent=1,
        )
    )


def cmd_run(args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{args.label}.json"
    results = []
    user_id = _resolve_user_id(args.api, args.user, args.timeout)
    print(f"[{args.label}] token attribution scoped to user_id={user_id}", flush=True)
    if args.mode == "executor":
        tasks = LIGHT_TASKS if args.suite == "light" else SUBAGENT_TASKS
        for attempt in range(1, args.runs + 1):
            for task in tasks:
                print(f"[{args.label}] run {attempt}/{args.runs} task={task[:50]!r}", flush=True)
                results.append(
                    run_executor_once(args.api, args.user, task, args.timeout, user_id)
                )
                _save(path, args, results)  # crash-safe: every task persisted
    else:
        for attempt in range(1, args.runs + 1):
            print(f"[{args.label}] run {attempt}/{args.runs}", flush=True)
            results.append(
                run_once(args.api, args.user, DEFAULT_SCENARIO, args.timeout, user_id)
            )
        _save(path, args, results)
    print(f"[{args.label}] wrote {path}")


def _summary(label: str) -> dict[str, Any]:
    data = json.loads((OUT_DIR / f"{label}.json").read_text())
    runs = data["runs"]

    def spread(key: str, filt: str | None = None) -> str:
        values = [
            r[key]
            for r in runs
            if r.get(key) is not None and (filt is None or filt in str(r.get("task", "")))
        ]
        if not values:
            return "n/a"
        if len(values) == 1:
            v = values[0]
            return f"{v:,}" if isinstance(v, int) else str(v)
        med = statistics.median(values)
        lo, hi = min(values), max(values)
        if isinstance(med, float):
            return f"{med:.1f} ({lo}-{hi})"
        return f"{int(med):,} ({lo:,}-{hi:,})"

    data_mode = data.get("mode", "chat")
    base: dict[str, Any] = {
        "label": label,
        "runs": len(runs),
        "seconds": spread("total_seconds") if data_mode == "chat" else spread("seconds"),
        "tokens": spread("total_tokens"),
    }
    if data_mode == "chat":
        base["tool_calls"] = spread("tool_calls")
        base["redundant"] = spread("redundant_tool_calls")
    else:
        base["tool_calls"] = "n/a (see LangSmith)"
        base["redundant"] = "n/a (see LangSmith)"
    if data.get("model"):
        base["label"] = f"{label} [{data['model']}]"
    return base


def cmd_compare(args: argparse.Namespace) -> None:
    rows = [_summary(label) for label in args.labels]
    headers = ("arm", "runs", "median seconds", "median tokens", "tool calls", "redundant")
    keys = ("label", "runs", "seconds", "tokens", "tool_calls", "redundant")
    widths = [
        max(len(h), *(len(str(r[k])) for r in rows)) for h, k in zip(headers, keys, strict=True)
    ]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
    for row in rows:
        print("  ".join(str(row[k]).ljust(w) for k, w in zip(keys, widths, strict=True)))
    print("\nMedian with (min-max). A spread wider than the gap between arms means")
    print("the comparison is noise — raise --runs before drawing a conclusion.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    runner = sub.add_parser("run", help="drive the scenario N times and record")
    runner.add_argument("--label", required=True, help="arm name, e.g. activation")
    runner.add_argument("--runs", type=int, default=3)
    runner.add_argument(
        "--mode",
        choices=["chat", "executor"],
        default="chat",
        help="chat = full comms→executor stream; executor = POST /dev/executor directly (no comms)",
    )
    runner.add_argument(
        "--model",
        default="",
        help="bookkeeping only: model id the server is pinned to (server-side config)",
    )
    runner.add_argument("--api", default="http://localhost:8000/api/v1/chat-stream")
    runner.add_argument("--user", default="dev@gaia.local")
    runner.add_argument("--timeout", type=int, default=400)
    runner.add_argument(
        "--suite",
        choices=["light", "heavy"],
        default="heavy",
        help="light = 3 quick single-integration tasks; heavy = 5 multi-integration tasks",
    )
    runner.set_defaults(func=cmd_run)

    comparer = sub.add_parser("compare", help="print a table across recorded arms")
    comparer.add_argument("labels", nargs="+")
    comparer.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
