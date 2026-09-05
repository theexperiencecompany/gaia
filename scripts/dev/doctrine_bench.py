#!/usr/bin/env python3
"""Prompt-doctrine bench: does the executor prompt make a model choose the right first action?

Runs entirely on free local-client models (`opencode run`) — no billed API needed.
This measures DECISION quality per prompt variant, not tokens/latency: each arm
gets the full executor system prompt (handoff vs activation rewrite) plus a task
and must emit its first tool call as JSON. Token counts in opencode's events
include opencode's own ~21k system overhead, so they are NOT comparable to GAIA
server numbers — only the action choice is scored.

Usage:
    scripts/dev/doctrine_bench.py [--models m1,m2] [--runs N]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "dev"))
sys.path.insert(0, str(REPO / "apps" / "api"))

from agent_bench import SUBAGENT_TASKS  # noqa: E402

#: (label, expected first action). The integration varies per task; only the
#: delegation verb is scored strictly, integration match is a bonus signal.
VARIANTS = ("handoff", "activation")
EXPECTED_ACTION = {"handoff": "handoff", "activation": "activate_integration"}

DEFAULT_MODELS = [
    "opencode/muse-spark-1.3-contributor-free",
    "opencode/ling-3.0-flash-fin-free",
]

INSTRUCTION = """
You are the GAIA executor agent. Rules above. User task below. Think step by step
about which SINGLE tool call to make first, then output ONLY one JSON object
(no prose, no fences): {"action": "<tool name>", "args": {"integration_id": "<id>"}, "why": "<one line>"}.
Available delegation actions: handoff (spawns a provider subagent) or
activate_integration (loads the integration into your own context).
Task: """


def load_prompts() -> dict[str, str]:
    from app.agents.prompts.comms_prompts import EXECUTOR_AGENT_PROMPT
    from app.agents.prompts.executor_activation_prompt import build_activation_executor_prompt

    return {"handoff": EXECUTOR_AGENT_PROMPT, "activation": build_activation_executor_prompt()}


def run_once(model: str, message: str, timeout: int) -> tuple[str, dict]:
    """Run opencode headless; return (assistant text, step_finish tokens)."""
    try:
        proc = subprocess.run(
            ["opencode", "run", "--format", "json", "-m", model, message],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "__TIMEOUT__", {}
    texts: list[str] = []
    usage: dict = {}
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "text":
            texts.append(ev.get("part", {}).get("text", ""))
        elif ev.get("type") == "step_finish":
            usage = ev.get("part", {}).get("tokens", {})
    if proc.returncode != 0 and not texts:
        return f"__ERROR__ {proc.stderr[-300:]}", {}
    return "".join(texts), usage


def extract_action(text: str) -> str:
    """Pull the action name out of a JSON blob (fenced or bare)."""
    m = re.search(r"\{.*?\"action\"\s*:\s*\"([a-zA-Z_]+)\".*?\}", text, re.S)
    return m.group(1) if m else "__unparseable__"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--tasks", default="")
    args = parser.parse_args()

    prompts = load_prompts()
    for name, p in prompts.items():
        print(f"prompt[{name}] chars={len(p)}", flush=True)

    tasks = SUBAGENT_TASKS
    if args.tasks:
        tasks = [SUBAGENT_TASKS[int(i)] for i in args.tasks.split(",")]

    results: dict[str, dict[str, int]] = {}
    for model in args.models.split(","):
        for variant in args.variants.split(","):
            key = f"{model} :: {variant}"
            correct = total = 0
            for _ in range(args.runs):
                for task in tasks:
                    text, _ = run_once(model, prompts[variant] + INSTRUCTION + task, args.timeout)
                    action = extract_action(text)
                    total += 1
                    ok = action == EXPECTED_ACTION[variant]
                    correct += ok
                    print(f"  [{key}] {task[:45]!r} -> {action} {'OK' if ok else 'MISS'}", flush=True)
            results[key] = {"correct": correct, "total": total}

    print("\n=== doctrine score (first-action match) ===")
    for key, r in results.items():
        print(f"{key}: {r['correct']}/{r['total']}")


if __name__ == "__main__":
    main()
