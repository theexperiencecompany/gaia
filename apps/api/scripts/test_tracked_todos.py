"""
Multi-agent test framework for GAIA tracked todos.

Agents:
  1. ScenarioDesigner — finds complex real-world test scenarios using GAIA's integrations
  2. Tester          — runs each scenario via the GAIA API, captures results
  3. Reporter        — writes a comprehensive markdown report
  4. Improver        — analyzes root causes and produces prioritized action plan

Usage:
  cd apps/api
  uv run python scripts/test_tracked_todos.py

Requires:
  - API running at localhost:8000
  - AGENT_SECRET set in .env
  - EVAL_USER_ID set in .env (the test user)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import time
import uuid

from dotenv import load_dotenv
import httpx
from jose import jwt

# ── Config ─────────────────────────────────────────────────────────────────────
# Secrets and the test user identity come from the environment (.env). Never
# hardcode them — AGENT_SECRET is a real signing key.

load_dotenv()

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
AGENT_SECRET = os.environ.get("AGENT_SECRET")
EVAL_USER_ID = os.environ.get("EVAL_USER_ID")
JWT_ALGORITHM = "HS256"
STREAM_TIMEOUT = 120  # seconds to wait for each stream to finish

if not AGENT_SECRET:
    print("ERROR: AGENT_SECRET is not set. Add it to apps/api/.env and re-run.")
    sys.exit(1)
if not EVAL_USER_ID:
    print("ERROR: EVAL_USER_ID is not set. Add the test user id to apps/api/.env.")
    sys.exit(1)


# ── Auth helper ────────────────────────────────────────────────────────────────


def create_agent_token(user_id: str) -> str:
    from datetime import timedelta

    expire = datetime.now(UTC) + timedelta(minutes=60)
    payload = {
        "sub": user_id,
        "role": "agent",
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, AGENT_SECRET, algorithm=JWT_ALGORITHM)


# ── Test scenario definitions ──────────────────────────────────────────────────


@dataclass
class TestScenario:
    id: str
    name: str
    description: str
    chats: list[str]  # Sequential messages within same conversation
    expected_todo_created: bool  # Should a tracked todo be created?
    expected_todo_count: int  # How many todos total should exist after all chats?
    tags: list[str] = field(default_factory=list)
    requires_integrations: list[str] = field(default_factory=list)  # e.g. ["gmail", "linear"]
    skip_if_no_integrations: bool = True  # skip when required integrations are absent


@dataclass
class ChatResult:
    message: str
    response_text: str
    tool_calls: list[dict]
    raw_events: list[dict]
    error: str | None = None


@dataclass
class ScenarioResult:
    scenario: TestScenario
    chat_results: list[ChatResult]
    todos_before: list[dict]
    todos_after: list[dict]
    passed: bool
    failures: list[str]
    notes: list[str]


# ── Scenario Designer ──────────────────────────────────────────────────────────

SCENARIOS: list[TestScenario] = [
    # ── GAIA-NATIVE writes (no external integrations needed) ──────────────────
    TestScenario(
        id="S01",
        name="Set up recurring HackerNews digest",
        description="Ask GAIA to set up a daily HN digest — should create workflow + tracked todo with scheduled_at + recurrence",
        chats=[
            "set up a daily workflow: every morning at 9am IST, fetch the top 10 HackerNews stories and send me a summary",
            "yes, go ahead and set that up",
        ],
        expected_todo_created=True,
        expected_todo_count=1,
        tags=["recurring", "native-write", "no-integration-needed"],
        requires_integrations=[],
    ),
    TestScenario(
        id="S02",
        name="Complex weather lookup (read-only)",
        description="Multi-step weather query across cities — still a read, zero tracked todos",
        chats=[
            "what's the weather in Mumbai, Delhi, and Bangalore today? compare them",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["read", "no-todo", "no-integration-needed"],
        requires_integrations=[],
    ),
    TestScenario(
        id="S03",
        name="My todos summary (read-only)",
        description="Asking GAIA to list or summarize its own todos is a read — no tracked todo",
        chats=[
            "what tracked todos do I have active right now?",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["read", "no-todo", "native"],
        requires_integrations=[],
    ),
    TestScenario(
        id="S04",
        name="Casual chat (no todo)",
        description="Small talk / casual conversation should never create a tracked todo",
        chats=[
            "hey what's up",
            "tell me a fun fact about space",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["chat", "no-todo", "no-integration-needed"],
        requires_integrations=[],
    ),
    # ── READ actions — should NOT create tracked todos ─────────────────────────
    TestScenario(
        id="S05",
        name="Calendar lookup (read-only)",
        description="Asking what's on the calendar should never create a tracked todo",
        chats=[
            "what meetings do I have tomorrow?",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["gcalendar", "read", "no-todo"],
        requires_integrations=[],  # comms_agent handles this without calling executor
    ),
    TestScenario(
        id="S06",
        name="GitHub PR review summary (read-only)",
        description="Summarizing open PRs is a read — no tracked todo",
        chats=[
            "give me a summary of all open PRs in the heygaia/gaia GitHub repo",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["github", "read", "no-todo"],
        requires_integrations=[],
    ),
    TestScenario(
        id="S07",
        name="Linear backlog review (read-only)",
        description="Listing high-priority Linear issues is a read — no tracked todo",
        chats=[
            "list all high priority Linear issues assigned to me",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["linear", "read", "no-todo"],
        requires_integrations=[],
    ),
    TestScenario(
        id="S08",
        name="Slack message search (read-only)",
        description="Searching Slack messages is a read — no tracked todo",
        chats=[
            "search Slack for any messages about the Q2 roadmap from last week",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["slack", "read", "no-todo"],
        requires_integrations=[],
    ),
    TestScenario(
        id="S09",
        name="Email listing (read-only)",
        description="Listing unread emails is a read — no tracked todo",
        chats=[
            "show me my last 5 unread emails",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["gmail", "read", "no-todo"],
        requires_integrations=[],
    ),
    TestScenario(
        id="S10",
        name="Multi-query read (read-only)",
        description="Complex multi-system read — no tracked todo",
        chats=[
            "what's on my calendar today and do I have any overdue Linear issues?",
        ],
        expected_todo_created=False,
        expected_todo_count=0,
        tags=["gcalendar", "linear", "read", "no-todo"],
        requires_integrations=[],
    ),
    # ── Integration-required write tests (skipped when integrations absent) ────
    TestScenario(
        id="S11",
        name="Linear issue creation + comment",
        description="Create a Linear issue, then add a comment to it — one tracked todo for both actions",
        chats=[
            "create a Linear issue titled 'Test: flaky auth timeout "
            + datetime.now(UTC).strftime("%Y%m%d%H%M")
            + "' with medium priority, assign to me",
            "add a comment to that issue: 'Reproduced on staging, affects ~5% of logins'",
        ],
        expected_todo_created=True,
        expected_todo_count=1,
        tags=["linear", "write", "multi-step"],
        requires_integrations=["linear"],
    ),
    TestScenario(
        id="S12",
        name="Slack announcement (write)",
        description="Post a message to Slack #general",
        chats=[
            "post to the #general Slack channel: 'Team sync moved to 4pm today'",
        ],
        expected_todo_created=True,
        expected_todo_count=1,
        tags=["slack", "write"],
        requires_integrations=["slack"],
    ),
    TestScenario(
        id="S13",
        name="Multi-provider: email + calendar event",
        description="Send an email AND create a calendar event for the same meeting — ONE todo",
        chats=[
            "email aryan@heygaia.io about a design review meeting on Monday 3pm, and create a Google Calendar event for it too",
        ],
        expected_todo_created=True,
        expected_todo_count=1,
        tags=["gmail", "gcalendar", "write", "multi-provider"],
        requires_integrations=["gmail"],
    ),
    TestScenario(
        id="S14",
        name="Follow-up email dedup",
        description="First chat sends email; second chat sends follow-up — must reuse the SAME todo",
        chats=[
            "email rahul@example.com about the Q3 vendor contract — introduce ourselves and ask for a call",
            "rahul replied saying he's interested. send a thank you and propose next Thursday 2pm",
        ],
        expected_todo_created=True,
        expected_todo_count=1,
        tags=["gmail", "dedup", "multi-chat"],
        requires_integrations=["gmail"],
    ),
]


# ── API helpers ────────────────────────────────────────────────────────────────


def _parse_sse_line(line: str) -> dict | None:
    """Parse a single `data: ...` SSE line into an event dict; return None to skip."""
    if not line.startswith("data: "):
        return None
    raw = line[6:]
    if raw in ("", "[DONE]"):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _accumulate_text(event: dict, text_chunks: list[str]) -> None:
    if "response" in event:
        text_chunks.append(event["response"])


def _accumulate_tool_calls(event: dict, tool_calls: list[dict]) -> None:
    td = event.get("tool_data")
    if not td:
        return
    tool_name = td.get("tool_name", td.get("name", ""))
    if not tool_name:
        return
    tool_calls.append(
        {
            "name": tool_name,
            "input": td.get("tool_input", td.get("input", {})),
        }
    )


def _extract_event_error(event: dict) -> str | None:
    if "error" not in event and "[STREAM_ERROR]" not in str(event):
        return None
    err_val = event.get("error", str(event))
    if err_val and err_val != "null":
        return str(err_val)
    return None


async def send_chat_message(
    client: httpx.AsyncClient,
    token: str,
    message: str,
    conversation_id: str,
    history: list[dict],
) -> ChatResult:
    """Send a message and collect the full SSE stream."""
    events: list[dict] = []
    tool_calls: list[dict] = []
    text_chunks: list[str] = []
    error: str | None = None

    # `messages` must include the current user message as the last item; history
    # holds previous turns.
    full_messages = [*history, {"role": "user", "content": message}]

    try:
        async with client.stream(
            "POST",
            f"{API_BASE}/api/v1/chat-stream",
            json={
                "message": message,
                "messages": full_messages,
                "conversation_id": conversation_id,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-timezone": "Asia/Kolkata",
            },
            timeout=STREAM_TIMEOUT,
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                return ChatResult(
                    message=message,
                    response_text="",
                    tool_calls=[],
                    raw_events=[],
                    error=f"HTTP {response.status_code}: {body.decode()[:500]}",
                )
            async for line in response.aiter_lines():
                event = _parse_sse_line(line)
                if event is None:
                    continue
                events.append(event)
                _accumulate_text(event, text_chunks)
                _accumulate_tool_calls(event, tool_calls)
                event_error = _extract_event_error(event)
                if event_error:
                    error = event_error
    except Exception as e:
        error = str(e)

    return ChatResult(
        message=message,
        response_text="".join(text_chunks),
        tool_calls=tool_calls,
        raw_events=events,
        error=error,
    )


async def get_tracked_todos(client: httpx.AsyncClient, token: str) -> list[dict]:
    """Fetch all tracked todos (gaia-tracked label) directly from MongoDB.

    Note: agent tokens only work for /api/v1/chat-stream, so we go to MongoDB directly.
    """
    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        mongo = AsyncIOMotorClient("mongodb://localhost:27017")
        db = mongo["GAIA"]
        docs = await db.todos.find(
            {
                "user_id": EVAL_USER_ID,
                "labels": "gaia-tracked",
            }
        ).to_list(100)
        return [
            {
                "id": str(doc["_id"]),
                "title": doc.get("title", ""),
                "labels": doc.get("labels", []),
                "priority": doc.get("priority"),
                "scheduled_at": str(doc["scheduled_at"]) if doc.get("scheduled_at") else None,
                "recurrence": doc.get("recurrence"),
            }
            for doc in docs
        ]
    except Exception as e:
        print(f"  WARNING: MongoDB todo fetch failed: {e}")
        return []


async def delete_todos_by_ids(todo_ids: list[str]) -> None:
    """Clean up test todos via MongoDB (agent token doesn't support DELETE endpoint)."""
    try:
        from bson import ObjectId
        from motor.motor_asyncio import AsyncIOMotorClient

        mongo = AsyncIOMotorClient("mongodb://localhost:27017")
        db = mongo["GAIA"]
        for tid in todo_ids:
            await db.todos.delete_one({"_id": ObjectId(tid)})
    except Exception:
        pass  # Best-effort cleanup


# ── Tester ────────────────────────────────────────────────────────────────────


async def check_connected_integrations(client: httpx.AsyncClient, token: str) -> set[str]:
    """Return set of connected integration IDs for the current user (via MongoDB)."""
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo = AsyncIOMotorClient("mongodb://localhost:27017")
    db = mongo["GAIA"]
    connected: set[str] = set()
    try:
        cursor = db.user_integrations.find({"user_id": EVAL_USER_ID, "status": "connected"})
        async for doc in cursor:
            integration_id = doc.get("integration_id", "")
            if integration_id:
                connected.add(integration_id.lower())
    finally:
        mongo.close()
    return connected


def _check_todo_count(scenario: TestScenario, new_todos: list[dict]) -> list[str]:
    """Validate the number of created todos against the scenario expectation."""
    actual = len(new_todos)
    if scenario.expected_todo_created and actual == 0:
        return ["Expected ≥1 tracked todo to be created, but got 0"]
    titles = [t.get("title", "?") for t in new_todos]
    if not scenario.expected_todo_created and actual > 0:
        return [f"Expected NO tracked todo (read-only action), but {actual} created: {titles}"]
    if scenario.expected_todo_created and actual != scenario.expected_todo_count:
        return [f"Expected {scenario.expected_todo_count} todo(s), got {actual}: {titles}"]
    return []


def _check_search_first(chat_results: list[ChatResult]) -> tuple[list[str], list[str]]:
    """Verify search_todo_context was called before create_tracked_todo."""
    all_tool_calls: list[dict] = []
    for cr in chat_results:
        all_tool_calls.extend(cr.tool_calls)

    tool_names_ordered = [t["name"] for t in all_tool_calls]
    if "create_tracked_todo" not in tool_names_ordered:
        return [], []

    create_idx = tool_names_ordered.index("create_tracked_todo")
    search_before = any(t["name"] == "search_todo_context" for t in all_tool_calls[:create_idx])
    if not search_before:
        return [
            "create_tracked_todo called WITHOUT prior search_todo_context "
            "(search-first rule violated)"
        ], []
    return [], ["✓ search_todo_context was called before create_tracked_todo"]


def _check_recurring_fields(scenario: TestScenario, new_todos: list[dict]) -> list[str]:
    """Validate recurring-todo fields for the recurring scenario (tagged ``recurring``)."""
    if "recurring" not in scenario.tags or not new_todos:
        return []
    todo = new_todos[0]
    failures = []
    if not todo.get("scheduled_at"):
        failures.append("Recurring todo missing scheduled_at field")
    if not todo.get("recurrence"):
        failures.append("Recurring todo missing recurrence field")
    return failures


def _evaluate_scenario(
    scenario: TestScenario, new_todos: list[dict], chat_results: list[ChatResult]
) -> tuple[list[str], list[str]]:
    """Collect all failures and notes for a completed scenario run."""
    failures = _check_todo_count(scenario, new_todos)

    search_failures, notes = _check_search_first(chat_results)
    failures += search_failures

    for i, cr in enumerate(chat_results):
        if cr.error:
            failures.append(f"Chat {i + 1} errored: {cr.error[:200]}")

    failures += _check_recurring_fields(scenario, new_todos)
    return failures, notes


async def run_scenario(
    scenario: TestScenario,
    token: str,
    connected_integrations: set[str] | None = None,
    cleanup: bool = True,
) -> ScenarioResult:
    """Run a single test scenario."""
    print(f"\n{'=' * 60}")
    print(f"[{scenario.id}] {scenario.name}")
    print(f"  Tags: {', '.join(scenario.tags)}")

    # Skip if required integrations are not connected
    if scenario.requires_integrations and scenario.skip_if_no_integrations:
        avail = connected_integrations or set()
        missing = [i for i in scenario.requires_integrations if i.lower() not in avail]
        if missing:
            print(f"  ⏭️  SKIPPED — integrations not connected: {missing}")
            return ScenarioResult(
                scenario=scenario,
                chat_results=[],
                todos_before=[],
                todos_after=[],
                passed=True,
                failures=[],
                notes=[f"Skipped: integrations not connected: {missing}"],
            )

    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
        # Capture todos before
        todos_before = await get_tracked_todos(client, token)
        before_ids = {t["id"] for t in todos_before}

        conversation_id = str(uuid.uuid4())
        history: list[dict] = []
        chat_results: list[ChatResult] = []

        for i, message in enumerate(scenario.chats):
            print(f"  Chat {i + 1}: {message[:80]}{'...' if len(message) > 80 else ''}")
            result = await send_chat_message(client, token, message, conversation_id, history)
            chat_results.append(result)

            if result.error:
                print(f"    ERROR: {result.error}")
            else:
                tool_names = [t["name"] for t in result.tool_calls]
                print(f"    Tools: {tool_names or '(none)'}")
                if result.response_text:
                    preview = result.response_text[:120].replace("\n", " ")
                    print(f"    Reply: {preview}...")

            # Update history for next chat
            history.append({"role": "user", "content": message})
            if result.response_text:
                history.append({"role": "assistant", "content": result.response_text})

            # Small delay between chats
            if i < len(scenario.chats) - 1:
                await asyncio.sleep(2)

        # Give the system a moment to persist
        await asyncio.sleep(3)

        # Capture todos after
        todos_after = await get_tracked_todos(client, token)
        new_todos = [t for t in todos_after if t["id"] not in before_ids]

        # Evaluate
        failures, notes = _evaluate_scenario(scenario, new_todos, chat_results)
        passed = len(failures) == 0

        print(f"  Result: {'✅ PASS' if passed else '❌ FAIL'}")
        for f in failures:
            print(f"    ✗ {f}")
        for n in notes:
            print(f"    {n}")

        # Cleanup test todos
        if cleanup and new_todos:
            new_todo_ids = [t["id"] for t in new_todos]
            await delete_todos_by_ids(new_todo_ids)
            print(f"  Cleaned up {len(new_todo_ids)} test todo(s)")

        return ScenarioResult(
            scenario=scenario,
            chat_results=chat_results,
            todos_before=todos_before,
            todos_after=new_todos,
            passed=passed,
            failures=failures,
            notes=notes,
        )


# ── Reporter ──────────────────────────────────────────────────────────────────


def _is_skipped(r: ScenarioResult) -> bool:
    return bool(r.notes and any("Skipped" in n for n in r.notes))


def _summary_status(r: ScenarioResult) -> str:
    if _is_skipped(r):
        return "⏭️ SKIP"
    return "✅ PASS" if r.passed else "❌ FAIL"


def _report_summary_rows(results: list[ScenarioResult]) -> list[str]:
    rows = []
    for r in results:
        tags = ", ".join(r.scenario.tags)
        rows.append(
            f"| {r.scenario.id} | {r.scenario.name} | {tags} | {_summary_status(r)} "
            f"| {len(r.todos_after)} | {len(r.failures)} |"
        )
    return rows


def _report_created_todos(r: ScenarioResult) -> list[str]:
    if not r.todos_after:
        return []
    out = ["**Created todos:**"]
    for t in r.todos_after:
        sched = t.get("scheduled_at", "")
        recur = t.get("recurrence", "")
        out.append(
            f"- `{t.get('title', '?')}` (priority={t.get('priority', 'none')}"
            + (f", scheduled_at={sched}" if sched else "")
            + (f", recurrence={recur}" if recur else "")
            + ")"
        )
    out.append("")
    return out


def _report_transcript(r: ScenarioResult) -> list[str]:
    out = ["**Chat transcript:**", ""]
    for i, cr in enumerate(r.chat_results):
        out.append(f"*Chat {i + 1}:* `{cr.message[:100]}`")
        if cr.tool_calls:
            tools = ", ".join(t["name"] for t in cr.tool_calls)
            out.append(f"- Tools called: {tools}")
        if cr.response_text:
            preview = cr.response_text[:300].replace("\n", " ")
            out.append(f"- Response: {preview}...")
        if cr.error:
            out.append(f"- ERROR: {cr.error[:200]}")
        out.append("")
    return out


def _report_detail(r: ScenarioResult) -> list[str]:
    status = _summary_status(r)
    out = [
        f"### [{r.scenario.id}] {r.scenario.name} — {status}",
        "",
        f"**Description:** {r.scenario.description}  ",
        f"**Tags:** {', '.join(r.scenario.tags)}  ",
        f"**Expected todo:** {'yes' if r.scenario.expected_todo_created else 'no'}  ",
        f"**Todos created:** {len(r.todos_after)}  ",
        "",
    ]
    out += _report_created_todos(r)
    if r.failures:
        out += ["**Failures:**", *[f"- ✗ {f}" for f in r.failures], ""]
    if r.notes:
        out += ["**Notes:**", *[f"- {n}" for n in r.notes], ""]
    out += _report_transcript(r)
    out += ["---", ""]
    return out


def generate_report(results: list[ScenarioResult], duration_s: float) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    skipped = [r for r in results if _is_skipped(r)]
    run = [r for r in results if not _is_skipped(r)]
    passed = [r for r in run if r.passed]
    failed = [r for r in run if not r.passed]

    lines: list[str] = [
        "# GAIA Tracked Todo Test Report",
        f"\n**Date:** {now}  ",
        f"**Duration:** {duration_s:.1f}s  ",
        f"**Passed:** {len(passed)}/{len(run)} (ran)  ",
        f"**Failed:** {len(failed)}/{len(run)} (ran)  ",
        f"**Skipped:** {len(skipped)} (no integrations)  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| ID | Name | Tags | Result | Todos Created | Failures |",
        "|----|------|------|--------|---------------|---------|",
    ]
    lines += _report_summary_rows(results)
    lines += ["", "---", "", "## Detailed Results", ""]
    for r in results:
        lines += _report_detail(r)

    return "\n".join(lines)


# ── Improver ──────────────────────────────────────────────────────────────────


def _categorize_failure(f_lower: str) -> str:
    """Map a lowercased failure message to a failure-pattern bucket."""
    if "read-only" in f_lower or "no tracked todo" in f_lower:
        return "read_only_created_todo"
    if "expected 1" in f_lower and "got" in f_lower:
        return "dedup_failed"
    if "search_todo_context" in f_lower and "without" in f_lower:
        return "search_first_violated"
    if "scheduled_at" in f_lower or "recurrence" in f_lower:
        return "recurring_missing_fields"
    if "errored" in f_lower or "http" in f_lower:
        return "api_errors"
    return "other_failures"


def _categorize_failures(failed: list[ScenarioResult]) -> dict[str, list[tuple]]:
    """Group all failure messages from failed scenarios into pattern buckets."""
    buckets: dict[str, list[tuple]] = {
        "read_only_created_todo": [],
        "dedup_failed": [],
        "search_first_violated": [],
        "recurring_missing_fields": [],
        "api_errors": [],
        "other_failures": [],
    }
    for r in failed:
        for f in r.failures:
            buckets[_categorize_failure(f.lower())].append((r.scenario.id, r.scenario.name, f))
    return buckets


def generate_improvement_plan(results: list[ScenarioResult]) -> str:
    skipped = [r for r in results if _is_skipped(r)]
    run = [r for r in results if not _is_skipped(r)]
    failed = [r for r in run if not r.passed]
    passed = [r for r in run if r.passed]

    buckets = _categorize_failures(failed)
    read_only_created_todo = buckets["read_only_created_todo"]
    dedup_failed = buckets["dedup_failed"]
    search_first_violated = buckets["search_first_violated"]
    recurring_missing_fields = buckets["recurring_missing_fields"]
    api_errors = buckets["api_errors"]
    other_failures = buckets["other_failures"]

    pct = (100 * len(passed) // len(run)) if run else 0
    lines: list[str] = [
        "# GAIA Tracked Todo — Improvement Analysis",
        "",
        f"**Pass rate:** {len(passed)}/{len(run)} ran ({pct}%) — {len(skipped)} skipped (no integrations)",
        "",
        "---",
        "",
        "## Failure Pattern Analysis",
        "",
    ]

    def section(title: str, items: list[tuple], root_cause: str, fix: str) -> list[str]:
        if not items:
            return []
        out = [f"### {title}", "", f"**Affected:** {len(items)} scenario(s)", ""]
        for sid, name, failure in items:
            out.append(f"- `{sid}` {name}: {failure}")
        out += ["", f"**Root cause:** {root_cause}", "", f"**Recommended fix:** {fix}", ""]
        return out

    lines += section(
        "Bug 1: Read-only actions creating tracked todos",
        read_only_created_todo,
        "The executor does not consistently distinguish read (fetch/list/search/summarize) from write (send/create/post/schedule). "
        "Despite the PHILOSOPHY section being updated, the LLM still sometimes creates a todo after complex multi-tool read operations.",
        "Add a stronger pre-action gate in the executor prompt: before ANY `create_tracked_todo` call, "
        "require the model to explicitly classify the action as READ or WRITE. Only proceed if WRITE. "
        "Example: add a CHECK block:\n"
        "```\nBEFORE calling create_tracked_todo, answer:\n"
        "  - Did GAIA modify something in an external system? (yes/no)\n"
        "  - If no → do not create. If yes → continue.\n```",
    )

    lines += section(
        "Bug 2: Duplicate todos (deduplication failures)",
        dedup_failed,
        "search_todo_context is called but the active-match gate is not strong enough. "
        "When a match score is low or the match is from a different action within the same initiative, "
        "the model still creates a new todo instead of updating the existing one.",
        "Strengthen the dedup gate with a concrete similarity threshold note in the prompt. "
        "Also: after search returns ANY match with score ≥ 0.3, force a vfs_read of the canvas "
        "before deciding whether to create. This makes the existing context visible before the create decision.",
    )

    lines += section(
        "Bug 3: search_todo_context not called before create_tracked_todo",
        search_first_violated,
        "The executor skips search_todo_context when the active todos block is empty (or when it's confident the task is new). "
        "The search-first instruction exists but is not enforced as a hard pre-condition.",
        "Add a hard GATE to the prompt:\n"
        "```\nHARD GATE: You MUST call search_todo_context BEFORE calling create_tracked_todo.\n"
        "If you skipped this, stop and call it now. There are no exceptions.\n```",
    )

    lines += section(
        "Bug 4: Recurring todo missing scheduled_at/recurrence fields",
        recurring_missing_fields,
        "When the system routes a recurring request to create_workflow instead of a tracked todo with recurrence, "
        "the tracked todo is created without scheduling fields. The workflow and todo are not linked.",
        "Two options:\n"
        "1. If a Workflow is created for a recurring task, also create/update a tracked todo with `scheduled_at` + `recurrence` "
        "that points to the workflow ID in its canvas.\n"
        "2. Or: skip the tracked todo entirely when a Workflow already tracks it — but add the workflow ID to the Activity Log.",
    )

    lines += section(
        "API / Infrastructure Errors",
        api_errors,
        "Connection or timeout issues during testing.",
        "Ensure the API is running and stable before re-running tests.",
    )

    lines += section(
        "Other Failures",
        other_failures,
        "Miscellaneous failures requiring case-by-case analysis.",
        "Review the detailed scenario logs above.",
    )

    # Priority order
    lines += [
        "---",
        "",
        "## Prioritized Action Plan",
        "",
        "| Priority | Fix | Impact | Effort |",
        "|----------|-----|--------|--------|",
        "| P0 | Hard GATE: `search_todo_context` before `create_tracked_todo` | Prevents all search-first violations | Low — one prompt line |",
        "| P0 | Pre-create READ/WRITE classification check | Fixes read-only todo creation | Low — add CHECK block to prompt |",
        "| P1 | Lower score threshold + vfs_read before dedup decision | Fixes duplicate todos | Medium — prompt + logic |",
        "| P1 | Link Workflow ↔ Tracked Todo (recurring tasks) | Fixes S04/S06 style failures | High — architectural change |",
        "| P2 | Add automated assertion for `search_todo_context` ordering | Catches regressions early | Medium — test infra |",
        "| P2 | Add `expires_at` guidance for time-sensitive todos | Prevents stale todos | Low — prompt addition |",
        "",
    ]

    lines += [
        "---",
        "",
        "## What's Working Well",
        "",
    ]
    for r in passed:
        lines.append(f"- **[{r.scenario.id}] {r.scenario.name}** — passed cleanly")
        for n in r.notes:
            lines.append(f"  - {n}")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────


async def reset_rate_limits() -> None:
    """Clear all chat_messages rate limit keys for the test user in Redis."""
    from datetime import datetime

    import redis.asyncio as aioredis

    r = aioredis.from_url("redis://localhost:6379")
    try:
        # Key format: rate_limit:{user_id}:{feature}:{period_repr}:{time_window}
        # period_repr uses Python enum repr: "RateLimitPeriod.DAY" / "RateLimitPeriod.MONTH"
        today = datetime.now(UTC).strftime("%Y%m%d")
        month = datetime.now(UTC).strftime("%Y%m")
        # Also cover yesterday in case UTC date hasn't rolled over yet
        from datetime import timedelta

        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%d")
        prev_month = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m")

        keys_to_delete = [
            f"rate_limit:{EVAL_USER_ID}:chat_messages:RateLimitPeriod.DAY:{today}",
            f"rate_limit:{EVAL_USER_ID}:chat_messages:RateLimitPeriod.DAY:{yesterday}",
            f"rate_limit:{EVAL_USER_ID}:chat_messages:RateLimitPeriod.MONTH:{month}",
            f"rate_limit:{EVAL_USER_ID}:chat_messages:RateLimitPeriod.MONTH:{prev_month}",
        ]
        keys_deleted = await r.delete(*keys_to_delete)
        print(f"  Rate limit keys cleared: {keys_deleted}")
    finally:
        await r.aclose()


async def purge_orphaned_todos() -> None:
    """Delete all gaia-tracked todos for the test user left from previous runs."""
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo = AsyncIOMotorClient("mongodb://localhost:27017")
    db = mongo["GAIA"]
    try:
        result = await db.todos.delete_many(
            {
                "user_id": EVAL_USER_ID,
                "labels": "gaia-tracked",
            }
        )
        print(f"  Purged {result.deleted_count} orphaned gaia-tracked todo(s)")
    finally:
        mongo.close()


async def main() -> None:
    token = create_agent_token(EVAL_USER_ID)
    print(f"Generated agent token for user {EVAL_USER_ID}")

    # Verify API is up
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{API_BASE}/health")
        if resp.status_code != 200:
            print(f"ERROR: API not healthy ({resp.status_code}). Run: nx dev api")
            sys.exit(1)
    print(f"API is healthy at {API_BASE}")

    # Pre-run cleanup: purge orphaned todos + reset rate limits
    print("Pre-run setup:")
    await purge_orphaned_todos()
    await reset_rate_limits()

    # Detect connected integrations
    async with httpx.AsyncClient(timeout=15) as client:
        connected = await check_connected_integrations(client, token)
    print(f"Connected integrations: {connected or '(none)'}")

    start = time.monotonic()
    results: list[ScenarioResult] = []

    # Run scenarios sequentially (to avoid flaky cross-contamination)
    for scenario in SCENARIOS:
        # Reset chat_messages rate limit before each scenario so tests don't block each other
        await reset_rate_limits()
        result = await run_scenario(scenario, token, connected_integrations=connected, cleanup=True)
        results.append(result)
        # Brief pause between scenarios
        await asyncio.sleep(2)

    duration = time.monotonic() - start

    # Generate report + improvement plan
    report = generate_report(results, duration)
    plan = generate_improvement_plan(results)

    # Write outputs
    out_dir = Path(__file__).parent / "test_output"
    out_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"todo_test_report_{ts}.md"
    plan_path = out_dir / f"todo_improvement_plan_{ts}.md"

    report_path.write_text(report)
    plan_path.write_text(plan)

    # Print summary
    skipped_count = sum(1 for r in results if r.notes and any("Skipped" in n for n in r.notes))
    run_count = len(results) - skipped_count
    passed_count = sum(
        1 for r in results if r.passed and not (r.notes and any("Skipped" in n for n in r.notes))
    )
    print(f"\n{'=' * 60}")
    print(
        f"FINAL RESULTS: {passed_count}/{run_count} passed, {skipped_count} skipped ({duration:.1f}s)"
    )
    print(f"Report:       {report_path}")
    print(f"Action plan:  {plan_path}")

    # Print report to stdout too
    print("\n" + "=" * 60)
    print(report)
    print("\n" + "=" * 60)
    print(plan)


if __name__ == "__main__":
    asyncio.run(main())
