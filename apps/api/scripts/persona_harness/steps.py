"""The persona harness's action vocabulary.

Every *action* a persona takes goes through a real surface: HTTP against the
running API (dev endpoints, the real ``/todos`` endpoints, ``/chat-stream``)
with ``X-Dev-User`` for identity. Direct Mongo access is used only for
FIXTURES (seeding backdated history a real user would have accumulated over
weeks) and ASSERTIONS (reading back what the product actually stored) — never
to perform the action itself. See ``openspec/changes/daily-briefing-self-
executing-todos/tasks.md`` I.7 and the ``driving-gaia`` skill.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from typing import Any
import uuid

from bson import ObjectId
import httpx
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import redis.asyncio as aioredis

from scripts.persona_harness.report import Report

MONGO_URL = "mongodb://localhost:27017/GAIA"
API_DIR = Path(__file__).resolve().parents[2]
REDIS_URL = "redis://localhost:6379"

_DAY_FIELDS_DATETIME = (
    "created_at",
    "updated_at",
    "completed_at",
    "scheduled_at",
    "dismissed_at",
    "pitch_expires_at",
)


@dataclass
class HarnessContext:
    """Everything one persona run needs: identity, transports, the report."""

    email: str
    api_base: str
    sim: bool
    report: Report
    day: int = 0
    user_id: str | None = None
    http: httpx.AsyncClient = field(init=False, repr=False)
    db: AsyncIOMotorDatabase = field(init=False, repr=False)
    redis: aioredis.Redis = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.http = httpx.AsyncClient(
            base_url=self.api_base,
            headers={"X-Dev-User": self.email},
            timeout=180.0,
        )
        self.db = AsyncIOMotorClient(MONGO_URL).get_default_database()
        self.redis = aioredis.from_url(REDIS_URL)

    async def aclose(self) -> None:
        await self.http.aclose()
        self.db.client.close()
        await self.redis.aclose()

    def log(self, *, actor: str, surface: str, content: str) -> None:
        self.report.record(sim_day=self.day, actor=actor, surface=surface, content=content)


def _raise_for_status(ctx: HarnessContext, resp: httpx.Response, surface: str) -> None:
    if resp.status_code >= 400:
        raise AssertionError(
            f"{surface} for {ctx.email} returned {resp.status_code}: {resp.text[:500]}"
        )


# --------------------------------------------------------------------- setup


async def mint_user(ctx: HarnessContext, *, name: str | None = None) -> dict[str, Any]:
    resp = await ctx.http.post("/dev/users", json={"email": ctx.email, "name": name})
    _raise_for_status(ctx, resp, "POST /dev/users")
    data = resp.json()
    ctx.user_id = data["id"]
    ctx.log(
        actor="harness", surface="POST /dev/users", content=f"minted {ctx.email} -> {ctx.user_id}"
    )
    return data


async def seed_data(
    ctx: HarnessContext,
    *,
    todos: int = 0,
    conversations: int = 0,
    platform_links: list[str] | None = None,
) -> dict[str, Any]:
    resp = await ctx.http.post(
        "/dev/seed",
        json={
            "email": ctx.email,
            "todos": todos,
            "conversations": conversations,
            "platform_links": platform_links or [],
        },
    )
    _raise_for_status(ctx, resp, "POST /dev/seed")
    data = resp.json()
    ctx.log(
        actor="harness",
        surface="POST /dev/seed",
        content=f"{data['todos_created']} todos, {data['conversations_created']} conversations",
    )
    return data


async def delete_user(ctx: HarnessContext) -> None:
    resp = await ctx.http.delete(f"/dev/users/{ctx.email}")
    if resp.status_code not in (200, 404):
        raise AssertionError(f"DELETE /dev/users/{ctx.email} returned {resp.status_code}")
    ctx.log(actor="harness", surface=f"DELETE /dev/users/{ctx.email}", content="teardown")


# ------------------------------------------------------------- fixture seams


def _require_user_id(ctx: HarnessContext) -> str:
    if ctx.user_id is None:
        raise AssertionError("mint_user() must run before any fixture/action step")
    return ctx.user_id


# UserRepository's cache contract (app/db/repositories/users.py): global scope,
# prefix "user" (USER_CACHE_PREFIX). Every real write refreshes the entity key
# and bumps the generation so a read can never see a value staler than the
# last write. A harness fixture that writes ``users`` directly through Mongo
# bypasses that repository entirely, so it must replicate the same
# invalidation by hand — otherwise a cached read (e.g. the briefing
# provisioner's user lookup) silently serves the pre-fixture doc.
_USER_CACHE_PREFIX = "user"
_REPO_GLOBAL_SCOPE = "global"


async def _invalidate_user_cache(ctx: HarnessContext, user_id: str) -> None:
    await ctx.redis.delete(f"{_USER_CACHE_PREFIX}:{_REPO_GLOBAL_SCOPE}:{user_id}")
    await ctx.redis.incr(f"{_USER_CACHE_PREFIX}:{_REPO_GLOBAL_SCOPE}:gen")


async def set_timezone(ctx: HarnessContext, tz: str) -> None:
    user_id = _require_user_id(ctx)
    await ctx.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"timezone": tz}})
    await _invalidate_user_cache(ctx, user_id)
    ctx.log(actor="harness", surface="mongo:users.timezone", content=tz)


async def set_focus(ctx: HarnessContext, focus: str) -> None:
    user_id = _require_user_id(ctx)
    await ctx.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"onboarding.focus": focus}})
    await _invalidate_user_cache(ctx, user_id)
    ctx.log(actor="harness", surface="mongo:users.onboarding.focus", content=focus)


async def set_dormancy(
    ctx: HarnessContext, *, idle_days: int, date_str: str, dormant_since: datetime | None
) -> None:
    """Fixture the ``briefing_dormancy`` marker (see ``services/briefing/dormancy.py``)."""
    user_id = _require_user_id(ctx)
    await ctx.db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "briefing_dormancy": {
                    "idle_days": idle_days,
                    "date": date_str,
                    "dormant_since": dormant_since,
                }
            }
        },
    )
    await _invalidate_user_cache(ctx, user_id)
    ctx.log(
        actor="harness",
        surface="mongo:users.briefing_dormancy",
        content=f"idle_days={idle_days} dormant_since={dormant_since}",
    )


# TodoRepository's cache contract (app/db/repositories/todos.py): user_id
# scope, prefix "todo" (TODO_CACHE_PREFIX). Same bypass problem as the users
# cache above — a direct Mongo write here must invalidate by hand too.
_TODO_CACHE_PREFIX = "todo"


async def _invalidate_todos_cache(ctx: HarnessContext, user_id: str) -> None:
    await ctx.redis.incr(f"{_TODO_CACHE_PREFIX}:{user_id}:gen")


async def insert_todo(ctx: HarnessContext, **fields: object) -> str:
    """Insert a raw ``todos`` fixture document. Caller supplies every domain
    field it cares about; ``user_id``/``title`` are the only required ones."""
    user_id = _require_user_id(ctx)
    doc: dict[str, object] = {
        "user_id": user_id,
        "title": fields.pop("title", "untitled"),
        "labels": [],
        "priority": "none",
        "completed": False,
        "subtasks": [],
        "workflow_activated": False,
        "gaia_retry_count": 0,
        "gaia_user_retry_count": 0,
        "references": [],
        "artifacts": [],
        "assignee": "user",
        "kind": "task",
        "gaia_offer_dismissed": False,
        "nudge_shown": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    doc.update(fields)
    result = await ctx.db.todos.insert_one(doc)
    todo_id = str(result.inserted_id)
    await _invalidate_todos_cache(ctx, user_id)
    ctx.log(
        actor="harness",
        surface="mongo:todos.insert",
        content=f"{todo_id} title={doc['title']!r} assignee={doc['assignee']} "
        f"execution_status={doc.get('execution_status')}",
    )
    return todo_id


async def update_todo(ctx: HarnessContext, todo_id: str, **fields: object) -> None:
    user_id = _require_user_id(ctx)
    await ctx.db.todos.update_one({"_id": ObjectId(todo_id)}, {"$set": fields})
    await ctx.redis.delete(f"{_TODO_CACHE_PREFIX}:{user_id}:{todo_id}")
    await _invalidate_todos_cache(ctx, user_id)
    ctx.log(actor="harness", surface="mongo:todos.update", content=f"{todo_id} <- {fields}")


async def get_todo(ctx: HarnessContext, todo_id: str) -> dict[str, Any] | None:
    return await ctx.db.todos.find_one({"_id": ObjectId(todo_id)})


async def count_todos(ctx: HarnessContext, **query: object) -> int:
    user_id = _require_user_id(ctx)
    return await ctx.db.todos.count_documents({"user_id": user_id, **query})


async def pick_latest_proposal(ctx: HarnessContext) -> str | None:
    """The most recently created ``proposed`` GAIA todo, or ``None``."""
    user_id = _require_user_id(ctx)
    doc = await ctx.db.todos.find_one(
        {"user_id": user_id, "assignee": "gaia", "execution_status": "proposed"},
        sort=[("created_at", -1)],
    )
    return str(doc["_id"]) if doc else None


async def wait_for_execution(
    ctx: HarnessContext, todo_id: str, *, timeout_s: float = 60.0, poll_s: float = 2.0
) -> str:
    """Poll Mongo until the ARQ worker drives ``todo_id`` out of queued/running,
    or the timeout elapses (still ``queued``/``running`` in that case)."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    status = "queued"
    while asyncio.get_event_loop().time() < deadline:
        doc = await get_todo(ctx, todo_id)
        status = doc["execution_status"] if doc else "missing"
        if status not in ("queued", "running"):
            break
        await asyncio.sleep(poll_s)
    ctx.log(
        actor="worker",
        surface="mongo:todos.execution_status (poll)",
        content=f"{todo_id} settled at {status!r}",
    )
    return status


async def insert_briefing(
    ctx: HarnessContext,
    *,
    date: str,
    kind: str = "daily",
    opened_at: datetime | None = None,
    created_at: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    """Insert a raw ``briefings`` fixture (string ``_id``, matching production's
    ``brief_<hex12>`` business key — see ``db/repositories/briefings.py``)."""
    user_id = _require_user_id(ctx)
    briefing_id = f"brief_{uuid.uuid4().hex[:12]}"
    doc = {
        "_id": briefing_id,
        "user_id": user_id,
        "date": date,
        "kind": kind,
        "payload": payload
        or {
            "kicker": "Daily",
            "date": date,
            "headline": "fixture briefing",
            "lede": "fixture briefing for winback simulation",
            "stats": [],
            "sections": [],
            "mood": "clear",
            "caption": "fixture",
            "hue": 0,
            "template_family": None,
            "message": None,
            "bubbles": [],
        },
        "delivered_channels": [],
        "opened_at": opened_at,
        "created_at": created_at or datetime.now(UTC),
        "updated_at": None,
    }
    await ctx.db.briefings.insert_one(doc)
    ctx.log(
        actor="harness",
        surface="mongo:briefings.insert",
        content=f"{briefing_id} date={date} kind={kind} opened_at={opened_at}",
    )
    return briefing_id


async def get_latest_briefing(ctx: HarnessContext, *, kind: str = "daily") -> dict[str, Any]:
    user_id = _require_user_id(ctx)
    doc = await ctx.db.briefings.find_one(
        {"user_id": user_id, "kind": kind}, sort=[("created_at", -1)]
    )
    if doc is None:
        raise AssertionError(f"no {kind} briefing exists for {ctx.email}")
    return doc


async def list_recent_briefings(
    ctx: HarnessContext, *, kind: str = "daily", limit: int = 10
) -> list[dict[str, Any]]:
    user_id = _require_user_id(ctx)
    cursor = ctx.db.briefings.find({"user_id": user_id, "kind": kind})
    cursor = cursor.sort("created_at", -1).limit(limit)
    return [doc async for doc in cursor]


async def count_notifications(
    ctx: HarnessContext, *, kind: str, since: datetime | None = None
) -> int:
    user_id = _require_user_id(ctx)
    query: dict[str, Any] = {"user_id": user_id, "original_request.metadata.kind": kind}
    if since is not None:
        query["created_at"] = {"$gte": since}
    return await ctx.db.notifications.count_documents(query)


async def list_notifications(
    ctx: HarnessContext, *, kind: str, since: datetime | None = None
) -> list[dict[str, Any]]:
    user_id = _require_user_id(ctx)
    query: dict[str, Any] = {"user_id": user_id, "original_request.metadata.kind": kind}
    if since is not None:
        query["created_at"] = {"$gte": since}
    cursor = ctx.db.notifications.find(query).sort("created_at", 1)
    return [doc async for doc in cursor]


async def get_user_doc(ctx: HarnessContext) -> dict[str, Any]:
    user_id = _require_user_id(ctx)
    doc = await ctx.db.users.find_one({"_id": ObjectId(user_id)})
    if doc is None:
        raise AssertionError(f"user document vanished for {ctx.email}")
    return doc


async def set_quota_used(ctx: HarnessContext, *, feature: str, count: int) -> None:
    """Force the tiered rate limiter's monthly counter for ``feature`` to
    ``count`` (see ``api/v1/middleware/tiered_rate_limiter.py``).

    ``_get_redis_key`` interpolates the ``RateLimitPeriod`` enum member
    itself into the f-string, not ``.value`` — verified against a live key:
    it renders as the literal ``"RateLimitPeriod.MONTH"``, not ``"month"``.
    """
    user_id = _require_user_id(ctx)
    window = datetime.now(UTC).strftime("%Y%m")
    key = f"rate_limit:{user_id}:{feature}:RateLimitPeriod.MONTH:{window}"
    await ctx.redis.set(key, count, ex=60 * 60 * 24 * 32)
    ctx.log(actor="harness", surface=f"redis:{key}", content=f"SET {count}")


async def _shift_todos(ctx: HarnessContext, user_id: str, delta: timedelta) -> None:
    async for todo in ctx.db.todos.find({"user_id": user_id}):
        todo_updates = {
            key: todo[key] - delta
            for key in _DAY_FIELDS_DATETIME
            if isinstance(todo.get(key), datetime)
        }
        if todo_updates:
            await ctx.db.todos.update_one({"_id": todo["_id"]}, {"$set": todo_updates})


async def _shift_briefings(ctx: HarnessContext, user_id: str, delta: timedelta) -> None:
    # Oldest-first: `briefings` has a unique {user_id, date, kind} index, and
    # shifting a newer doc onto an older doc's still-unshifted date would
    # transiently collide with it. Shifting the oldest doc out of the way
    # first always vacates the slot the next-oldest doc is about to land on.
    async for briefing in ctx.db.briefings.find({"user_id": user_id}).sort("date", 1):
        briefing_updates: dict[str, Any] = {}
        if isinstance(briefing.get("created_at"), datetime):
            briefing_updates["created_at"] = briefing["created_at"] - delta
        if isinstance(briefing.get("opened_at"), datetime):
            briefing_updates["opened_at"] = briefing["opened_at"] - delta
        if isinstance(briefing.get("date"), str):
            shifted = datetime.strptime(briefing["date"], "%Y-%m-%d") - delta
            briefing_updates["date"] = shifted.strftime("%Y-%m-%d")
        if briefing_updates:
            await ctx.db.briefings.update_one({"_id": briefing["_id"]}, {"$set": briefing_updates})


async def _shift_dormancy(ctx: HarnessContext, user_id: str, delta: timedelta) -> None:
    user = await ctx.db.users.find_one({"_id": ObjectId(user_id)})
    if not (user and isinstance(user.get("briefing_dormancy"), dict)):
        return
    marker = user["briefing_dormancy"]
    dormancy_updates: dict[str, Any] = {}
    if isinstance(marker.get("dormant_since"), datetime):
        dormancy_updates["briefing_dormancy.dormant_since"] = marker["dormant_since"] - delta
    if isinstance(marker.get("date"), str):
        shifted = datetime.strptime(marker["date"], "%Y-%m-%d") - delta
        dormancy_updates["briefing_dormancy.date"] = shifted.strftime("%Y-%m-%d")
    if dormancy_updates:
        await ctx.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": dormancy_updates})
        await _invalidate_user_cache(ctx, user_id)


async def advance_day(ctx: HarnessContext, *, days: int = 1) -> None:
    """Simulate elapsed time without waiting: shift this user's stored
    timestamps ``days`` further into the past (Phase-G technique), so the
    next real-time-anchored run treats today's fixtures/actions as
    yesterday's. Bumps ``ctx.day`` for the timeline."""
    user_id = _require_user_id(ctx)
    delta = timedelta(days=days)
    await _shift_todos(ctx, user_id, delta)
    await _shift_briefings(ctx, user_id, delta)
    await _shift_dormancy(ctx, user_id, delta)

    ctx.day += days
    ctx.log(
        actor="harness", surface="mongo:advance_day", content=f"shifted -{days}d, now day {ctx.day}"
    )


# --------------------------------------------------------------- real actions


async def approve_todo(
    ctx: HarnessContext, todo_id: str, *, channel: str = "web", instruction: str | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"channel": channel}
    if instruction is not None:
        body["instruction"] = instruction
    resp = await ctx.http.post(f"/todos/{todo_id}/approve", json=body)
    ctx.log(
        actor=ctx.email,
        surface=f"POST /todos/{todo_id}/approve",
        content=f"-> {resp.status_code} {resp.text[:300]}",
    )
    return resp


async def dismiss_todo(
    ctx: HarnessContext, todo_id: str, *, reason: str | None = None, channel: str = "web"
) -> httpx.Response:
    resp = await ctx.http.post(
        f"/todos/{todo_id}/dismiss", json={"reason": reason, "channel": channel}
    )
    ctx.log(
        actor=ctx.email,
        surface=f"POST /todos/{todo_id}/dismiss",
        content=f"-> {resp.status_code} reason={reason!r}",
    )
    _raise_for_status(ctx, resp, "POST /todos/{id}/dismiss")
    return resp


async def answer_todo(
    ctx: HarnessContext, todo_id: str, answer: str, *, channel: str = "web"
) -> httpx.Response:
    resp = await ctx.http.post(
        f"/todos/{todo_id}/answer", json={"answer": answer, "channel": channel}
    )
    ctx.log(
        actor=ctx.email,
        surface=f"POST /todos/{todo_id}/answer",
        content=f"-> {resp.status_code} answer={answer!r}",
    )
    _raise_for_status(ctx, resp, "POST /todos/{id}/answer")
    return resp


async def force_complete_todo(ctx: HarnessContext, todo_id: str) -> None:
    """Force a GAIA todo straight to ``done`` via Mongo — the explicitly
    sanctioned shortcut for capstone days where a real executor run would be
    too slow/flaky (mission brief: real execution required on day 1 only)."""
    await update_todo(
        ctx,
        todo_id,
        execution_status="done",
        completed=True,
        completed_at=datetime.now(UTC),
        log_content="force-completed by persona harness",
    )


async def trigger_briefing(ctx: HarnessContext, *, kind: str = "daily") -> httpx.Response:
    resp = await ctx.http.post(f"/dev/briefing/{kind}/{ctx.email}")
    ctx.log(
        actor="cron",
        surface=f"POST /dev/briefing/{kind}/{ctx.email}",
        content=f"-> {resp.status_code}",
    )
    _raise_for_status(ctx, resp, "POST /dev/briefing/{kind}/{email}")
    return resp


async def run_executor_task(
    ctx: HarnessContext, *, sim_task: str, agent_task: str, conversation_id: str | None = None
) -> dict[str, Any]:
    """Run a task on the executor directly (skips comms). Under ``--sim`` the
    task must carry ``[[tool:...]]`` directives; under a real LLM lane it is
    plain natural-language instruction."""
    task = sim_task if ctx.sim else agent_task
    body: dict[str, Any] = {"email": ctx.email, "task": task}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    resp = await ctx.http.post("/dev/executor", json=body)
    _raise_for_status(ctx, resp, "POST /dev/executor")
    data = resp.json()
    ctx.log(
        actor=ctx.email,
        surface="POST /dev/executor",
        content=f"task={task!r} -> {data['message']!r}",
    )
    return data


async def chat_turn(ctx: HarnessContext, message: str) -> str:
    """One user chat turn through the real comms front door; returns the
    concatenated SSE text deltas."""
    text_parts: list[str] = []
    # MessageRequestWithHistory requires both the top-level `message` (this
    # turn's text) and `messages` (history incl. this turn) — see
    # app/models/message_models.py. The driving-gaia skill's curl example
    # only sends `messages` and 422s; don't copy it verbatim.
    async with ctx.http.stream(
        "POST",
        "/chat-stream",
        json={"message": message, "messages": [{"role": "user", "content": message}]},
    ) as resp:
        if resp.status_code >= 400:
            body = await resp.aread()
            raise AssertionError(
                f"POST /chat-stream for {ctx.email} returned {resp.status_code}: {body[:500]!r}"
            )
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                continue
            # Every SSE frame is one JSON object keyed by frame type (no
            # discriminator field) — see app/models/stream_events.py. The
            # assistant's actual text deltas are the frames whose only key is
            # "response" (app/utils/agent_utils.py format_sse_response());
            # everything else (conversation-init, tool_data, reasoning,
            # progress, main_response_complete, ...) is metadata to skip.
            event = json.loads(payload)
            if isinstance(event, dict) and "response" in event:
                text_parts.append(str(event["response"]))
    reply = "".join(text_parts)
    ctx.log(actor=ctx.email, surface="POST /chat-stream", content=f"{message!r} -> {reply[:300]!r}")
    return reply


async def provision_briefing_workflow(ctx: HarnessContext) -> None:
    """Run the real existing-user provisioning step for this one user
    (``app/services/system_workflows/provisioner.py`` via
    ``app/services/briefing/rollout.py``) — the same code
    ``scripts/provision_daily_briefings.py`` runs as a backfill. Dev seed does
    NOT provision briefing workflows, so any persona that needs a live
    ``daily_briefing`` system workflow must call this explicitly."""
    user_id = _require_user_id(ctx)
    script = (
        "import asyncio\n"
        "from app.core.provider_registration import unified_startup\n"
        "from app.services.briefing.rollout import provision_existing_user\n"
        "async def main() -> None:\n"
        "    await unified_startup('arq_worker')\n"
        f"    await provision_existing_user({user_id!r})\n"
        "asyncio.run(main())\n"
    )
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "python",
        "-c",
        script,
        cwd=str(API_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        raise AssertionError(f"provision_existing_user failed:\n{stdout.decode()[-3000:]}")
    ctx.log(actor="harness", surface="subprocess:provision_existing_user", content=user_id)


async def get_daily_briefing_workflow(ctx: HarnessContext) -> dict[str, Any]:
    user_id = _require_user_id(ctx)
    doc = await ctx.db.workflows.find_one(
        {"user_id": user_id, "system_workflow_key": "daily_briefing"}
    )
    if doc is None:
        raise AssertionError(f"no daily_briefing workflow provisioned for {ctx.email}")
    return doc


def streak_from_completions(completed_dates_local: list[date], today_local: date) -> int:
    """Independent re-derivation of ``activity.streak_from_counts`` (see
    ``app/services/todos/activity.py``) from raw local completion dates, so the
    harness can assert the honest streak length without any LLM in the loop."""
    days_with_completion = set(completed_dates_local)
    streak = 0
    offset = 0
    while True:
        day = today_local - timedelta(days=offset)
        if day in days_with_completion:
            streak += 1
        elif offset != 0:
            break
        offset += 1
    return streak
