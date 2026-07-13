"""Runnable inbox-triage demo for the weak-model harness improvements.

Drives the REAL executor loop (create_agent + LoopGuardMiddleware, with
require_finish_to_end and the duplicate-call guard active) over a scripted inbox,
so no connected Gmail account is needed.

Model selection, in priority order:
  1. OPENROUTER_API_KEY set  -> real gpt-oss-120b:free via OpenRouter (the actual
     weak target model). This is the "real LLM" path; it needs only the key.
  2. otherwise               -> a scripted BindableToolsFakeModel that reproduces
     the exact failure this harness fixes: a weak model that tries to quit after
     one lookup, then (after the harness nudge) actually finishes the triage.

Run:  cd apps/api && uv run python scripts/harness_triage_demo.py
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

os.environ.setdefault("ENV", "development")
# Dummy settings so importing the app package (which loads settings + the mongo
# collection module) succeeds without real infra. Mirrors tests/conftest.py; no
# DB is actually contacted by this demo. gitleaks-safe placeholders.
os.environ.setdefault(
    "MONGO_DB", "mongodb://localhost:27017/gaia_demo?serverSelectionTimeoutMS=100"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("WORKOS_API_KEY", "sk_test_fake")  # noqa: S105
os.environ.setdefault("WORKOS_CLIENT_ID", "client_fake")
os.environ.setdefault("WORKOS_COOKIE_PASSWORD", "a" * 32)
os.environ.setdefault("MCP_ENCRYPTION_KEY", "dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9ieXRlcw==")  # noqa: S105
os.environ.setdefault("AGENT_SECRET", "demo-agent-secret-" + "x" * 32)  # noqa: S105
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.store.memory import InMemoryStore  # noqa: E402

from app.agents.middleware.loop_guard import LoopGuardMiddleware  # noqa: E402
from app.constants.llm import COMPLETION_NUDGE_MESSAGE  # noqa: E402
from app.override.langgraph_bigtool.create_agent import create_agent  # noqa: E402

# --- scripted inbox -------------------------------------------------------------

INBOX: dict[str, dict] = {
    "e1": {"from": "promotions@shopmart.com", "subject": "50% OFF everything!", "unread": True},
    "e2": {"from": "hr@acme.com", "subject": "Offer letter - please sign by Fri", "unread": True},
    "e3": {"from": "newsletter@medium.com", "subject": "Your weekly digest", "unread": True},
    "e4": {"from": "billing@aws.com", "subject": "URGENT: payment failed", "unread": True},
    "e5": {"from": "deals@travelnow.com", "subject": "Last-minute flight deals", "unread": True},
}
ARCHIVED: set[str] = set()
LABELS: dict[str, list[str]] = {}


@tool
def gmail_search(query: str) -> str:
    """Search the inbox. Matches sender or subject; returns id, from, subject."""
    q = query.lower()
    hits = [
        f"{eid} | {e['from']} | {e['subject']}"
        for eid, e in INBOX.items()
        if eid not in ARCHIVED and (q in e["from"].lower() or q in e["subject"].lower() or q == "")
    ]
    return "\n".join(hits) if hits else "no matches"


@tool
def gmail_archive(email_id: str) -> str:
    """Archive an email by id (reversible)."""
    if email_id not in INBOX:
        return f"error: no such email {email_id}"
    ARCHIVED.add(email_id)
    return f"archived {email_id}"


@tool
def gmail_label(email_id: str, label: str) -> str:
    """Add a label to an email by id."""
    if email_id not in INBOX:
        return f"error: no such email {email_id}"
    LABELS.setdefault(email_id, []).append(label)
    return f"labeled {email_id} -> {label}"


TOOLS = {"gmail_search": gmail_search, "gmail_archive": gmail_archive, "gmail_label": gmail_label}


def _real_openrouter_model():
    from langchain_openrouter import ChatOpenRouter

    return ChatOpenRouter(
        model="openai/gpt-oss-120b:free",
        temperature=0.1,
        api_key=os.environ["OPENROUTER_API_KEY"],
    )


def _scripted_weak_model():
    """A weak model that quits after one lookup, then (post-nudge) does the work."""
    from tests.helpers import create_fake_llm_with_tool_calls

    def call(name: str, args: dict, cid: str) -> dict:
        return {"name": name, "args": args, "id": cid, "type": "tool_call"}

    return create_fake_llm_with_tool_calls(
        [
            call("gmail_search", {"query": ""}, "c1"),
            # Premature stop: one lookup, then a lazy summary with the job undone.
            "I looked at your inbox. Looks like mostly promos. All set!",
            # After the harness nudge, it actually triages.
            call("gmail_archive", {"email_id": "e1"}, "c2"),
            call("gmail_archive", {"email_id": "e3"}, "c3"),
            call("gmail_archive", {"email_id": "e5"}, "c4"),
            call("gmail_label", {"email_id": "e2", "label": "action-needed"}, "c5"),
            call("gmail_label", {"email_id": "e4", "label": "action-needed"}, "c6"),
            "Triaged: archived 3 promo/newsletter emails (e1, e3, e5) and flagged 2 that need "
            "you (e2 offer letter, e4 failed payment) as action-needed.",
        ]
    )


async def main() -> None:
    use_real = bool(os.environ.get("OPENROUTER_API_KEY"))
    model = _real_openrouter_model() if use_real else _scripted_weak_model()
    print(
        f"MODEL: {'gpt-oss-120b:free (real, via OpenRouter)' if use_real else 'scripted weak model'}\n"
    )

    builder = create_agent(
        llm=model,
        tool_registry=TOOLS,
        agent_name="executor_agent",
        disable_retrieve_tools=True,
        initial_tool_ids=list(TOOLS),
        require_finish_to_end=True,
        middleware=[LoopGuardMiddleware(hard_stop=True)],
    )
    graph = builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())

    task = (
        "Triage my inbox: archive the promotional and newsletter emails, and flag anything "
        "that genuinely needs my attention with an 'action-needed' label. Be thorough."
    )
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=task)], "todos": []},
        config={"configurable": {"thread_id": "triage-demo"}, "recursion_limit": 40},
    )

    msgs = result["messages"]
    nudged = any(
        isinstance(m, HumanMessage) and m.content == COMPLETION_NUDGE_MESSAGE for m in msgs
    )
    tool_calls = [
        tc["name"] for m in msgs if isinstance(m, AIMessage) for tc in (m.tool_calls or [])
    ]

    print("--- trajectory ---")
    for m in msgs:
        if isinstance(m, HumanMessage):
            tag = "NUDGE" if m.content == COMPLETION_NUDGE_MESSAGE else "USER"
            print(f"[{tag}] {m.content[:110]}")
        elif isinstance(m, AIMessage):
            if m.tool_calls:
                print(
                    f"[MODEL] tool_calls: {[tc['name'] + str(tc['args']) for tc in m.tool_calls]}"
                )
            if isinstance(m.content, str) and m.content.strip():
                print(f"[MODEL] {m.content[:140]}")
        elif isinstance(m, ToolMessage):
            print(f"[TOOL:{m.name}] {str(m.content)[:90]}")

    print("\n--- outcome ---")
    print(f"harness nudged a premature stop : {nudged}")
    print(f"tool calls made                : {tool_calls}")
    print(f"emails archived                : {sorted(ARCHIVED)}")
    print(f"labels applied                 : {LABELS}")
    ok = {"e1", "e3", "e5"} == ARCHIVED and LABELS.get("e2") and LABELS.get("e4")
    print(f"\nTRIAGE CORRECT: {bool(ok)}")


if __name__ == "__main__":
    asyncio.run(main())
