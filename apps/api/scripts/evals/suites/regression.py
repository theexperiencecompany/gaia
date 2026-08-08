"""Regression gate suite — free, deterministic, stub-driven.

Drives the REAL executor graph in GAIA_SIM_MODE against the scripted LLM stub
(tools/llm-stub), so tool flow/streaming/scoring plumbing is verified without
spending a cent. The stub server is spawned on demand (LLM_STUB_PORT).
Cases use scripted directives: [[tool:name {...}]] and [[say:...]].
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import time
from typing import Any

import httpx

from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.providers import EvalConfig
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.types import Case, CaseRun

_REPO_ROOT = Path(__file__).resolve().parents[4]
STUB_PORT = int(os.environ.get("LLM_STUB_PORT", "9797"))
STUB_URL = f"http://localhost:{STUB_PORT}/api/v1"

_STUB_PROCESS: subprocess.Popen | None = None
_GRAPH_CACHE: dict[str, Any] = {}


def ensure_stub() -> None:
    global _STUB_PROCESS
    try:
        r = httpx.get(f"{STUB_URL}/health", timeout=2.0)
        if r.status_code < 500:
            return
    except httpx.HTTPError:
        pass
    _STUB_PROCESS = subprocess.Popen(
        ["uv", "run", "tools/llm-stub/server.py"],
        cwd=_REPO_ROOT,
        env={**os.environ, "LLM_STUB_PORT": str(STUB_PORT)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            r = httpx.get(f"{STUB_URL}/health", timeout=2.0)
            if r.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit("llm-stub server failed to start")


def _sim_graph_builder():
    from app.agents.core.graph_builder.build_graph import build_executor_graph
    from app.agents.llm.client import init_llm, register_llm_providers

    register_llm_providers()
    return build_executor_graph(chat_llm=init_llm(preferred_provider="custom"))


async def _ensure_registered() -> None:
    """Register the app's lazy providers + services the executor graph needs."""
    from app.core.provider_registration import register_lazy_providers
    from app.db.redis import redis_cache
    from app.helpers.lifespan_helpers import init_mongodb_async

    register_lazy_providers("arq_worker")
    await asyncio.gather(init_mongodb_async(), redis_cache.verify_connection())


@register_suite("regression")
class RegressionSuite(Suite):
    name = "regression"
    project = "gaia-capability"
    label = "Regression gate"

    def __init__(self, cfg: EvalConfig) -> None:
        self.cfg = cfg
        self._cases: list[Case] | None = None

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        if self._cases is not None:
            return self._cases
        cases = [
            Case(
                id="reg-todo-create",
                ticket="Scripted create_todo through the real executor graph.",
                prompt='[[tool:create_todo {"title":"Buy milk"}]]\n[[say:Created it.]]',
                expected={
                    "category": "todos",
                    "tool_calls": [{"tool": "create_todo", "args": "name-only"}],
                    "communicate": ["Created"],
                    "score": {"gates": ["communicate", "tool_call_correctness"]},
                },
                tags=["regression"],
            ),
            Case(
                id="reg-todo-list",
                ticket="Scripted list_todos.",
                prompt="[[tool:list_todos {}]]\n[[say:Here they are.]]",
                expected={
                    "category": "todos",
                    "tool_calls": [{"tool": "list_todos"}],
                    "communicate": ["Here"],
                    "score": {"gates": ["communicate", "tool_call_correctness"]},
                },
                tags=["regression"],
            ),
            Case(
                id="reg-plain-reply",
                ticket="Scripted plain reply, no tools.",
                prompt="[[say:All good.]]",
                expected={
                    "category": "chat",
                    "tool_calls": [],
                    "communicate": ["All good"],
                    "score": {"gates": ["communicate"]},
                },
                tags=["regression"],
            ),
            Case(
                id="reg-web-search",
                ticket="Scripted web search binding.",
                prompt='[[tool:web_search_tool {"query":"eiffel tower"}]]\n[[say:Found it.]]',
                expected={
                    "category": "search",
                    "tool_calls": [{"tool": "web_search_tool"}],
                    "communicate": ["Found"],
                    "score": {"gates": ["communicate", "tool_call_correctness"]},
                },
                tags=["regression"],
            ),
            Case(
                id="reg-tracked-todo",
                ticket="Scripted tracked todo canvas tool.",
                prompt='[[tool:create_tracked_todo {"title":"Q3 plan","purpose":"planning"}]]\n[[say:Tracked.]]',
                expected={
                    "category": "tracked_todos",
                    "tool_calls": [{"tool": "create_tracked_todo"}],
                    "communicate": ["Tracked"],
                    "score": {"gates": ["communicate", "tool_call_correctness"]},
                },
                tags=["regression"],
            ),
        ]
        self._cases = cases
        return cases

    def transport(self, case: Case, cfg: EvalConfig, tracker: EvalCostTracker, provider):
        del cfg
        return self._run_graph(case, tracker, provider)

    async def _run_graph(self, case: Case, tracker: EvalCostTracker, provider) -> CaseRun:
        from langchain_core.messages import HumanMessage

        from app.config.settings import settings

        if not settings.GAIA_SIM_MODE:
            return CaseRun(
                case_id=case.id,
                provider=provider.name,
                model=provider.model,
                error="regression suite requires --sim (GAIA_SIM_MODE)",
            )
        ensure_stub()
        await _ensure_registered()
        config = {
            "configurable": {"thread_id": f"reg-{case.id}", "user_id": "reg-user"},
            "metadata": {"user_id": "reg-user"},
            "callbacks": [tracker],
        }
        messages: list[dict[str, str]] = []
        tool_calls: list[dict[str, Any]] = []
        try:
            async with _sim_graph_builder() as graph:
                async for event in graph.astream(
                    {"messages": [HumanMessage(content=case.prompt)]},
                    config=config,
                    stream_mode="updates",
                ):
                    for node, payload in event.items():
                        for msg in payload.get("messages", []) if isinstance(payload, dict) else []:
                            content = getattr(msg, "content", None)
                            msg_type = getattr(msg, "type", "?")
                            role = (
                                "assistant"
                                if msg_type == "ai"
                                else "human"
                                if msg_type == "human"
                                else msg_type
                            )
                            if content:
                                messages.append({"role": role, "content": str(content)})
                            for call in getattr(msg, "tool_calls", []) or []:
                                tool_calls.append(
                                    {"name": call.get("name", ""), "args": call.get("args", {})}
                                )
            text = " ".join(m.get("content", "") for m in messages if m.get("role") == "assistant")
        except Exception as e:
            return CaseRun(
                case_id=case.id,
                provider=provider.name,
                model=provider.model,
                messages=messages,
                tool_calls=tool_calls,
                text="",
                error=f"{type(e).__name__}: {e}",
            )
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=messages,
            tool_calls=tool_calls,
            text=text,
            tokens_in=tracker.input_tokens.get(provider.name, 0),
            tokens_out=tracker.output_tokens.get(provider.name, 0),
        )

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        from scripts.evals.core.scorers import CommunicateGate, ToolCallCorrectness

        scores: dict[str, float] = {}
        if case.expected.get("communicate"):
            scores["communicate"] = (
                CommunicateGate()
                .score(output=run.text, messages=run.messages, expected=case.expected)
                .value
            )
        scores["tool_call_correctness"] = (
            ToolCallCorrectness()
            .score(output=run.text, tool_calls=run.tool_calls, expected=case.expected)
            .value
        )
        return scores

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        del cfg
        from scripts.evals.core.scorers import CommunicateGate, ProviderQuality, ToolCallCorrectness

        return [CommunicateGate(), ToolCallCorrectness(), ProviderQuality()]
