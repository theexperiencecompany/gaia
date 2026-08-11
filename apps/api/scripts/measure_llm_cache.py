"""Live prompt-cache measurement harness.

Ground-truth measurement of GAIA's prompt-cache hit rate against the REAL
provider lane (OpenRouter -> deepseek/deepseek-v4-flash-0731, the production
default). Instead of estimating from token counts or assuming cache semantics,
this script replays realistic per-turn prompt shapes through the REAL message
pipeline (``manage_system_prompts_node`` + the real static/dynamic/time
builders) and reads the provider's own usage report (``cache_read``) after
every call.

Scenario comparison, all with identical conversation bytes and identical
per-turn churn:

- ``current``  — the layout the graph produces today: volatile system slots
  (todo_context, executor status, memory_recall) BETWEEN the stable prefix and
  the conversation history.
- ``tail``     — the proposed layout: volatile slots moved AFTER the whole
  conversation, so the byte-stable ``[static, dynamic_stable, ...history]``
  prefix survives turn-to-turn and the provider's prefix cache covers the
  conversation.
- ``control``  — no volatile slots at all (provider ceiling; never realistic).

Also verifies SEMANTICS of the tail layout: a hidden directive is embedded in
the tail system message and the model's reply must obey it — proving the
provider still applies system messages that appear after the conversation.

Run: ``uv run python scripts/measure_llm_cache.py [--scenario current|tail|control|all] [--turns N]``
from ``apps/api``. Uses the production OpenRouter key (real spend, ~$0.01 per
full run). ``--smoke`` prints the raw usage shape the lane reports so metering
accuracy can be audited.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.agents.llm.client import get_default_llm
from app.agents.templates.agent_template import get_comms_static_prompt
from app.helpers.message_helpers import MEMORY_RECALL_MARKER, build_current_time_message

# Markers must match the real node's detection (additional_kwargs).
TODO_MARKER = "todo_context"
EXEC_STATUS_MARKER = "executor_status"
DYNAMIC_MARKER = "dynamic_context"

# A hidden directive embedded in the volatile tail slot. If the model obeys it,
# the provider applied the tail system message (semantics preserved).
TAIL_PROBE = "ALWAYS END YOUR REPLY WITH THE SINGLE WORD: CELESTE."


def _user_turn(n: int) -> HumanMessage:
    topics = [
        "Can you summarize my inbox for today and flag anything urgent?",
        "What's on my calendar this week? Any conflicts?",
        "Please draft a reply to Sarah declining the meeting invite politely.",
        "Remind me to call the dentist tomorrow at 3pm.",
        "Did my GitHub PR get merged? Check the status.",
        "Set up a weekly review with the design team every Monday at 10.",
        "Look at my expenses for last month and categorize them.",
        "Find the notes I took about the product roadmap in March.",
        "What did we decide about the new onboarding flow?",
        "Send a thank-you note to the vendor for the samples.",
    ]
    return HumanMessage(content=topics[n % len(topics)])


def _assistant_turn(n: int) -> AIMessage:
    bodies = [
        (
            "Here's your inbox summary for today. Three items need attention: "
            "the Q3 budget draft from finance (due Friday), Sarah's meeting "
            "request for Thursday, and a vendor contract renewal. I'd flag the "
            "budget as the only true urgent item — the other two can wait until "
            "tomorrow. Want me to draft responses for any of them?"
        ),
        (
            "Your calendar this week has 14 events. Thursday is the busiest: "
            "back-to-back from 9am to 4pm with the quarterly planning session "
            "and the design review. There is one conflict I noticed — the vendor "
            "demo at 2pm overlaps your 1:45pm 1:1 with Priya. I can move the "
            "1:1 to Friday morning if you'd like."
        ),
        (
            "Here's a draft reply for Sarah:\n\n'Hi Sarah, thanks for the "
            "invite — unfortunately I have a conflict on Thursday and won't be "
            "able to make it. I hope it goes well! Best, [Your name]'\n\n"
            "Want me to adjust the tone, or send it as-is?"
        ),
        (
            "Done — I've set a reminder for tomorrow at 3pm to call the "
            "dentist. I'll ping you 10 minutes before as well so you have time "
            "to wrap up whatever you're doing. Anything else you'd like to "
            "schedule while I'm at it?"
        ),
        (
            "I checked the PR status: your branch was merged into master about "
            "an hour ago, and the deploy to staging is in progress. CI passed "
            "with all checks green. Nothing needs your attention right now."
        ),
        (
            "I've created a recurring calendar event — 'Weekly review with "
            "design team' every Monday at 10am, starting next week. I invited "
            "the design team members from your contacts. Want me to add a "
            "notion doc link to the invite?"
        ),
        (
            "Here's the expense breakdown for last month: dining out is your "
            "biggest category at $412 (up 18% from the month before), followed "
            "by transportation at $238 and software subscriptions at $156. "
            "Overall you spent 6% more than the previous month. The dining "
            "trend might be worth a look."
        ),
        (
            "I found your roadmap notes from March. The key decisions were: "
            "onboarding flow gets simplified to 3 steps, the mobile app ships "
            "before the desktop refresh, and the analytics dashboard is "
            "deferred to Q4. There's also a note about revisiting the pricing "
            "page in June — that may be the next item on your list."
        ),
        (
            "From the conversation history: we decided on the new onboarding "
            "flow that it should be 3 steps max, use the open-ended preference "
            "questions instead of the checkbox grid, and that the 'profession' "
            "field is optional. You also wanted a progress indicator on every "
            "step. The implementation is tracked in the onboarding epic."
        ),
        (
            "I've sent the thank-you note to the vendor. I kept it brief — "
            "mentioned the samples arrived in great condition and that we're "
            "excited to evaluate them. Let me know if you want to add anything "
            "specific before they reply."
        ),
    ]
    return AIMessage(content=bodies[n % len(bodies)])


def _tool_result(n: int) -> tuple[AIMessage, ToolMessage]:
    call_id = f"call_{n}"
    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_emails",
                "args": {"query": f"priority flagging batch {n % 3}", "limit": 10},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )
    bodies = [
        (
            '{"results": [{"id": "e1", "from": "finance@corp.com", "subject": '
            '"Q3 budget draft for review", "preview": "Attached is the draft '
            "budget for Q3. Please review the marketing line items and return "
            'comments by Friday."}, {"id": "e2", "from": "sarah@corp.com", '
            '"subject": "Meeting invite — Thursday", "preview": "Hi! Would you '
            'be free Thursday afternoon to review the new vendor proposal?"}]}'
        ),
        (
            '{"events": [{"title": "Quarterly planning", "start": "09:00", '
            '"end": "11:00"}, {"title": "Design review", "start": "11:30", '
            '"end": "12:30"}, {"title": "Vendor demo", "start": "14:00", '
            '"end": "15:00"}, {"title": "1:1 with Priya", "start": "13:45", '
            '"end": "14:15"}]}'
        ),
        (
            '{"status": "merged", "branch": "feat/onboarding-revamp", '
            '"checks": {"lint": "passed", "type-check": "passed", "tests": '
            '"passed"}, "deploy": "staging in progress"}'
        ),
    ]
    return ai, ToolMessage(content=bodies[n % len(bodies)], tool_call_id=call_id)


def _big_tool_result(n: int) -> tuple[AIMessage, ToolMessage]:
    """A tool turn with a production-sized result: thousands of tokens of
    JSON (email listings, file listings, search hits). This is what makes
    real conversations large — and what the current layout re-sends uncached
    on every turn."""
    call_id = f"bigcall_{n}"
    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_emails",
                "args": {"query": f"bulk folder scan {n}", "limit": 50},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )
    # ~5k tokens of realistic JSON-ish listing
    rows = []
    for i in range(60):
        rows.append(
            f'{{"id": "msg_{n}_{i}", "from": "contact{i % 12}@corp.com", '
            f'"subject": "Update on project delta iteration {i % 5} — action '
            f'items and next steps for the team", "preview": "Hi team, please '
            f"review the attached notes from the sync. Key decisions: proceed "
            f"with the phased rollout, keep the legacy endpoint for two more "
            f"weeks, and freeze new feature requests until the migration "
            f'completes. Next steps are listed below.", "date": "2026-08-{1 + i % 28:02d}"}}'
        )
    return ai, ToolMessage(content='{"results": [' + ",\n".join(rows) + "]}", tool_call_id=call_id)


def _memory_recall(n: int) -> SystemMessage:
    """Volatile per-turn recall content that churns between turns."""
    memories = [
        "Based on our previous conversations: you started the quarterly planning project (Mar 12). You prefer concise bullet summaries over prose. You mentioned disliking early morning meetings.",
        "Based on our previous conversations: the vendor contract renewal deadline is June 30. You asked to keep all contract reviews within the family budget category. You use the desktop app most mornings.",
        "Based on our previous conversations: Sarah from the design team is your main contact there. You agreed to review the onboarding flow mockups this week. You prefer async updates over calls.",
        "Based on our previous conversations: the dentist appointment reminder pattern is set. You track expenses monthly with the finance notebook. You asked to be notified about PR merges after 5pm.",
    ]
    knowledge = (
        "About Gaia: GAIA is a proactive personal assistant that can manage "
        "email, calendar, reminders, todos, and integrations. It runs tasks in "
        "a sandboxed workspace and can read/write files there."
    )
    todos = (
        "Active tracked todos: (1) Review Q3 budget [id: t_1] — in progress; "
        "(2) Follow up with vendor on samples [id: t_2] — waiting; (3) Prepare "
        "onboarding retro notes [id: t_3] — pending."
    )
    return SystemMessage(
        content=(
            f"{memories[n % len(memories)]}\n\n{knowledge}\n\n{todos}\n\n"
            f"[Turn-context note: {n}]\n{TAIL_PROBE}"
        ),
        additional_kwargs={MEMORY_RECALL_MARKER: True},
    )


def _todo_context(n: int) -> SystemMessage:
    return SystemMessage(
        content=(
            "Current task tracking:\n"
            f"- t_1: Review Q3 budget (in progress, step {n})\n"
            "- t_2: Follow up with vendor (waiting)\n"
            "- t_3: Onboarding retro notes (pending)"
        ),
        additional_kwargs={TODO_MARKER: True},
    )


def _executor_status(n: int) -> SystemMessage:
    return SystemMessage(
        content=(
            "A background task you dispatched is STILL RUNNING right now "
            f"(task_id: bg_{n % 2}). Its results have not arrived yet — do not "
            "claim it finished."
        ),
        additional_kwargs={EXEC_STATUS_MARKER: True},
    )


def _dynamic_stable(seed: str) -> SystemMessage:
    return SystemMessage(
        content=(
            f"Session fingerprint: {seed}\n"
            "User Name: Alex Rivera\n"
            "User Timezone: America/Los_Angeles\n"
            "User Preferences:\n"
            "- Tone: concise, direct, bullet points preferred\n"
            "- Response style: summarize first, details on request\n"
            "Connected integrations (hand off to the matching subagent to use them):\n"
            "- Gmail (gmail)\n- Google Calendar (google_calendar)\n"
            "- GitHub (github)\n- Notion (notion)"
        ),
        additional_kwargs={DYNAMIC_MARKER: True, "memory_message": True},
    )


def _time_message() -> HumanMessage:
    return build_current_time_message(user_timezone="America/Los_Angeles")


def _run_config(provider: str) -> RunnableConfig:
    return RunnableConfig(configurable={"provider": provider, "thread_id": "cache-probe-thread"})


def _call_config(provider: str) -> dict[str, Any]:
    return {"configurable": {"provider": provider}}


def run_node(messages: list[AnyMessage], provider: str) -> list[AnyMessage]:
    """Run the REAL manage_system_prompts_node on the bag (the graph's pre-model hook)."""
    out = manage_system_prompts_node({"messages": messages}, _run_config(provider), None)
    return out["messages"]


class TurnStats:
    def __init__(self, turn: int) -> None:
        self.turn = turn
        self.input = 0
        self.cached = 0
        self.output = 0


def _search_emails(query: str, limit: int = 10) -> str:
    """Search the user's inbox. Returns matching emails."""
    return f"results for {query} (limit {limit})"


def _add_calendar_event(title: str) -> str:
    """Add an event to the user's calendar."""
    return f"event added: {title}"


def _set_reminder(what: str, when: str) -> str:
    """Set a reminder for the user."""
    return f"reminder set: {what} at {when}"


async def run_scenario(
    provider: str,
    tail_volatile: bool,
    turns: int,
    seed: str,
) -> tuple[list[TurnStats], str]:
    """Run one scenario: ``turns`` sequential model calls, growing history.

    ``tail_volatile=False`` reproduces the pre-fix layout: the node's provider
    is forced to ``gemini`` (outside ``TAIL_VOLATILE_PROVIDERS``), which keeps
    the leading-block layout, while the model call itself still goes to the
    same OpenAI-wire lane. ``True`` uses the real openrouter path (tail
    layout). ``seed`` randomizes the conversation bytes so each scenario-run
    only ever sees its own cache writes (the provider's cache is global and
    persists across processes). Returns per-turn stats and the model's final
    reply (semantics probe).
    """
    node_provider = "gemini" if not tail_volatile else provider
    llm = get_default_llm(temperature=0.0)
    # A small fixed tool set, mirroring the comms agent's stable bind prefix.
    tools = [
        tool(_search_emails),
        tool(_add_calendar_event),
        tool(_set_reminder),
    ]
    bound = llm.bind_tools(tools)

    history: list[AnyMessage] = []
    stats: list[TurnStats] = []
    final_reply = ""
    for turn in range(turns):
        # The graph's per-turn message bag: fresh slot messages + append-only
        # history + the user's new turn. The node reshapes it into the
        # per-call layout; the time message lands at the very end.
        volatile: list[SystemMessage] = []
        if turn >= 1:
            volatile.append(_todo_context(turn))
            if turn % 2 == 1:
                volatile.append(_executor_status(turn))
        volatile.append(_memory_recall(turn))

        user_msg = _user_turn(turn)
        bag = [
            SystemMessage(content=get_comms_static_prompt("web")),
            _dynamic_stable(seed),
            *volatile,
            *history,
            user_msg,
            _time_message(),
        ]
        shaped = run_node(bag, node_provider)

        resp = await bound.ainvoke(shaped, config=_call_config(provider))
        usage = getattr(resp, "usage_metadata", None) or {}
        st = TurnStats(turn)
        st.input = int(usage.get("input_tokens") or 0)
        st.output = int(usage.get("output_tokens") or 0)
        details = usage.get("input_token_details") or {}
        st.cached = int(details.get("cache_read") or 0)
        stats.append(st)

        # Grow history exactly like a real conversation (big tool turn every 4th).
        history.append(user_msg)
        if turn % 4 == 3:
            ai, tm = _big_tool_result(turn)
            history.extend([ai, tm])
        else:
            history.append(_assistant_turn(turn))

    # --- semantics probe: ask directly for the word embedded in the tail ---
    probe_bag = [
        SystemMessage(content=get_comms_static_prompt("web")),
        _dynamic_stable("probe"),
        _memory_recall(999),
        *history,
        HumanMessage(
            content="What single word should you end your replies with? Reply with only that word."
        ),
        _time_message(),
    ]
    shaped = run_node(probe_bag, node_provider)
    resp = await bound.ainvoke(shaped, config=_call_config(provider))
    final_reply = str(resp.content)

    return stats, final_reply


def report(name: str, stats: list[TurnStats]) -> None:
    print(f"\n=== {name} ===")
    print(f"{'turn':>5} {'input':>8} {'cached':>8} {'hit%':>7} {'out':>7}")
    tot_in = tot_c = tot_out = 0
    for st in stats:
        hit = st.cached / st.input * 100 if st.input else 0.0
        tot_in += st.input
        tot_c += st.cached
        tot_out += st.output
        print(f"{st.turn:>5} {st.input:>8} {st.cached:>8} {hit:>6.1f}% {st.output:>7}")
    hit = tot_c / tot_in * 100 if tot_in else 0.0
    # deepseek-v4-flash-0731 seeded pricing ($/1k)
    in_price, cached_price, out_price = 0.00009, 0.000018, 0.00018
    cost = (
        (tot_in - tot_c) / 1000 * in_price
        + tot_c / 1000 * cached_price
        + tot_out / 1000 * out_price
    )
    cost_no_cache = tot_in / 1000 * in_price + tot_out / 1000 * out_price
    print(
        f"TOTAL  {tot_in:>8} {tot_c:>8} {hit:>6.1f}% {tot_out:>7}\n"
        f"  input cost (actual): ${cost:.5f}   "
        f"(if 0% cached: ${cost_no_cache:.5f})   "
        f"total-cost reduction vs 0% cache: {100 * (1 - cost / cost_no_cache):.1f}%"
    )


async def smoke() -> None:
    """Print the raw usage shape the lane reports for one call."""
    llm = get_default_llm(temperature=0.0)
    resp = await llm.ainvoke(
        [HumanMessage(content="Reply with the single word: pong")],
        config=_call_config("openrouter"),
    )
    print("usage_metadata:", resp.usage_metadata)
    print("response_metadata usage:", (resp.response_metadata or {}).get("usage"))
    print("reply:", resp.content)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="all", choices=["current", "tail", "control", "all"])
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument("--dump-shapes", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--provider", default="openrouter")
    args = parser.parse_args()

    if args.smoke:
        await smoke()
        return

    if args.dump_shapes:
        # Debug: print the exact per-call shapes the harness produces.
        history: list[AnyMessage] = []
        seed = "dump"
        for turn in range(2):
            volatile = [_memory_recall(turn)]
            if turn >= 1:
                volatile = [_todo_context(turn), _executor_status(turn), _memory_recall(turn)]
            user = _user_turn(turn)
            bag = [
                SystemMessage(content=get_comms_static_prompt("web")),
                _dynamic_stable(seed),
                *volatile,
                *history,
                user,
                _time_message(),
            ]
            shaped = run_node(bag, args.provider)
            print(f"--- turn {turn} ({len(shaped)} msgs) ---")
            for m in shaped:
                extra = {k: v for k, v in m.additional_kwargs.items() if v}
                print(f"  [{m.type}] {extra} len={len(str(m.content))}: {str(m.content)[:60]!r}")
            history.extend([user, _assistant_turn(turn)])
        print("static prompt chars:", len(get_comms_static_prompt("web")))
        return

    if args.scenario in ("current", "all"):
        seed = secrets.token_hex(8)
        stats, reply = await run_scenario(args.provider, False, args.turns, seed)
        report(f"current (volatile before conversation) [seed {seed}]", stats)
        print(
            "  semantics probe:",
            "PASS (tail applied)" if "CELESTE" in reply.upper() else f"FAIL — {reply[:100]!r}",
        )

    if args.scenario in ("tail", "all"):
        seed = secrets.token_hex(8)
        stats, reply = await run_scenario(args.provider, True, args.turns, seed)
        report(f"tail (volatile after conversation) [seed {seed}]", stats)
        print(
            "  semantics probe:",
            "PASS (tail applied)" if "CELESTE" in reply.upper() else f"FAIL — {reply[:100]!r}",
        )

    if args.scenario == "control":
        # No volatile slots at all — provider ceiling.
        seed = secrets.token_hex(8)
        llm = get_default_llm(temperature=0.0)
        history: list[AnyMessage] = []
        stats: list[TurnStats] = []
        for turn in range(args.turns):
            user_msg = _user_turn(turn)
            bag = [
                SystemMessage(content=get_comms_static_prompt("web")),
                _dynamic_stable(seed),
                *history,
                user_msg,
                _time_message(),
            ]
            shaped = run_node(bag, args.provider)
            resp = await llm.ainvoke(shaped, config=_call_config(args.provider))
            usage = getattr(resp, "usage_metadata", None) or {}
            st = TurnStats(turn)
            st.input = int(usage.get("input_tokens") or 0)
            st.output = int(usage.get("output_tokens") or 0)
            st.cached = int((usage.get("input_token_details") or {}).get("cache_read") or 0)
            stats.append(st)
            history.extend([user_msg, _assistant_turn(turn)])
        report("control (no volatile slots)", stats)


if __name__ == "__main__":
    asyncio.run(main())
