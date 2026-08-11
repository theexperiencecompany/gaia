"""Probe the provider's prompt-cache semantics with controlled prefixes.

Answers, empirically, against the REAL lane (OpenRouter -> DeepSeek):
1. Does a stable prefix P hit cache when the suffix changes?
2. Does a 1-byte change at the END of P bust the whole prefix?
3. Does a 1-byte change at the START of P bust the whole prefix?
4. Do tool definitions participate in the cache prefix?
5. What's the cache granularity (block size)?

Run: uv run python scripts/probe_cache_semantics.py
"""

from __future__ import annotations

import asyncio
import secrets

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.agents.llm.client import get_default_llm

PREFIX_TOKENS = 800  # ~0.75 char/token for this text


def _make_prefix(seed: str, tokens: int = PREFIX_TOKENS) -> str:
    """Deterministic, unique, realistic prose block of ~`tokens` tokens."""
    base = (
        "The observatory records atmospheric conditions across the western "
        "ridge every fifteen minutes, logging temperature, humidity, wind "
        "speed, and barometric pressure into a rolling archive that spans "
        "fourteen years. Researchers use this archive to correlate seasonal "
        "patterns with crop yields in the valley below, and the correlation "
        "has proven strong enough that local farmers now plan planting "
        "schedules from the published weekly summaries. "
    )
    base_tokens = len(base) // 4  # ~4 chars/token for prose
    repeat = max(1, tokens // base_tokens)
    block = (base * repeat)[: tokens * 4]
    return f"[PREFIX {seed}]\n{block}"


def _question(n: int) -> str:
    return f"Question {n}: ignoring the prefix above, reply with exactly the word ANSWER{n}."


def _probe_a(_q: str) -> str:
    """Tool A for the probe (schema only — the body never runs)."""
    return "r"


def _probe_b(_q: str) -> str:
    """Tool B for the probe (schema only — the body never runs)."""
    return "r"


async def main() -> None:
    llm = get_default_llm(temperature=0.0)
    seed = secrets.token_hex(8)
    P = _make_prefix(seed)

    async def call(label: str, messages: list[HumanMessage], tools: list | None = None) -> None:
        runnable = llm.bind_tools(tools) if tools else llm
        resp = await runnable.ainvoke(messages)
        u = getattr(resp, "usage_metadata", None) or {}
        details = u.get("input_token_details") or {}
        inp = int(u.get("input_tokens") or 0)
        cached = int(details.get("cache_read") or 0)
        created = int(details.get("cache_creation") or 0)
        print(
            f"  {label:<46} input={inp:>6} cached={cached:>6} "
            f"({100 * cached / max(inp, 1):5.1f}%) created={created}"
        )

    tools = [tool(_probe_a), tool(_probe_b)]

    print(f"prefix seed={seed} (~{PREFIX_TOKENS} tokens)")
    print("1. cold start (cache write)")
    await call("R1: [P, q1] cold", [HumanMessage(content=P + "\n" + _question(1))])
    print("2. stable prefix, new suffix")
    await call("R2: [P, q2] stable prefix", [HumanMessage(content=P + "\n" + _question(2))])
    await call("R3: [P, q3] stable prefix", [HumanMessage(content=P + "\n" + _question(3))])
    print("3. 1-byte change at END of prefix")
    await call(
        "R4: [P+'.', q4] tail byte change",
        [HumanMessage(content=P + "." + "\n" + _question(4))],
    )
    await call(
        "R5: [P, q5] back to exact prefix",
        [HumanMessage(content=P + "\n" + _question(5))],
    )
    print("4. 1-byte change at START of prefix")
    await call(
        "R6: ['.'+P, q6] head byte change",
        [HumanMessage(content="." + P + "\n" + _question(6))],
    )
    await call(
        "R7: [P, q7] back to exact prefix",
        [HumanMessage(content=P + "\n" + _question(7))],
    )
    print("5. tools participation")
    await call(
        "R8: [P, q8] WITH tools (same P)",
        [HumanMessage(content=P + "\n" + _question(8))],
        tools=tools,
    )
    await call(
        "R9: [P, q9] WITH tools again",
        [HumanMessage(content=P + "\n" + _question(9))],
        tools=tools,
    )
    await call(
        "R10: [P, q10] WITHOUT tools",
        [HumanMessage(content=P + "\n" + _question(10))],
    )
    print("6. system-vs-user placement")
    from langchain_core.messages import SystemMessage

    await call(
        "R11: [sys(P), user(q11)]",
        [SystemMessage(content=P), HumanMessage(content=_question(11))],
    )
    await call(
        "R12: [user(q12), sys(P)] tail system",
        [HumanMessage(content=_question(12)), SystemMessage(content=P)],
    )
    await call(
        "R13: [user(q13), sys(P)] again",
        [HumanMessage(content=_question(13)), SystemMessage(content=P)],
    )


if __name__ == "__main__":
    asyncio.run(main())
