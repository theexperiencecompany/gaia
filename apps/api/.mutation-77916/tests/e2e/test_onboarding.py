"""Onboarding as the user actually experiences it: submit, watch, finish, reset.

The flow spans five layers that no test crossed together — the endpoints, the
service gate, the ARQ job lifecycle, the intelligence DAG, and the second job
that finishes the split (Gmail) shape. The unit suites underneath fake every
node at its own boundary, so orchestration is asserted in isolation and the
seams between layers are asserted nowhere. Two of the functions the user's data
depends on most had no test at all: ``submit_onboarding_integrations`` (which
decides whether a second pipeline starts) and ``reset_onboarding`` (which
deletes workflows, todos, conversations, integrations and memories, and aborts
whatever is still running).

What that costs when it breaks is invisible. Every stage is a fire-and-forget
WebSocket emit wrapped in ``try/except``, every node runs under ``_safe_run``,
and both ARQ tasks swallow their own failure and mark the phase complete anyway.
So a broken pipeline does not error — it produces an onboarding that finishes
with no todos, no workflows, no first message, and a reveal screen that shows
defaults. A double-submit produces something worse: two pipelines emitting
interleaved stages onto the same socket, which the frontend's stage cursor
cannot untangle.

**What is real here.** The HTTP endpoints, ``onboarding_service``,
``intelligence_job``, both ARQ task wrappers, and the whole
``intelligence_service`` DAG including every stage emit and the branch
selection. ARQ is real too: jobs are enqueued onto a real ``ArqRedis`` (backed
by fakeredis), read back off the queue by ``run_queued_jobs`` exactly as the
worker does, and aborts land in arq's real ``abort`` sorted set — so "the job is
live" and "the job was aborted" are answered by arq, not by a mock.

**What is doubled.** Only external I/O: the LLM, Gmail, Composio, and the
persistence layer. ``_UserStore`` stands in for Mongo and mirrors three
conditional repository contracts — the ``onboarding: {$exists: false}`` gate,
compare-and-clear on the job id, and set-social-profiles-if-unset — each of
which is certified against real Mongo in ``tests/contracts/test_users_repository.py``.
The tests below assert what the *services* do with each outcome, which is the
part no other test covers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import Any
from unittest.mock import AsyncMock, patch

from arq.connections import ArqRedis
from arq.constants import abort_jobs_ss, default_queue_name, job_key_prefix
from arq.jobs import Job
import fakeredis.aioredis
from httpx import AsyncClient
from langchain_core.messages import AIMessage
import pytest

from app.constants.onboarding import (
    INTELLIGENCE_TASK,
    WORKFLOWS_TASK,
)
from app.models.onboarding_models import (
    EmailSummary,
    InboxTriageOutput,
    SocialProfile,
    WritingStyleExampleBlocks,
    WritingStyleOutput,
)
from app.models.user_models import OnboardingIntegrationsStatus, OnboardingPhase, UserDocument
from app.models.workflow_models import SuggestedTrigger, TriggerConfig, TriggerType
from app.services.onboarding import intelligence_service
from app.services.onboarding.intelligence_service import (
    OnboardingStage,
    _FocusTodoList,
    _TodoListFromEmails,
    _TodoSpec,
    _WorkflowList,
    _WorkflowSpec,
)
from app.utils.redis_utils import RedisPoolManager
from app.workers.tasks.onboarding_tasks import (
    process_onboarding_intelligence_task,
    process_onboarding_workflows_task,
)
from tests.conftest import FAKE_USER

pytestmark = pytest.mark.e2e

USER_ID: str = FAKE_USER["user_id"]

#: The sender the triage LLM reports as important. Todo specs that cite it keep
#: their ``source_email``; anything else is dropped as hallucinated.
REAL_SENDER = "priya@client.com"
REAL_SUBJECT = "Contract redlines"

SUBMIT = "/api/v1/onboarding"
INTEGRATIONS = "/api/v1/onboarding/integrations"
RESET = "/api/v1/onboarding/reset"
STATUS = "/api/v1/onboarding/status"
PERSONALIZATION = "/api/v1/onboarding/personalization"


# ---------------------------------------------------------------------------
# Mongo stand-in
# ---------------------------------------------------------------------------


class _UserStore:
    """The user collection, in process.

    Only the named methods the onboarding flow calls are implemented, under the
    repository's own names, so production code is unchanged. The three methods
    whose real semantics live in a Mongo filter rather than in Python —
    ``complete_onboarding``'s existence gate, ``clear_active_job_if_matches``'s
    compare-and-clear, and ``set_social_profiles_if_unset`` — are reproduced
    here; each is certified against real Mongo by the repository contract suite.
    """

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    # -- helpers ----------------------------------------------------------
    def seed(self, user_id: str, **fields: Any) -> None:
        self.docs[user_id] = {
            "id": user_id,
            "email": "test@example.com",
            "name": "Test User",
            "timezone": "UTC",
            "created_at": datetime.now(UTC),
            **fields,
        }

    def onboarding_of(self, user_id: str) -> dict[str, Any]:
        return deepcopy(self.docs[user_id].get("onboarding") or {})

    def first_message_of(self, user_id: str) -> str | None:
        """Read straight through, for the stage sink's mid-flight snapshots."""
        return (self.docs.get(user_id, {}).get("onboarding") or {}).get("first_message")

    def _sub(self, user_id: str) -> dict[str, Any] | None:
        doc = self.docs.get(user_id)
        if doc is None:
            return None
        return doc.setdefault("onboarding", {})

    # -- reads ------------------------------------------------------------
    async def get(self, user_id: str) -> UserDocument | None:
        doc = self.docs.get(user_id)
        return UserDocument.model_validate(deepcopy(doc)) if doc else None

    async def count_created_before(self, created_at: datetime) -> int:
        return sum(
            1 for d in self.docs.values() if d.get("created_at") and d["created_at"] < created_at
        )

    # -- onboarding lifecycle ---------------------------------------------
    async def complete_onboarding(self, user_id: str, **fields: Any) -> UserDocument | None:
        doc = self.docs.get(user_id)
        if doc is None or "onboarding" in doc:
            return None
        if fields.get("name") is not None:
            doc["name"] = fields["name"]
        if fields.get("timezone") is not None:
            doc["timezone"] = fields["timezone"]
        sub: dict[str, Any] = {
            "completed": True,
            "completed_at": datetime.now(UTC),
            "phase": fields["phase"],
            "bio_status": fields["bio_status"],
            "pipeline_mode": fields["pipeline_mode"],
            "preferences": fields["preferences"].model_dump(),
        }
        for key in ("focus", "clarify_answers", "selected_integrations"):
            if fields.get(key) is not None:
                sub[key] = fields[key]
        doc["onboarding"] = sub
        return await self.get(user_id)

    async def clear_onboarding(self, user_id: str) -> None:
        self.docs.get(user_id, {}).pop("onboarding", None)

    async def reset_onboarding(self, user_id: str) -> None:
        self.docs.get(user_id, {}).pop("onboarding", None)

    async def set_selected_integrations(self, user_id: str, integrations: list[str]) -> None:
        sub = self._sub(user_id)
        if sub is not None:
            sub["selected_integrations"] = integrations

    async def set_onboarding_phase(self, user_id: str, phase: OnboardingPhase) -> bool:
        sub = self._sub(user_id)
        if sub is None:
            return False
        sub["phase"] = phase
        return True

    # -- job slots ---------------------------------------------------------
    async def set_active_job(self, user_id: str, field_path: str, job_id: str) -> None:
        sub = self._sub(user_id)
        if sub is not None:
            sub[field_path.removeprefix("onboarding.")] = job_id

    async def clear_active_job(self, user_id: str, field_path: str) -> None:
        sub = self._sub(user_id)
        if sub is not None:
            sub.pop(field_path.removeprefix("onboarding."), None)

    async def clear_active_job_if_matches(self, user_id: str, field_path: str, job_id: str) -> None:
        sub = self._sub(user_id)
        key = field_path.removeprefix("onboarding.")
        if sub is not None and sub.get(key) == job_id:
            sub.pop(key)

    # -- pipeline writes ---------------------------------------------------
    async def set_pipeline_completion(
        self, user_id: str, *, phase: OnboardingPhase, conversation_id: str | None = None
    ) -> None:
        sub = self._sub(user_id)
        if sub is None:
            return
        sub["phase"] = phase
        if conversation_id is not None:
            sub["first_message_conversation_id"] = conversation_id

    async def set_first_message(self, user_id: str, first_message: str) -> None:
        sub = self._sub(user_id)
        if sub is not None:
            sub["first_message"] = first_message

    async def mark_early_intelligence_done(self, user_id: str) -> None:
        sub = self._sub(user_id)
        if sub is not None:
            sub["early_intelligence_done_at"] = datetime.now(UTC)

    async def set_suggested_workflows(self, user_id: str, workflow_ids: list[str]) -> None:
        sub = self._sub(user_id)
        if sub is not None:
            sub["suggested_workflows"] = workflow_ids

    async def set_social_profiles_if_unset(
        self, user_id: str, profiles: list[SocialProfile]
    ) -> None:
        sub = self._sub(user_id)
        if sub is not None and not sub.get("social_profiles"):
            sub["social_profiles"] = [p.model_dump() for p in profiles]

    async def set_writing_style_and_triage(
        self,
        user_id: str,
        *,
        writing_style_summary: str | None = None,
        writing_style_example: WritingStyleExampleBlocks | None = None,
        triage_summary: Any = None,
    ) -> None:
        sub = self._sub(user_id)
        if sub is None:
            return
        if writing_style_summary is not None or writing_style_example is not None:
            style = sub.setdefault("writing_style", {})
            if writing_style_summary is not None:
                style["summary"] = writing_style_summary
            if writing_style_example is not None:
                style["example"] = writing_style_example.model_dump()
        if triage_summary is not None:
            sub["triage_summary"] = triage_summary.model_dump()

    async def save_personalization(self, user_id: str, **fields: Any) -> None:
        sub = self._sub(user_id)
        if sub is not None:
            sub.update({k: v for k, v in fields.items() if k != "workflow_ids"})


# ---------------------------------------------------------------------------
# Stage recorder
# ---------------------------------------------------------------------------


class _StageSink:
    """Every ``onboarding_stage`` event the socket would have carried, in order.

    Also snapshots the user document at the instant each stage goes out, and can
    hold a stage open. Both exist because ordering claims are otherwise
    unfalsifiable here: a write that moves to after its stage still leaves the
    right value behind by the time the test looks, and an emit that stops being
    awaited still tends to land first when nothing in the pipeline does real I/O.
    """

    def __init__(self, users: _UserStore) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.entered: list[str] = []
        self.first_message_at: dict[str, str | None] = {}
        self._users = users
        self._gates: dict[str, asyncio.Event] = {}

    def hold(self, stage: OnboardingStage) -> asyncio.Event:
        """Make the socket block on ``stage`` until the returned event is set."""
        gate = asyncio.Event()
        self._gates[stage.value] = gate
        return gate

    async def broadcast_to_user(self, *, user_id: str, message: dict[str, Any]) -> None:
        if message.get("type") != "onboarding_stage":
            return
        data = message["data"]
        stage = data["stage"]
        self.entered.append(stage)
        gate = self._gates.get(stage)
        if gate is not None:
            await gate.wait()
        self.events.append((stage, data["payload"]))
        self.first_message_at[stage] = self._users.first_message_of(user_id)

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def payload(self, stage: OnboardingStage) -> dict[str, Any]:
        """The last payload emitted for ``stage`` — the one the client keeps."""
        for name, payload in reversed(self.events):
            if name == stage.value:
                return payload
        raise AssertionError(f"{stage.value} never emitted; got {self.names}")

    def emitted(self, stage: OnboardingStage) -> bool:
        return stage.value in self.names

    def index(self, stage: OnboardingStage) -> int:
        return self.names.index(stage.value)


# ---------------------------------------------------------------------------
# External-service doubles
# ---------------------------------------------------------------------------


@dataclass
class _Externals:
    """Everything outside the process, recorded."""

    has_gmail: bool = False
    #: When set, the Composio round trip blocks on it — the only way to observe
    #: what the user's screen shows *while* that call is outstanding.
    composio_gate: asyncio.Event | None = None
    inbox: list[dict[str, Any]] = field(default_factory=list)
    sent_emails: list[dict[str, Any]] = field(default_factory=list)
    llm_labels: list[str] = field(default_factory=list)
    llm_prompts: dict[str, str] = field(default_factory=dict)
    llm_failures: set[str] = field(default_factory=set)
    workflows_created: list[str] = field(default_factory=list)
    workflow_timezones: list[str] = field(default_factory=list)
    todos_created: list[str] = field(default_factory=list)
    workflows_deleted: list[str] = field(default_factory=list)
    workflow_delete_error: str | None = None
    seeded_conversation_id: str | None = "conv-seeded"
    integrations_connected: list[str] = field(default_factory=list)
    disconnected: list[str] = field(default_factory=list)
    memories_cleared: int = 0
    todos_purged: int = 0
    demo_conversations: int = 0
    conversation_deleted: bool = True
    provisioned: list[str] = field(default_factory=list)
    memory_jobs: list[str] = field(default_factory=list)
    seeded_users: list[str] = field(default_factory=list)
    purged_workflow_ids: list[list[str]] = field(default_factory=list)


def _gmail_message(idx: int) -> dict[str, Any]:
    return {
        "id": f"msg-{idx}",
        "sender": REAL_SENDER if idx == 0 else f"person{idx}@example.com",
        "subject": REAL_SUBJECT if idx == 0 else f"Subject {idx}",
        "snippet": "Please take a look before Friday." * 2,
        "body": "Hi there, please take a look at the attached before Friday. Thanks!",
        "is_unread": idx % 2 == 0,
        "labelIds": ["IMPORTANT"],
    }


def _sent_email(idx: int) -> dict[str, Any]:
    """A sent message long enough to survive the writing-style sampler's filters."""
    return {
        "subject": f"Re: thread {idx}",
        "body": "Thanks for the update — I'll take a look today and come back to you.",
    }


def _structured_result(schema: type, ext: _Externals) -> Any:
    """A valid instance of whatever schema the caller asked the model for."""
    if schema is WritingStyleOutput:
        return WritingStyleOutput(
            summary="Direct and warm; short paragraphs, signs off with 'Cheers'.",
            example=WritingStyleExampleBlocks(
                greeting="Hey,", body=["Sending the draft over."], signoff="Cheers", name="Test"
            ),
        )
    if schema is InboxTriageOutput:
        return InboxTriageOutput(
            summary="Two threads need a reply today.",
            important_emails=[
                EmailSummary(
                    sender=REAL_SENDER,
                    subject=REAL_SUBJECT,
                    why_important="Blocking the deal",
                )
            ],
            patterns=["Most mail arrives before noon"],
        )
    if schema is _TodoListFromEmails:
        return _TodoListFromEmails(
            todos=[
                _TodoSpec(
                    title="Reply to the contract redlines",
                    description="Draft a response to the outstanding redlines.",
                    source_sender=REAL_SENDER,
                    source_subject=REAL_SUBJECT,
                ),
                _TodoSpec(
                    title="Summarize this week's invoices",
                    description="Pull the invoice threads into one summary.",
                    source_sender="ghost@nowhere.com",
                    source_subject="Never sent",
                ),
            ]
        )
    if schema is _FocusTodoList:
        return _FocusTodoList(todos=["Draft the Q3 plan", "Chase the pending signature"])
    if schema is _WorkflowList:
        return _WorkflowList(
            workflows=[
                _WorkflowSpec(
                    title=f"Workflow {n}",
                    description=f"Does thing {n} every morning.",
                    categories=["gmail"] if n == 1 else ["todos"],
                )
                for n in range(1, 5)
            ]
        )
    raise AssertionError(f"no scripted result for {schema!r}")


class _FakeWorkflow:
    def __init__(self, workflow_id: str) -> None:
        self.id = workflow_id
        self.steps: list[dict[str, Any]] = []
        self.trigger_config = TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")


class _FakeTodo:
    def __init__(self, todo_id: str) -> None:
        self.id = todo_id


@pytest.fixture
def externals() -> _Externals:
    return _Externals()


@pytest.fixture
def users() -> _UserStore:
    store = _UserStore()
    store.seed(USER_ID)
    return store


@pytest.fixture
async def arq_pool() -> Any:
    """A real ArqRedis on fakeredis, installed as the process pool.

    Real arq rather than a mock because job *liveness* is a branch of the code
    under test: ``submit_onboarding_integrations`` asks arq whether the previous
    workflows job is still running, and ``reset_onboarding`` asks arq to abort it.
    """
    fake = fakeredis.aioredis.FakeRedis()
    pool = ArqRedis(connection_pool=fake.connection_pool)
    previous = RedisPoolManager._pool
    RedisPoolManager._pool = pool
    yield pool
    RedisPoolManager._pool = previous
    await fake.aclose()


@pytest.fixture
def stages(users: _UserStore) -> _StageSink:
    return _StageSink(users)


@pytest.fixture(autouse=True)
def world(
    users: _UserStore,
    stages: _StageSink,
    externals: _Externals,
    arq_pool: ArqRedis,
) -> Iterator[None]:
    """Wire the store, the socket and every external service into the real flow."""
    svc = "app.services.onboarding"

    async def _check_connection(slugs: list[str], _user_id: str) -> dict[str, bool]:
        if externals.composio_gate is not None:
            await externals.composio_gate.wait()
        return {slug: (slug == "gmail" and externals.has_gmail) for slug in slugs}

    composio = AsyncMock()
    composio.check_connection_status.side_effect = _check_connection

    async def _fetch_emails(
        user_id: str,
        months: int = 1,
        batch_size: int = 100,
        max_total: int = 100,
        on_batch: Callable[[int, str | None], Awaitable[None]] | None = None,
        fmt: str = "metadata",
        into: list[dict[str, Any]] | None = None,
        include_sent: bool = False,
    ) -> list[dict[str, Any]]:
        batch = list(externals.inbox)
        if into is not None:
            into.extend(batch)
        if on_batch is not None:
            await on_batch(len(batch), batch[0]["sender"] if batch else None)
        return batch

    async def _structured(schema: type, prompt: Any, *, label: str, **_: Any) -> Any:
        externals.llm_labels.append(label)
        externals.llm_prompts[label] = str(prompt)
        if label in externals.llm_failures:
            raise RuntimeError(f"model refused: {label}")
        return _structured_result(schema, externals)

    async def _invoke_llm(_runnable: Any, messages: Any, *, label: str = "model", **_: Any) -> Any:
        externals.llm_labels.append(label)
        externals.llm_prompts[label] = str(messages)
        if label in externals.llm_failures:
            raise RuntimeError(f"model refused: {label}")
        return AIMessage(content="Hey, you're all set.")

    async def _search_messages(**_: Any) -> Any:
        result = AsyncMock()
        result.messages = externals.sent_emails
        return result

    async def _create_workflow(
        request: Any, _user_id: str, user_timezone: str = "UTC", **_: Any
    ) -> _FakeWorkflow:
        externals.workflows_created.append(request.title)
        externals.workflow_timezones.append(user_timezone)
        return _FakeWorkflow(f"wf-{len(externals.workflows_created)}")

    async def _delete_workflow(workflow_id: str, _user_id: str) -> bool:
        if externals.workflow_delete_error == workflow_id:
            raise RuntimeError("composio trigger teardown failed")
        externals.workflows_deleted.append(workflow_id)
        return True

    async def _generate_prompt(**_: Any) -> dict[str, Any]:
        return {
            "prompt": "Do the thing.",
            "suggested_trigger": SuggestedTrigger(type="schedule", cron_expression="0 8 * * *"),
        }

    async def _create_todo(todo: Any, _user_id: str) -> _FakeTodo:
        externals.todos_created.append(todo.title)
        return _FakeTodo(f"todo-{len(externals.todos_created)}")

    async def _list_onboarding_todos(_user_id: str, limit: int = 3) -> list[Any]:
        todos = []
        for idx, title in enumerate(externals.todos_created[:limit], start=1):
            todo = AsyncMock()
            todo.id = f"todo-{idx}"
            todo.title = title
            todo.description = None
            todo.source_email = None
            todos.append(todo)
        return todos

    async def _seed_conversation(**_: Any) -> str | None:
        return externals.seeded_conversation_id

    async def _seed_user_data(user_id: str) -> None:
        externals.seeded_users.append(user_id)

    async def _purge_workflows(workflow_ids: list[str], _user_id: str) -> int:
        externals.purged_workflow_ids.append(list(workflow_ids))
        return len(workflow_ids)

    async def _provision(user_id: str, slug: str, *_args: Any, **_kw: Any) -> None:
        externals.provisioned.append(slug)

    async def _list_user_integrations(_user_id: str) -> list[Any]:
        out = []
        for slug in externals.integrations_connected:
            entry = AsyncMock()
            entry.integration_id = slug
            out.append(entry)
        return out

    async def _disconnect(_user_id: str, integration_id: str) -> None:
        externals.disconnected.append(integration_id)

    todo_repo = AsyncMock()
    todo_repo.delete_onboarding_todos.side_effect = lambda _uid: externals.todos_purged
    todo_repo.list_onboarding_todos.side_effect = _list_onboarding_todos

    conversation_repo = AsyncMock()
    conversation_repo.delete.side_effect = lambda _cid, user_id: externals.conversation_deleted
    conversation_repo.delete_onboarding_demos.side_effect = lambda _uid: (
        externals.demo_conversations
    )

    integrations_repo = AsyncMock()
    integrations_repo.list_for_user.side_effect = _list_user_integrations

    memory = AsyncMock()
    memory.delete_all.side_effect = lambda _uid: externals.memories_cleared

    patches = [
        # --- persistence -------------------------------------------------
        patch(f"{svc}.onboarding_service.user_repository", users),
        patch(f"{svc}.intelligence_job.user_repository", users),
        patch(f"{svc}.intelligence_service.user_repository", users),
        patch(f"{svc}.post_onboarding_service.user_repository", users),
        patch("app.workers.tasks.onboarding_tasks.user_repository", users),
        patch("app.api.v1.endpoints.onboarding.user_repository", users),
        patch(f"{svc}.onboarding_service.todo_repository", todo_repo),
        patch(f"{svc}.intelligence_job.todo_repository", todo_repo),
        patch(f"{svc}.intelligence_service.todo_repository", todo_repo),
        patch("app.api.v1.endpoints.onboarding.todo_repository", todo_repo),
        patch("app.api.v1.endpoints.onboarding.workflow_repository", AsyncMock()),
        patch(
            f"{svc}.intelligence_service.workflow_repository.delete_many_for_user", _purge_workflows
        ),
        patch(f"{svc}.onboarding_service.conversation_repository", conversation_repo),
        patch(f"{svc}.onboarding_service.user_integration_repository", integrations_repo),
        patch(f"{svc}.onboarding_service.memory_engine", memory),
        patch(f"{svc}.onboarding_service.disconnect_integration", _disconnect),
        # --- transport ---------------------------------------------------
        patch(f"{svc}.intelligence_service.websocket_manager", stages),
        # --- composio ----------------------------------------------------
        patch(f"{svc}.intelligence_service.get_composio_service", lambda: composio),
        patch("app.api.v1.endpoints.onboarding.get_composio_service", lambda: composio),
        # --- gmail -------------------------------------------------------
        patch(f"{svc}.intelligence_service.fetch_emails_for_onboarding", _fetch_emails),
        patch(f"{svc}.writing_style_service.search_messages", _search_messages),
        patch(f"{svc}.intelligence_service.inbox_scan_cache.get", AsyncMock(return_value=None)),
        patch(f"{svc}.intelligence_service.inbox_scan_cache.put", AsyncMock()),
        patch(
            f"{svc}.intelligence_service.extract_social_profiles_from_emails",
            AsyncMock(return_value=[SocialProfile(platform="linkedin", url="https://li/x")]),
        ),
        # --- llm ---------------------------------------------------------
        patch(f"{svc}.intelligence_service.ainvoke_structured", _structured),
        patch(f"{svc}.writing_style_service.ainvoke_structured", _structured),
        patch(f"{svc}.inbox_triage_service.ainvoke_structured", _structured),
        patch(f"{svc}.first_message_service.ainvoke_llm", _invoke_llm),
        patch(f"{svc}.first_message_service.get_helper_llm", lambda **_: AsyncMock()),
        # --- downstream services ----------------------------------------
        patch(f"{svc}.intelligence_service.WorkflowService.create_workflow", _create_workflow),
        patch(f"{svc}.onboarding_service.WorkflowService.delete_workflow", _delete_workflow),
        patch(
            f"{svc}.intelligence_service.WorkflowGenerationService.generate_workflow_prompt",
            _generate_prompt,
        ),
        patch(
            f"{svc}.intelligence_service.compute_missing_integrations", AsyncMock(return_value=[])
        ),
        patch(f"{svc}.intelligence_service.TodoService.create_todo", _create_todo),
        patch(f"{svc}.intelligence_service.seed_onboarding_conversation", _seed_conversation),
        patch(f"{svc}.intelligence_service.provision_system_workflows", _provision),
        patch(f"{svc}.post_onboarding_service.seed_onboarding_todo", _seed_user_data),
        patch(
            f"{svc}.intelligence_service.generate_holo_card_content",
            AsyncMock(return_value=("Curious Adventurer", "A bio.", "completed")),
        ),
    ]
    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        yield


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------

#: The two onboarding tasks a real worker would pick up. Anything else the
#: pipeline enqueues (gmail -> memory ingestion) is recorded, not run.
_TASKS: dict[str, Any] = {
    INTELLIGENCE_TASK: process_onboarding_intelligence_task,
    WORKFLOWS_TASK: process_onboarding_workflows_task,
}


async def run_queued_jobs(pool: ArqRedis, externals: _Externals) -> list[str]:
    """Drain the arq queue through the real task functions, worker-style.

    Reads the queued job ids off the real sorted set and deserializes each one
    with arq itself, so the task name and arguments under test are the ones that
    were actually enqueued — not ones the test supplied.
    """
    ran: list[str] = []
    for _ in range(4):  # a job may enqueue another; bounded so a loop cannot hang
        queued = await pool.zrange(default_queue_name, 0, -1)
        if not queued:
            break
        for raw in queued:
            job_id = raw.decode() if isinstance(raw, bytes) else raw
            info = await Job(job_id, redis=pool).info()
            assert info is not None, f"queued job {job_id} has no definition"
            await pool.zrem(default_queue_name, job_id)
            await pool.delete(job_key_prefix + job_id)
            if info.function in _TASKS:
                ran.append(info.function)
                await _TASKS[info.function]({"job_id": job_id}, *info.args)
            else:
                externals.memory_jobs.append(info.function)
    return ran


async def drop_queued_jobs(pool: ArqRedis) -> None:
    """Discard whatever is queued without running it — a worker that died."""
    for raw in await pool.zrange(default_queue_name, 0, -1):
        job_id = raw.decode() if isinstance(raw, bytes) else raw
        await pool.zrem(default_queue_name, job_id)
        await pool.delete(job_key_prefix + job_id)


async def wait_for_stages(stages: _StageSink, count: int, timeout: float = 3.0) -> list[str]:
    """The first ``count`` stages to reach the socket, or fail saying what did."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(stages.entered) >= count:
            return list(stages.entered[:count])
        await asyncio.sleep(0.005)
    raise AssertionError(f"only {stages.entered} reached the socket within {timeout}s")


async def wait_for_stage(stages: _StageSink, stage: OnboardingStage, timeout: float = 3.0) -> None:
    """Block until ``stage`` reaches the socket. Bounded: a change that stops it
    being emitted at all has to fail the test, not hang the run."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stage.value in stages.entered:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"{stage.value} never reached the socket; got {stages.entered}")


async def queued_job_names(pool: ArqRedis) -> list[str]:
    names = []
    for raw in await pool.zrange(default_queue_name, 0, -1):
        job_id = raw.decode() if isinstance(raw, bytes) else raw
        info = await Job(job_id, redis=pool).info()
        if info is not None:
            names.append(info.function)
    return names


#: A filled-in no-Gmail follow-up, shaped as the clarify endpoint returns it.
CLARIFY_ANSWERS: list[dict[str, Any]] = [
    {
        "id": "scope",
        "kind": "scope",
        "question": "What are you working on right now?",
        "value": "Migrating the billing stack",
    }
]


def submit_body(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Test User",
        "profession": "Lawyer",
        "timezone": "UTC",
        "focus": "close the Q3 deals",
        **overrides,
    }


async def complete_submit(client: AsyncClient, **overrides: Any) -> Any:
    return await client.post(SUBMIT, json=submit_body(**overrides))


# ---------------------------------------------------------------------------
# POST /onboarding
# ---------------------------------------------------------------------------


class TestSubmitStartsExactlyOnePipeline:
    async def test_a_submission_queues_the_intelligence_job(
        self, client: AsyncClient, arq_pool: ArqRedis, users: _UserStore
    ):
        """Nothing else starts the pipeline. If the enqueue is lost the user sits
        on the loading screen forever — there is no retry and no error."""
        response = await complete_submit(client)

        assert response.status_code == 200
        assert await queued_job_names(arq_pool) == [INTELLIGENCE_TASK]
        assert users.onboarding_of(USER_ID)["intelligence_job_id"]

    async def test_a_double_submit_queues_only_one_pipeline(
        self, client: AsyncClient, arq_pool: ArqRedis
    ):
        """Two pipelines on one socket interleave their stage events and the
        frontend's stage cursor cannot untangle them. The atomic gate is what
        makes the second POST a replay instead of a second run."""
        first = await complete_submit(client)
        second = await complete_submit(client)

        assert first.status_code == 200
        assert second.status_code == 200
        assert await queued_job_names(arq_pool) == [INTELLIGENCE_TASK]

    async def test_a_replayed_submit_still_returns_the_stored_user(self, client: AsyncClient):
        """The frontend advances on this payload. Returning an error or an empty
        body on a retried request would strand a user whose first POST landed."""
        await complete_submit(client)

        response = await complete_submit(client, name="Someone Else")

        assert response.json()["user"]["user_id"] == USER_ID
        assert response.json()["user"]["name"] == "Test User"

    async def test_a_replay_does_not_reseed_initial_data(
        self, client: AsyncClient, externals: _Externals
    ):
        """The starter todo is seeded by a background task on the winning submit.
        Firing it again on a retried request gives the user duplicates of the
        first thing they ever see in their todo list."""
        await complete_submit(client)
        await complete_submit(client)

        assert externals.seeded_users == [USER_ID]

    async def test_the_submitted_choices_are_what_the_pipeline_reads(
        self, client: AsyncClient, users: _UserStore
    ):
        """Everything the form collects has to survive the write, because the
        pipeline reads it back from the document and nothing re-asks the user."""
        response = await complete_submit(
            client,
            selected_integrations=["slack", "slack", "notion"],
            defer_workflows=True,
            timezone="Europe/London",
            clarify_answers=CLARIFY_ANSWERS,
        )

        assert response.status_code == 200
        onboarding = users.onboarding_of(USER_ID)
        assert onboarding["selected_integrations"] == ["slack", "notion"]
        assert onboarding["pipeline_mode"] == "split"
        assert onboarding["focus"] == "close the Q3 deals"
        assert onboarding["clarify_answers"] == CLARIFY_ANSWERS
        assert users.docs[USER_ID]["timezone"] == "Europe/London"

    async def test_the_submitted_timezone_is_what_workflows_are_scheduled_in(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals
    ):
        """Dropped, every workflow silently schedules in UTC — a 9am briefing
        that arrives in the middle of the user's night."""
        await complete_submit(client, timezone="Asia/Kolkata")
        await run_queued_jobs(arq_pool, externals)

        assert externals.workflow_timezones == ["Asia/Kolkata"] * 4

    async def test_the_clarify_answers_reach_the_greeting(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals
    ):
        """These are the only thing a no-Gmail user told us beyond their focus —
        exactly the users this path serves. Dropped, the greeting is written as
        if they never answered the follow-up questions at all."""
        await complete_submit(client, clarify_answers=CLARIFY_ANSWERS)
        await run_queued_jobs(arq_pool, externals)

        assert "Migrating the billing stack" in externals.llm_prompts["onboarding_first_message"]

    async def test_a_failed_enqueue_rolls_the_submission_back(
        self, client: AsyncClient, users: _UserStore
    ):
        """A user whose job never queued must be able to submit again. Leaving the
        subdoc behind makes every retry a replay of a pipeline that never ran —
        the loading screen never resolves."""
        with patch.object(
            RedisPoolManager, "get_pool", AsyncMock(side_effect=RuntimeError("redis down"))
        ):
            failed = await complete_submit(client)

        assert failed.status_code == 503
        assert "onboarding" not in users.docs[USER_ID]

        retry = await complete_submit(client)
        assert retry.status_code == 200

    async def test_an_unknown_user_is_a_404_not_a_500(self, client: AsyncClient, users: _UserStore):
        users.docs.clear()

        response = await complete_submit(client)

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# The full (no-Gmail) pipeline
# ---------------------------------------------------------------------------


class TestTheFullPipelineFinishes:
    @pytest.fixture(autouse=True)
    async def _run(self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals):
        await complete_submit(client, selected_integrations=["notion"])
        self.ran = await run_queued_jobs(arq_pool, externals)

    async def test_the_pipeline_ran_in_one_job(self):
        """Full mode does all of it inline. A second job here would mean the
        split branch was taken for a user with no Gmail to scan."""
        assert self.ran == [INTELLIGENCE_TASK]

    async def test_the_user_reaches_complete(self, stages: _StageSink):
        """COMPLETE is the only event that dismisses the onboarding screen."""
        assert stages.emitted(OnboardingStage.COMPLETE)

    async def test_complete_carries_the_conversation_the_user_lands_in(self, stages: _StageSink):
        assert stages.payload(OnboardingStage.COMPLETE)["conversation_id"] == "conv-seeded"

    async def test_workflows_are_reported_before_the_screen_is_dismissed(
        self, stages: _StageSink, externals: _Externals
    ):
        """WORKFLOWS_READY after COMPLETE lands on a screen that is already gone —
        the user never sees the workflows the pipeline built for them. The tail
        also has to have *waited* for them, not merely been beaten by them: the
        greeting names what was built, and names nothing if the tail ran first."""
        assert stages.index(OnboardingStage.WORKFLOWS_READY) < stages.index(
            OnboardingStage.COMPLETE
        )
        assert len(stages.payload(OnboardingStage.WORKFLOWS_READY)["workflows"]) == 4
        assert "Workflow 1" in externals.llm_prompts["onboarding_first_message"]

    async def test_todos_are_reported_before_the_screen_is_dismissed(
        self, stages: _StageSink, externals: _Externals
    ):
        """The twin of the workflows case: the list the user was shown is the list
        the greeting talks about, and it arrived before the screen went away."""
        assert stages.index(OnboardingStage.TODOS_READY) < stages.index(OnboardingStage.COMPLETE)
        assert [t["title"] for t in stages.payload(OnboardingStage.TODOS_READY)["todos"]] == (
            externals.todos_created
        )
        assert "Draft the Q3 plan" in externals.llm_prompts["onboarding_first_message"]

    async def test_the_four_generated_workflows_are_created_and_remembered(
        self, users: _UserStore, externals: _Externals
    ):
        """The reveal card reads them back by id from the user document."""
        assert len(externals.workflows_created) == 4
        assert users.onboarding_of(USER_ID)["suggested_workflows"] == [
            "wf-1",
            "wf-2",
            "wf-3",
            "wf-4",
        ]

    async def test_todos_come_from_the_stated_focus_when_there_is_no_inbox(
        self, externals: _Externals
    ):
        assert externals.todos_created == ["Draft the Q3 plan", "Chase the pending signature"]

    async def test_the_first_message_is_persisted_before_complete_is_announced(
        self, stages: _StageSink
    ):
        """COMPLETE triggers a personalization fetch. A first message written
        after it means that fetch returns null and the chat opens empty.

        Read at the instant COMPLETE went out, not afterwards: by the end of the
        pipeline the value is there either way, so a test that looks at the end
        passes with the write moved to after the emit."""
        assert stages.first_message_at[OnboardingStage.COMPLETE.value] == "Hey, you're all set."

    async def test_the_phase_advances_so_the_app_stops_showing_onboarding(self, users: _UserStore):
        assert (
            users.onboarding_of(USER_ID)["phase"] == OnboardingPhase.PERSONALIZATION_COMPLETE.value
        )

    async def test_no_writing_style_stage_is_emitted_without_gmail(self, stages: _StageSink):
        """Style learning and social extraction are Gmail-only and return before
        their stages, so neither card is announced at all rather than announced
        empty. This is the contract the frontend's no-Gmail reveal queue is built
        on — that queue never lists these two, so their absence is expected."""
        assert not stages.emitted(OnboardingStage.WRITING_STYLE_READY)
        assert not stages.emitted(OnboardingStage.SOCIAL_PROFILES_READY)

    async def test_no_inbox_work_is_started_without_gmail(
        self, stages: _StageSink, externals: _Externals
    ):
        assert not stages.emitted(OnboardingStage.TRIAGE_READY)
        assert externals.memory_jobs == []

    async def test_the_job_id_is_released_when_the_pipeline_finishes(self, users: _UserStore):
        """A stale id makes the next reset try to abort a job that is long gone."""
        assert "intelligence_job_id" not in users.onboarding_of(USER_ID)

    async def test_the_personalization_endpoint_serves_what_the_pipeline_wrote(
        self, client: AsyncClient
    ):
        """The reveal screen refetches over HTTP when the socket drops. It must
        agree with the socket, or a reconnecting user sees a blank card."""
        body = (await client.get(PERSONALIZATION)).json()

        assert body["has_personalization"] is True
        assert body["first_message_conversation_id"] == "conv-seeded"
        assert body["first_message"] == "Hey, you're all set."


class TestTheFullPipelineDegrades:
    async def test_a_workflow_model_outage_still_delivers_everything_else(
        self,
        client: AsyncClient,
        arq_pool: ArqRedis,
        externals: _Externals,
        users: _UserStore,
        stages: _StageSink,
    ):
        """One node's model fails; the rest of the onboarding still has to arrive.

        Asserted on the outputs rather than on the phase: the task wrapper marks
        the phase complete even when the whole pipeline dies, so a phase-only
        assertion passes for a user who got nothing at all. Here the workflow
        model is the only thing broken, so the fallback workflow, the todos, the
        greeting and COMPLETE must all still be there."""
        externals.llm_failures = {"onboarding_workflow_suggestions"}

        await complete_submit(client)
        await run_queued_jobs(arq_pool, externals)

        titles = [w["title"] for w in stages.payload(OnboardingStage.WORKFLOWS_READY)["workflows"]]

        assert externals.todos_created == ["Draft the Q3 plan", "Chase the pending signature"]
        assert titles == ["Daily Briefing"]
        assert stages.emitted(OnboardingStage.COMPLETE)
        assert users.onboarding_of(USER_ID)["first_message"] == "Hey, you're all set."

    async def test_a_crash_inside_the_todos_node_does_not_take_the_pipeline_down(
        self,
        client: AsyncClient,
        arq_pool: ArqRedis,
        externals: _Externals,
        stages: _StageSink,
    ):
        """The todos node runs inside the gather the whole pipeline waits on, so
        it swallows its own failures. Without that, a bug in todo creation costs
        the user their workflows, their greeting and the end of onboarding —
        three things that have nothing to do with todos.

        The card still has to be resolved, with the copy that says there is
        nothing rather than being left mid-spin."""
        with patch.object(
            intelligence_service,
            "_create_focus_todos",
            AsyncMock(side_effect=RuntimeError("todo creation blew up")),
        ):
            await complete_submit(client)
            await run_queued_jobs(arq_pool, externals)

        assert stages.payload(OnboardingStage.TODOS_READY)["status_text"] == "No todos to save"
        assert stages.payload(OnboardingStage.TODOS_READY)["todos"] == []
        assert stages.emitted(OnboardingStage.COMPLETE)
        assert len(externals.workflows_created) == 4

    async def test_a_failed_first_message_falls_back_to_copy_not_an_empty_chat(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, users: _UserStore
    ):
        """The chat opens on this message. A model failure has to leave written
        copy behind, not an empty string the user lands on."""
        externals.llm_failures = {"onboarding_first_message"}

        await complete_submit(client)
        await run_queued_jobs(arq_pool, externals)

        first_message = users.onboarding_of(USER_ID)["first_message"]
        assert first_message.startswith("Hey Test User, ok, you're all set up.")

    async def test_the_pipelines_own_default_copy_is_used_when_the_node_is_gone(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, users: _UserStore
    ):
        """One greeting, whichever layer catches the failure.

        ``generate_first_message`` handles its own exceptions, so ``_safe_run``'s
        default is only reachable if the node stops doing that — but it is the
        last thing between a model outage and an empty first chat, so it stays.
        What it must not be is *different* copy: the assertion below is the same
        one ``test_a_failed_first_message_falls_back_to_copy_not_an_empty_chat``
        makes, which is what keeps the two layers from drifting into two
        different greetings for one failure mode."""
        await complete_submit(client)
        with patch.object(
            intelligence_service,
            "generate_first_message",
            AsyncMock(side_effect=RuntimeError("node raised")),
        ):
            await run_queued_jobs(arq_pool, externals)

        first_message = users.onboarding_of(USER_ID)["first_message"]
        assert first_message.startswith("Hey Test User, ok, you're all set up.")

    async def test_a_pipeline_crash_does_not_strand_the_user(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, users: _UserStore
    ):
        """The task wrapper's rescue path: full mode owns the completion, so an
        unhandled crash must still advance the phase."""
        await complete_submit(client)
        with patch.object(
            intelligence_service, "_run_todos", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            await run_queued_jobs(arq_pool, externals)

        assert (
            users.onboarding_of(USER_ID)["phase"] == OnboardingPhase.PERSONALIZATION_COMPLETE.value
        )

    async def test_a_failed_seed_still_completes_without_a_conversation(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, stages: _StageSink
    ):
        externals.seeded_conversation_id = None

        await complete_submit(client)
        await run_queued_jobs(arq_pool, externals)

        assert stages.payload(OnboardingStage.COMPLETE)["conversation_id"] is None


# ---------------------------------------------------------------------------
# Ordering the user can actually observe
# ---------------------------------------------------------------------------


class TestWhatTheScreenShowsWhileItWaits:
    """Ordering claims asserted against a pipeline that is held mid-flight.

    Reading the finished event list cannot distinguish "emitted before" from
    "emitted at all": with no real I/O anywhere, a stage moved after a network
    call, or detached from the thing that should await it, still lands in the
    same place. Both tests below stop the pipeline at the exact point of
    interest and look at the screen while it is stopped.
    """

    async def test_activity_is_announced_before_the_composio_round_trip(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, stages: _StageSink
    ):
        """Both first-step cards must light up before the Gmail check, which is a
        real network call to Composio. Announced after it, the user watches a
        blank screen for the length of that round trip and concludes it hung."""
        externals.composio_gate = asyncio.Event()
        await complete_submit(client)

        job = asyncio.create_task(run_queued_jobs(arq_pool, externals))
        try:
            announced = await wait_for_stages(stages, 2)
        finally:
            externals.composio_gate.set()
            await job

        assert set(announced) == {
            OnboardingStage.INBOX_SCANNING.value,
            OnboardingStage.TODOS_CREATING.value,
        }

    async def test_the_screen_is_not_dismissed_while_the_todos_stage_is_in_flight(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, stages: _StageSink
    ):
        """The pipeline has to await the todos stage, not fire it and move on.

        Held open at the socket: while TODOS_READY is still being delivered,
        COMPLETE must not have gone out. Detach that emit and the tail runs
        straight through — the client is told onboarding finished while the todo
        list it is supposed to render is still on the wire, and on a slow socket
        it is dropped entirely when the connection closes."""
        gate = stages.hold(OnboardingStage.TODOS_READY)
        await complete_submit(client)

        job = asyncio.create_task(run_queued_jobs(arq_pool, externals))
        try:
            await wait_for_stage(stages, OnboardingStage.TODOS_READY)
            # Hand the loop back repeatedly so the tail gets every chance to run
            # on. Held correctly it cannot; detached it runs to COMPLETE here,
            # which is what makes this deterministic rather than a race.
            for _ in range(50):
                await asyncio.sleep(0)
            in_flight = list(stages.names)
        finally:
            gate.set()
            await job

        assert OnboardingStage.COMPLETE.value not in in_flight
        assert stages.index(OnboardingStage.TODOS_READY) < stages.index(OnboardingStage.COMPLETE)


# ---------------------------------------------------------------------------
# The split (Gmail) pipeline: first half
# ---------------------------------------------------------------------------


class TestTheSplitPipelineStopsAndWaits:
    @pytest.fixture(autouse=True)
    async def _run(self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals):
        externals.has_gmail = True
        externals.inbox = [_gmail_message(i) for i in range(6)]
        externals.sent_emails = [_sent_email(i) for i in range(8)]
        await complete_submit(client, defer_workflows=True)
        self.ran = await run_queued_jobs(arq_pool, externals)

    async def test_the_first_job_does_not_finish_onboarding(self, stages: _StageSink):
        """The whole point of the split is that the inbox work overlaps the time
        the user spends picking integrations. Completing here would dismiss the
        screen before they have picked anything."""
        assert not stages.emitted(OnboardingStage.COMPLETE)

    async def test_no_workflows_are_created_yet(self, externals: _Externals):
        assert externals.workflows_created == []

    async def test_the_early_marker_is_set_so_the_second_job_can_proceed(self, users: _UserStore):
        """The workflows job polls for this for five minutes before giving up."""
        assert users.onboarding_of(USER_ID)["early_intelligence_done_at"]

    async def test_the_inbox_work_did_run(self, stages: _StageSink):
        assert stages.emitted(OnboardingStage.TRIAGE_READY)
        assert stages.payload(OnboardingStage.TRIAGE_READY)["total_scanned"] == 6

    async def test_the_writing_style_the_user_sees_is_the_one_persisted(
        self, stages: _StageSink, users: _UserStore
    ):
        """The card is shown from the socket and re-read over HTTP. Two different
        answers is a card that changes under the user on a refresh."""
        emitted = stages.payload(OnboardingStage.WRITING_STYLE_READY)["style_summary"]

        assert emitted == users.onboarding_of(USER_ID)["writing_style"]["summary"]

    async def test_todos_are_built_from_the_triaged_inbox(self, externals: _Externals):
        assert externals.todos_created == [
            "Reply to the contract redlines",
            "Summarize this week's invoices",
        ]

    async def test_a_todo_keeps_only_a_source_email_that_really_exists(self, stages: _StageSink):
        """The card renders "from <sender>" under the todo. A hallucinated citation
        shows the user an email they never received."""
        todos = stages.payload(OnboardingStage.TODOS_READY)["todos"]

        assert todos[0]["source_email"]["sender"] == REAL_SENDER
        assert "source_email" not in todos[1]

    async def test_memory_ingestion_is_queued_off_the_scan(self, externals: _Externals):
        assert externals.memory_jobs == ["process_gmail_emails_to_memory"]

    async def test_the_phase_stays_pending_until_the_second_job(self, users: _UserStore):
        assert (
            users.onboarding_of(USER_ID)["phase"] == OnboardingPhase.PERSONALIZATION_PENDING.value
        )


class TestACrashedEarlyJobIsLeftForTheCleanupCron:
    """The split half that must NOT rescue itself.

    Full mode owns the completion, so its task wrapper advances the phase on a
    crash. Split mode does not: the workflows job (or the stuck-personalization
    cron, which selects on ``phase == personalization_pending``) is what finishes
    the flow. Marking a crashed early job complete drops the user out of that
    query, and nothing ever picks them up again.
    """

    @pytest.fixture(autouse=True)
    async def _run(self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals):
        externals.has_gmail = True
        externals.inbox = [_gmail_message(i) for i in range(4)]
        await complete_submit(client, defer_workflows=True)
        with patch.object(
            intelligence_service, "_run_todos", AsyncMock(side_effect=RuntimeError("worker died"))
        ):
            await run_queued_jobs(arq_pool, externals)

    async def test_the_phase_is_left_pending_for_the_retry(self, users: _UserStore):
        """The whole rescue. Advanced here, this user is invisible to the cron and
        permanently stuck with no workflows, no greeting, and a reveal screen of
        defaults — with nothing anywhere reporting a failure."""
        assert (
            users.onboarding_of(USER_ID)["phase"] == OnboardingPhase.PERSONALIZATION_PENDING.value
        )

    async def test_onboarding_was_not_announced_as_finished(self, stages: _StageSink):
        assert not stages.emitted(OnboardingStage.COMPLETE)

    async def test_nothing_was_written_that_would_look_finished(self, users: _UserStore):
        onboarding = users.onboarding_of(USER_ID)

        assert "first_message" not in onboarding
        assert "first_message_conversation_id" not in onboarding


class TestAnEmptySentFolder:
    """Gmail connected, but too few sent emails to learn a style from.

    The no-Gmail case skips the stage entirely; this one must not. The card is
    already on screen by the time style learning finishes, and an explicit null
    is what resolves it — the frontend distinguishes "learned nothing" from
    "still learning", and only one of those ever stops spinning.
    """

    @pytest.fixture(autouse=True)
    async def _run(self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals):
        externals.has_gmail = True
        externals.inbox = [_gmail_message(i) for i in range(4)]
        externals.sent_emails = [_sent_email(0)]  # under the sampler's minimum
        await complete_submit(client, defer_workflows=True)
        await run_queued_jobs(arq_pool, externals)

    async def test_the_card_is_told_there_was_nothing_to_learn(self, stages: _StageSink):
        payload = stages.payload(OnboardingStage.WRITING_STYLE_READY)

        assert payload["style_summary"] is None
        assert payload["example"] is None

    async def test_no_style_is_persisted_from_an_empty_sample(self, users: _UserStore):
        """A persisted style built from one email would be handed to every future
        draft as if it were learned."""
        assert "writing_style" not in users.onboarding_of(USER_ID)

    async def test_the_rest_of_the_inbox_work_still_ran(self, stages: _StageSink):
        assert stages.emitted(OnboardingStage.TRIAGE_READY)


# ---------------------------------------------------------------------------
# POST /onboarding/integrations
# ---------------------------------------------------------------------------


@pytest.fixture
async def awaiting_integrations(
    client: AsyncClient, arq_pool: ArqRedis, externals: _Externals
) -> None:
    """A user parked exactly where the integration picker is shown."""
    externals.has_gmail = True
    externals.inbox = [_gmail_message(i) for i in range(4)]
    await complete_submit(client, defer_workflows=True)
    await run_queued_jobs(arq_pool, externals)


class TestSubmittingIntegrations:
    async def test_a_selection_queues_the_workflows_job(
        self, client: AsyncClient, arq_pool: ArqRedis, awaiting_integrations: None
    ):
        response = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})

        assert response.json()["status"] == OnboardingIntegrationsStatus.QUEUED.value
        assert await queued_job_names(arq_pool) == [WORKFLOWS_TASK]

    async def test_the_selection_is_persisted_for_the_workflows_prompt(
        self, client: AsyncClient, users: _UserStore, awaiting_integrations: None
    ):
        """These are what the generated workflows are anchored to. Losing them
        gives the user four generic workflows for tools they never picked."""
        await client.post(INTEGRATIONS, json={"selected_integrations": ["slack", "notion"]})

        assert users.onboarding_of(USER_ID)["selected_integrations"] == ["slack", "notion"]

    async def test_the_queued_job_is_tracked_so_it_can_be_aborted(
        self, client: AsyncClient, users: _UserStore, awaiting_integrations: None
    ):
        await client.post(INTEGRATIONS, json={"selected_integrations": []})

        assert users.onboarding_of(USER_ID)["workflows_job_id"]

    async def test_a_double_submit_does_not_start_a_second_workflows_job(
        self, client: AsyncClient, arq_pool: ArqRedis, awaiting_integrations: None
    ):
        """The picker's submit button is clickable twice. Two workflows jobs both
        generate four workflows and both emit COMPLETE — the user ends up with
        eight workflows and a screen that dismisses twice."""
        first = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})
        second = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})

        assert first.json()["status"] == OnboardingIntegrationsStatus.QUEUED.value
        assert second.json()["status"] == OnboardingIntegrationsStatus.ALREADY_RUNNING.value
        assert await queued_job_names(arq_pool) == [WORKFLOWS_TASK]

    async def test_a_resubmit_after_the_job_died_starts_a_fresh_one(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals
    ):
        """A stored job id is not proof of a live job — a worker restart drops it.
        Treating a dead id as running would leave the user stuck forever with no
        way to retry."""
        externals.has_gmail = True
        await complete_submit(client, defer_workflows=True)
        await run_queued_jobs(arq_pool, externals)
        await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})
        await drop_queued_jobs(arq_pool)

        response = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})

        assert response.json()["status"] == OnboardingIntegrationsStatus.QUEUED.value
        assert await queued_job_names(arq_pool) == [WORKFLOWS_TASK]

    async def test_submitting_after_onboarding_finished_changes_nothing(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, users: _UserStore
    ):
        """Replay of a request the user already completed — a stale tab, a retry.
        Re-running the phase would regenerate their workflows and re-seed the
        conversation they are already reading."""
        externals.has_gmail = True
        await complete_submit(client, defer_workflows=True)
        await run_queued_jobs(arq_pool, externals)
        await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})
        await run_queued_jobs(arq_pool, externals)
        created_before = list(externals.workflows_created)

        response = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})

        assert response.json()["status"] == OnboardingIntegrationsStatus.ALREADY_COMPLETE.value
        assert await queued_job_names(arq_pool) == []
        assert externals.workflows_created == created_before

    async def test_a_full_mode_user_is_refused(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals
    ):
        """Full mode already created the workflows inline. Accepting this would
        run the workflows phase a second time on top of them."""
        await complete_submit(client)
        await run_queued_jobs(arq_pool, externals)

        response = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})

        assert response.status_code == 409
        assert await queued_job_names(arq_pool) == []

    async def test_a_user_who_never_submitted_onboarding_is_refused(self, client: AsyncClient):
        """Two different 409s guard this endpoint and the frontend routes on the
        detail: "not submitted" sends the user back to the form, "not awaiting
        selection" does not. Dropping the first guard leaves the second answering
        for it with the wrong instruction."""
        response = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})

        assert response.status_code == 409
        assert response.json()["detail"] == "Onboarding has not been submitted yet"

    async def test_an_unknown_user_is_a_404(self, client: AsyncClient, users: _UserStore):
        users.docs.clear()

        response = await client.post(INTEGRATIONS, json={"selected_integrations": []})

        assert response.status_code == 404

    async def test_a_failed_enqueue_is_reported_as_retryable(
        self, client: AsyncClient, awaiting_integrations: None
    ):
        """503 is what tells the picker to offer a retry. A 200 here would leave
        the user watching for workflows that no job will ever create."""
        with patch.object(ArqRedis, "enqueue_job", AsyncMock(return_value=None)):
            response = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})

        assert response.status_code == 503


class TestTheWorkflowsPhaseFinishesOnboarding:
    @pytest.fixture(autouse=True)
    async def _run(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, stages: _StageSink
    ):
        externals.has_gmail = True
        externals.inbox = [_gmail_message(i) for i in range(4)]
        externals.sent_emails = [_sent_email(i) for i in range(8)]
        await complete_submit(client, defer_workflows=True)
        await run_queued_jobs(arq_pool, externals)
        await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})
        stages.events.clear()
        self.early_scan = list(externals.inbox)
        self.labels_before = len(externals.llm_labels)
        self.ran = await run_queued_jobs(arq_pool, externals)
        self.phase_labels = externals.llm_labels[self.labels_before :]

    async def test_the_second_job_ran(self):
        assert self.ran == [WORKFLOWS_TASK]

    async def test_the_user_finally_reaches_complete(self, stages: _StageSink):
        assert stages.emitted(OnboardingStage.COMPLETE)
        assert stages.payload(OnboardingStage.COMPLETE)["conversation_id"] == "conv-seeded"

    async def test_workflows_are_created_in_this_phase(self, externals: _Externals):
        assert len(externals.workflows_created) == 4

    async def test_the_phase_advances_only_now(self, users: _UserStore):
        assert (
            users.onboarding_of(USER_ID)["phase"] == OnboardingPhase.PERSONALIZATION_COMPLETE.value
        )

    async def test_the_inbox_is_not_rescanned(self):
        """The early phase already paid for the scan and persisted what it learned.
        Re-triaging here would double the Gmail cost and the latency the split was
        introduced to hide."""
        assert self.phase_labels == [
            "onboarding_workflow_suggestions",
            "onboarding_first_message",
        ]

    async def test_the_workflows_are_grounded_in_what_the_early_phase_learned(
        self, externals: _Externals
    ):
        """This phase rebuilds triage and writing style from the user document
        rather than re-deriving them. If that read regressed the call still
        succeeds and the user still gets four workflows — generic ones, with the
        whole inbox scan thrown away and nothing anywhere saying so."""
        prompt = externals.llm_prompts["onboarding_workflow_suggestions"]

        assert REAL_SENDER in prompt
        assert "Direct and warm" in prompt

    async def test_the_selected_integrations_reach_the_workflow_prompt(self, externals: _Externals):
        """Picking Slack and getting four Gmail workflows is the failure the
        picker exists to prevent. Asserted on the rendered preference section, not
        on the word: the prompt template names Slack in its own examples, so a
        bare substring check passes with the selection thrown away. Gmail joins
        the line because it is connected — the selection is what the user picked
        plus what they are already on."""
        prompt = externals.llm_prompts["onboarding_workflow_suggestions"]

        assert "Preferred integrations" in prompt
        assert prompt.split("Preferred integrations")[1].splitlines()[1] == "Slack, Gmail"

    async def test_the_workflows_job_id_is_released(self, users: _UserStore):
        assert "workflows_job_id" not in users.onboarding_of(USER_ID)


class TestRetryingAKilledWorkflowsPhase:
    """A workflows job that dies after creating workflows but before finishing.

    Production reaches this through the stuck-personalization cron, which
    re-enqueues the phase for a user still sitting at pending. Reached here the
    same way it happens: the tail raises, the task wrapper rescues the user, and
    the picker is submitted again.
    """

    @pytest.fixture(autouse=True)
    async def _run(self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals):
        externals.has_gmail = True
        externals.inbox = [_gmail_message(i) for i in range(4)]
        await complete_submit(client, defer_workflows=True)
        await run_queued_jobs(arq_pool, externals)

        await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})
        with patch.object(
            intelligence_service,
            "_finalize_onboarding",
            AsyncMock(side_effect=RuntimeError("worker killed")),
        ):
            await run_queued_jobs(arq_pool, externals)
        self.after_first_attempt = list(externals.workflows_created)

        self.retry = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})
        await run_queued_jobs(arq_pool, externals)

    async def test_the_killed_attempt_did_create_workflows(self):
        assert len(self.after_first_attempt) == 4

    async def test_the_retry_is_accepted_rather_than_treated_as_a_replay(self):
        """The user never reached a first message, so this is not a replay — a
        stuck user has to be able to get through."""
        assert self.retry.json()["status"] == OnboardingIntegrationsStatus.QUEUED.value

    async def test_the_orphaned_workflows_are_purged_before_regenerating(
        self, externals: _Externals
    ):
        """Without the purge the retry adds to the first attempt's output: the
        user lands on eight workflows, four of which nothing points at."""
        assert externals.purged_workflow_ids == [["wf-1", "wf-2", "wf-3", "wf-4"]]

    async def test_the_user_ends_up_with_one_set_of_suggestions(self, users: _UserStore):
        assert users.onboarding_of(USER_ID)["suggested_workflows"] == [
            "wf-5",
            "wf-6",
            "wf-7",
            "wf-8",
        ]

    async def test_the_retry_finishes_onboarding(self, users: _UserStore, stages: _StageSink):
        assert stages.emitted(OnboardingStage.COMPLETE)
        assert users.onboarding_of(USER_ID)["first_message_conversation_id"] == "conv-seeded"


class TestTheWorkflowsPhaseWhenTheEarlyHalfNeverFinished:
    """The early-phase wait timing out — the branch the real constants hide.

    ``_wait_for_early_phase`` polls for five minutes for a marker that a killed
    or aborted early job never writes. Reaching the timeout in a test means
    shortening it, so the constants are patched down; everything after that
    point is the real degraded path. It has to end with the user through
    onboarding on whatever was persisted, because the alternative is a user
    stuck behind a job that gave up.
    """

    @pytest.fixture(autouse=True)
    async def _run(
        self,
        client: AsyncClient,
        arq_pool: ArqRedis,
        externals: _Externals,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(intelligence_service, "EARLY_PHASE_WAIT_TIMEOUT_S", 0.2)
        monkeypatch.setattr(intelligence_service, "EARLY_PHASE_POLL_INTERVAL_S", 0.02)
        externals.has_gmail = True
        await complete_submit(client, defer_workflows=True)
        # The early job is queued and then lost — a worker that died before
        # picking it up, so the marker it would have written never appears.
        await drop_queued_jobs(arq_pool)

        self.submitted = await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})
        self.ran = await run_queued_jobs(arq_pool, externals)

    async def test_the_workflows_phase_is_accepted_and_runs(self):
        assert self.submitted.json()["status"] == OnboardingIntegrationsStatus.QUEUED.value
        assert self.ran == [WORKFLOWS_TASK]

    async def test_the_user_still_gets_through_onboarding(
        self, stages: _StageSink, users: _UserStore
    ):
        """Giving up here would leave them on the loading screen with a job that
        already exited — no error, no retry, nothing to click."""
        assert stages.emitted(OnboardingStage.COMPLETE)
        assert (
            users.onboarding_of(USER_ID)["phase"] == OnboardingPhase.PERSONALIZATION_COMPLETE.value
        )

    async def test_they_still_get_workflows_and_a_greeting(
        self, externals: _Externals, users: _UserStore
    ):
        assert len(externals.workflows_created) == 4
        assert users.onboarding_of(USER_ID)["first_message"] == "Hey, you're all set."

    async def test_the_workflows_are_generated_without_the_learnings_that_never_landed(
        self, externals: _Externals
    ):
        """Degraded, not wrong: with no persisted triage or style the prompt says
        so rather than carrying a half-written one."""
        prompt = externals.llm_prompts["onboarding_workflow_suggestions"]

        assert "no email data" in prompt
        assert "not analyzed" in prompt


# ---------------------------------------------------------------------------
# POST /onboarding/reset
# ---------------------------------------------------------------------------


@pytest.fixture
async def onboarded(client: AsyncClient, arq_pool: ArqRedis, externals: _Externals) -> None:
    externals.integrations_connected = ["slack", "notion"]
    externals.memories_cleared = 7
    externals.todos_purged = 3
    externals.demo_conversations = 2
    await complete_submit(client)
    await run_queued_jobs(arq_pool, externals)


class TestResettingOnboarding:
    async def test_the_user_can_run_onboarding_again(
        self, client: AsyncClient, users: _UserStore, arq_pool: ArqRedis, onboarded: None
    ):
        """This is the only thing reset is for. If the subdoc survives, the next
        submit is treated as a replay and no pipeline is ever queued again."""
        await client.post(RESET)

        assert "onboarding" not in users.docs[USER_ID]
        again = await complete_submit(client)
        assert again.status_code == 200
        assert await queued_job_names(arq_pool) == [INTELLIGENCE_TASK]

    async def test_the_status_endpoint_agrees_the_user_is_no_longer_onboarded(
        self, client: AsyncClient, onboarded: None
    ):
        await client.post(RESET)

        body = (await client.get(STATUS)).json()

        assert body["completed"] is False
        assert body["first_message_conversation_id"] is None

    async def test_the_generated_workflows_are_torn_down(
        self, client: AsyncClient, externals: _Externals, onboarded: None
    ):
        """Deleted through the workflow service, not the collection, so their
        schedules and Composio triggers go with them. Orphaned triggers keep
        firing into an account the user thinks they have wiped."""
        response = await client.post(RESET)

        assert externals.workflows_deleted == ["wf-1", "wf-2", "wf-3", "wf-4"]
        assert response.json()["workflows_deleted"] == 4

    async def test_everything_the_pipeline_created_is_counted_as_deleted(
        self, client: AsyncClient, onboarded: None
    ):
        """The counts are what the reset screen shows back to the user."""
        body = (await client.post(RESET)).json()

        assert body["todos_deleted"] == 3
        assert body["conversation_deleted"] == 1
        assert body["demo_conversations_deleted"] == 2
        assert body["integrations_disconnected"] == 2
        assert body["memories_cleared"] == 7

    async def test_the_connected_integrations_are_disconnected(
        self, client: AsyncClient, externals: _Externals, onboarded: None
    ):
        await client.post(RESET)

        assert externals.disconnected == ["slack", "notion"]

    async def test_a_live_pipeline_is_aborted_before_the_document_is_wiped(
        self, client: AsyncClient, arq_pool: ArqRedis, users: _UserStore
    ):
        """A job that survives the reset keeps writing stages onto the socket of a
        user who has already restarted — the two runs interleave on the new one."""
        await complete_submit(client)
        job_id = users.onboarding_of(USER_ID)["intelligence_job_id"]

        await client.post(RESET)

        aborted = await arq_pool.zrange(abort_jobs_ss, 0, -1)
        assert [raw.decode() if isinstance(raw, bytes) else raw for raw in aborted] == [job_id]

    async def test_a_queued_workflows_job_is_aborted_too(
        self,
        client: AsyncClient,
        arq_pool: ArqRedis,
        users: _UserStore,
        awaiting_integrations: None,
    ):
        """Both slots are aborted independently — cancelling only the first leaves
        the second half of the split still running against a wiped document."""
        await client.post(INTEGRATIONS, json={"selected_integrations": ["slack"]})
        workflows_job = users.onboarding_of(USER_ID)["workflows_job_id"]

        await client.post(RESET)

        aborted = {
            raw.decode() if isinstance(raw, bytes) else raw
            for raw in await arq_pool.zrange(abort_jobs_ss, 0, -1)
        }
        assert workflows_job in aborted

    async def test_one_failed_deletion_does_not_abandon_the_rest(
        self, client: AsyncClient, externals: _Externals, onboarded: None
    ):
        """A half-reset is worse than none: the user restarts onboarding while
        their old todos and memories are still feeding the new run's context."""
        externals.workflow_delete_error = "wf-2"

        body = (await client.post(RESET)).json()

        assert externals.workflows_deleted == ["wf-1", "wf-3", "wf-4"]
        assert body["workflows_deleted"] == 3
        assert body["memories_cleared"] == 7

    async def test_a_failed_abort_does_not_block_the_reset(
        self, client: AsyncClient, users: _UserStore, onboarded: None
    ):
        with patch(
            "app.services.onboarding.onboarding_service.abort_active_intelligence_job",
            AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            response = await client.post(RESET)

        assert response.status_code == 200
        assert "onboarding" not in users.docs[USER_ID]

    async def test_resetting_an_unknown_user_is_a_404(self, client: AsyncClient, users: _UserStore):
        users.docs.clear()

        assert (await client.post(RESET)).status_code == 404

    async def test_resetting_a_user_who_never_onboarded_is_harmless(
        self, client: AsyncClient, externals: _Externals
    ):
        body = (await client.post(RESET)).json()

        assert body["success"] is True
        assert body["workflows_deleted"] == 0
        assert externals.workflows_deleted == []
