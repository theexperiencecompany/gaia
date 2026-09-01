"""Onboarding as the user actually experiences it: submit, connect Gmail, reset.

The flow spans layers no other test crosses together — the HTTP endpoints, the
onboarding service, the OAuth connect handler, the ARQ job slot, and the Gmail
personalization DAG. The unit suites underneath fake every node at its own
boundary, so orchestration is asserted in isolation and the seams between layers
are asserted nowhere.

The shape changed: submitting the form *is* completion. Nothing is queued, no
todo is seeded and no conversation is created there. Everything the user gets —
the inbox scan, memories, writing style, triage, social profiles, the holo card
and the conversation that hands it over — is earned by connecting Gmail, exactly
once per user. What that costs when it breaks is invisible: every stage emit is
fire-and-forget, every node swallows its own failure, and the task returns a
string rather than raising. A broken pipeline does not error, it just leaves a
user with no card and no memories and nothing anywhere saying so. A pipeline
that runs *twice* is worse — a second holo card and a second announcement
conversation for a user who merely reconnected Gmail.

**What is real here.** The HTTP endpoints, ``onboarding_service``,
``handle_oauth_connection``'s Gmail branch, ``intelligence_job``, the ARQ task
wrapper, and the whole ``intelligence_service`` DAG including triage, writing
style, the holo card and the seeded announcement. ARQ is real too: jobs are
enqueued onto a real ``ArqRedis`` (backed by fakeredis), read back off the queue
by ``run_queued_jobs`` exactly as the worker does, and aborts land in arq's real
``abort`` sorted set — so "the job is live" and "the job was aborted" are
answered by arq, not by a mock.

**What is doubled.** Only external I/O: the LLM, Gmail, Composio, notifications
and the persistence layer. ``_UserStore`` stands in for Mongo and mirrors two
conditional repository contracts — the ``onboarding: {$exists: false}`` gate and
compare-and-clear on the job id — each of which is certified against real Mongo
in ``tests/contracts/test_users_repository.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from arq.connections import ArqRedis
from arq.constants import abort_jobs_ss, default_queue_name, job_key_prefix
from arq.jobs import Job
import fakeredis.aioredis
from fastapi import BackgroundTasks
from httpx import AsyncClient
import pytest

from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.onboarding import (
    GMAIL_PERSONALIZATION_MARKER,
    HOLO_CONVERSATION_ID_FIELD,
    INTELLIGENCE_TASK,
    LEGACY_PERSONALIZATION_MARKER,
)
from app.models.oauth_models import OAuthIntegration
from app.models.onboarding_models import (
    EmailSummary,
    HoloCardLLMOutput,
    InboxTriageOutput,
    SocialProfile,
    WritingStyleExampleBlocks,
    WritingStyleOutput,
)
from app.models.user_models import OnboardingPhase, UserDocument
from app.services.oauth.oauth_service import handle_oauth_connection
from app.services.onboarding.intelligence_service import OnboardingStage, holo_card_url
from app.utils.redis_utils import RedisPoolManager
from app.workers.tasks.onboarding_tasks import process_onboarding_intelligence_task
from tests.conftest import FAKE_USER

pytestmark = pytest.mark.e2e

USER_ID: str = FAKE_USER["user_id"]

#: The sender the triage LLM reports as important.
REAL_SENDER = "priya@client.com"
REAL_SUBJECT = "Contract redlines"

SUBMIT = "/api/v1/onboarding"
RESET = "/api/v1/onboarding/reset"
STATUS = "/api/v1/onboarding/status"
PERSONALIZATION = "/api/v1/onboarding/personalization"

MEMORY_TASK = "process_gmail_emails_to_memory"

GMAIL_CONFIG = OAuthIntegration(
    id=GMAIL_INTEGRATION_ID,
    name="Gmail",
    description="Email",
    category="productivity",
    provider="google",
    scopes=[],
    managed_by="self",
)


# ---------------------------------------------------------------------------
# Mongo stand-in
# ---------------------------------------------------------------------------


class _UserStore:
    """The user collection, in process.

    Only the named methods the onboarding flow calls are implemented, under the
    repository's own names, so production code is unchanged. The two methods
    whose real semantics live in a Mongo filter rather than in Python —
    ``complete_onboarding``'s existence gate and ``clear_active_job_if_matches``'s
    compare-and-clear — are reproduced here; each is certified against real Mongo
    by the repository contract suite.
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

    async def set_onboarding_phase(self, user_id: str, phase: OnboardingPhase) -> bool:
        sub = self._sub(user_id)
        if sub is None:
            return False
        sub["phase"] = phase
        return True

    async def set_bio_status(self, user_id: str, bio_status: Any) -> None:
        sub = self._sub(user_id)
        if sub is not None:
            sub["bio_status"] = bio_status

    # -- job slot ----------------------------------------------------------
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
    async def mark_gmail_personalization_done(
        self, user_id: str, *, conversation_id: str | None = None
    ) -> None:
        sub = self._sub(user_id)
        if sub is None:
            return
        sub[GMAIL_PERSONALIZATION_MARKER] = datetime.now(UTC)
        if conversation_id is not None:
            sub[HOLO_CONVERSATION_ID_FIELD] = conversation_id

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
            sub.update(fields)


# ---------------------------------------------------------------------------
# Stage recorder
# ---------------------------------------------------------------------------


class _StageSink:
    """Every ``onboarding_stage`` event the socket would have carried, in order."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def broadcast_to_user(self, *, user_id: str, message: dict[str, Any]) -> None:
        if message.get("type") != "onboarding_stage":
            return
        data = message["data"]
        self.events.append((data["stage"], data["payload"]))

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


# ---------------------------------------------------------------------------
# External-service doubles
# ---------------------------------------------------------------------------


@dataclass
class _Externals:
    """Everything outside the process, recorded."""

    has_gmail: bool = True
    inbox: list[dict[str, Any]] = field(default_factory=list)
    sent_emails: list[dict[str, Any]] = field(default_factory=list)
    llm_labels: list[str] = field(default_factory=list)
    llm_prompts: dict[str, str] = field(default_factory=dict)
    llm_failures: set[str] = field(default_factory=set)
    #: (conversation_id, description) per seeded conversation, and the bot turn
    #: appended to it — the announcement the user actually opens.
    seeded_conversations: list[tuple[str, str]] = field(default_factory=list)
    seeded_messages: list[str] = field(default_factory=list)
    seeding_fails: bool = False
    notifications: list[str] = field(default_factory=list)
    conversations_deleted: list[str] = field(default_factory=list)
    demo_conversations: int = 0
    todos_purged: int = 0
    memories_cleared: int = 0
    integrations_connected: list[str] = field(default_factory=list)
    disconnected: list[str] = field(default_factory=list)


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


STYLE_SUMMARY = "Direct and warm; short paragraphs, signs off with 'Cheers'."
TRIAGE_SUMMARY = "Two threads need a reply today."
HOLO_PHRASE = "Midnight Architect"
HOLO_BIO = "Builds quietly, ships loudly."


def _structured_result(schema: type) -> Any:
    """A valid instance of whatever schema the caller asked the model for."""
    if schema is WritingStyleOutput:
        return WritingStyleOutput(
            summary=STYLE_SUMMARY,
            example=WritingStyleExampleBlocks(
                greeting="Hey,", body=["Sending the draft over."], signoff="Cheers", name="Test"
            ),
        )
    if schema is InboxTriageOutput:
        return InboxTriageOutput(
            summary=TRIAGE_SUMMARY,
            important_emails=[
                EmailSummary(
                    sender=REAL_SENDER,
                    subject=REAL_SUBJECT,
                    why_important="Blocking the deal",
                )
            ],
            patterns=["Most mail arrives before noon"],
        )
    if schema is HoloCardLLMOutput:
        return HoloCardLLMOutput(personality_phrase=HOLO_PHRASE, user_bio=HOLO_BIO)
    raise AssertionError(f"no scripted result for {schema!r}")


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
    under test: the personalization slot aborts an in-flight job on reset, and
    "nothing was queued" has to be answered by the queue itself.
    """
    fake = fakeredis.aioredis.FakeRedis()
    pool = ArqRedis(connection_pool=fake.connection_pool)
    previous = RedisPoolManager._pool
    RedisPoolManager._pool = pool
    yield pool
    RedisPoolManager._pool = previous
    await fake.aclose()


@pytest.fixture
def stages() -> _StageSink:
    return _StageSink()


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
        return {slug: (slug == "gmail" and externals.has_gmail) for slug in slugs}

    composio = AsyncMock()
    composio.check_connection_status.side_effect = _check_connection

    async def _fetch_emails(
        user_id: str,
        months: int = 1,
        max_total: int = 100,
        on_batch: Callable[[int, str | None], Awaitable[None]] | None = None,
        into: list[dict[str, Any]] | None = None,
        options: Any = None,
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
        return _structured_result(schema)

    async def _search_messages(**_: Any) -> Any:
        result = AsyncMock()
        result.messages = externals.sent_emails
        return result

    async def _create_conversation(conversation: Any, _user: Any) -> Any:
        if externals.seeding_fails:
            raise RuntimeError("mongo down")
        externals.seeded_conversations.append(
            (conversation.conversation_id, conversation.description)
        )
        return conversation

    async def _append_messages(
        _conversation_id: str, *, user_id: str, messages: list[Any]
    ) -> list[str]:
        externals.seeded_messages.extend(m.response for m in messages)
        return [f"msg-{i}" for i, _ in enumerate(messages)]

    async def _create_notification(request: Any) -> None:
        externals.notifications.append(request.content.title)

    async def _list_user_integrations(_user_id: str) -> list[Any]:
        out = []
        for slug in externals.integrations_connected:
            entry = AsyncMock()
            entry.integration_id = slug
            out.append(entry)
        return out

    async def _disconnect(_user_id: str, integration_id: str) -> None:
        externals.disconnected.append(integration_id)

    seeding_conversations = AsyncMock()
    seeding_conversations.append_messages.side_effect = _append_messages

    todo_repo = AsyncMock()
    todo_repo.delete_onboarding_todos.side_effect = lambda _uid: externals.todos_purged
    todo_repo.list_onboarding_todos.return_value = []

    conversation_repo = AsyncMock()

    async def _delete_conversation(conversation_id: str, *, user_id: str) -> bool:
        externals.conversations_deleted.append(conversation_id)
        return True

    conversation_repo.delete.side_effect = _delete_conversation
    conversation_repo.delete_onboarding_demos.side_effect = lambda _uid: (
        externals.demo_conversations
    )

    integrations_repo = AsyncMock()
    integrations_repo.list_for_user.side_effect = _list_user_integrations

    memory = AsyncMock()
    memory.delete_all.side_effect = lambda _uid: externals.memories_cleared

    notifications = AsyncMock()
    notifications.create_notification.side_effect = _create_notification

    patches = [
        # --- persistence -------------------------------------------------
        patch(f"{svc}.onboarding_service.user_repository", users),
        patch(f"{svc}.intelligence_job.user_repository", users),
        patch(f"{svc}.intelligence_service.user_repository", users),
        patch(f"{svc}.post_onboarding_service.user_repository", users),
        patch("app.api.v1.endpoints.onboarding.user_repository", users),
        patch("app.services.oauth.oauth_service.user_repository", users),
        patch("app.utils.profile_card.user_repository", users),
        patch(f"{svc}.onboarding_service.todo_repository", todo_repo),
        patch("app.api.v1.endpoints.onboarding.todo_repository", todo_repo),
        patch("app.api.v1.endpoints.onboarding.workflow_repository", AsyncMock()),
        patch(f"{svc}.onboarding_service.conversation_repository", conversation_repo),
        patch("app.utils.seeding_utils.conversation_repository", seeding_conversations),
        patch("app.utils.seeding_utils.create_conversation_service", _create_conversation),
        patch(f"{svc}.onboarding_service.user_integration_repository", integrations_repo),
        patch(f"{svc}.onboarding_service.memory_engine", memory),
        patch(f"{svc}.onboarding_service.disconnect_integration", _disconnect),
        # --- transport ---------------------------------------------------
        patch(f"{svc}.intelligence_service.websocket_manager", stages),
        patch(f"{svc}.intelligence_service.notification_service", notifications),
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
        patch(f"{svc}.writing_style_service.ainvoke_structured", _structured),
        patch(f"{svc}.inbox_triage_service.ainvoke_structured", _structured),
        patch("app.utils.profile_card.ainvoke_structured", _structured),
        # --- oauth connect side effects ----------------------------------
        patch(
            "app.services.oauth.oauth_service.update_user_integration_status",
            new_callable=AsyncMock,
        ),
    ]
    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        yield


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------

#: The only onboarding task a real worker would pick up. Anything else the
#: pipeline enqueues (gmail -> memory ingestion) is recorded, not run.
_TASKS: dict[str, Any] = {INTELLIGENCE_TASK: process_onboarding_intelligence_task}


async def run_queued_jobs(pool: ArqRedis) -> list[str]:
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
            ran.append(info.function)
            if info.function in _TASKS:
                await _TASKS[info.function]({"job_id": job_id}, *info.args)
    return ran


async def queued_job_names(pool: ArqRedis) -> list[str]:
    names = []
    for raw in await pool.zrange(default_queue_name, 0, -1):
        job_id = raw.decode() if isinstance(raw, bytes) else raw
        info = await Job(job_id, redis=pool).info()
        if info is not None:
            names.append(info.function)
    return names


async def connect_gmail() -> None:
    """The real OAuth connect handler, Gmail branch — what actually starts the
    personalization pipeline now."""
    await handle_oauth_connection(USER_ID, GMAIL_CONFIG, BackgroundTasks())


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


class TestSubmittingTheFormIsCompletion:
    async def test_the_phase_lands_on_complete_in_one_write(
        self, client: AsyncClient, users: _UserStore
    ):
        """Nothing runs after this any more, so anything short of complete parks
        the user on a loading screen forever — there is no job to resolve it."""
        response = await complete_submit(client)

        assert response.status_code == 200
        assert (
            users.onboarding_of(USER_ID)["phase"] == OnboardingPhase.PERSONALIZATION_COMPLETE.value
        )

    async def test_no_job_is_queued_and_nothing_is_seeded(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals
    ):
        """The pipeline, the starter todo and the announcement conversation are
        all Gmail's to earn. Queued here they run for users with no inbox at
        all, and hand every user a holo card built from nothing."""
        await complete_submit(client)

        assert await queued_job_names(arq_pool) == []
        assert externals.seeded_conversations == []

    async def test_the_submitted_choices_are_persisted(
        self, client: AsyncClient, users: _UserStore
    ):
        """Everything the form collects has to survive the write: the Gmail
        pipeline reads focus, profession and clarify answers back off the
        document whenever it eventually runs, and nothing re-asks the user."""
        response = await complete_submit(
            client,
            selected_integrations=["slack", "slack", "notion"],
            timezone="Europe/London",
            clarify_answers=CLARIFY_ANSWERS,
        )

        assert response.status_code == 200
        onboarding = users.onboarding_of(USER_ID)
        assert onboarding["selected_integrations"] == ["slack", "notion"]
        assert onboarding["focus"] == "close the Q3 deals"
        assert onboarding["clarify_answers"] == CLARIFY_ANSWERS
        assert onboarding["preferences"]["profession"] == "Lawyer"
        assert users.docs[USER_ID]["timezone"] == "Europe/London"

    async def test_a_replayed_submit_returns_the_stored_user_unchanged(
        self, client: AsyncClient, arq_pool: ArqRedis
    ):
        """The frontend advances on this payload. Returning an error or an empty
        body on a retried request would strand a user whose first POST landed —
        and the atomic gate must keep the second one from overwriting anything."""
        await complete_submit(client)

        response = await complete_submit(client, name="Someone Else")

        assert response.status_code == 200
        assert response.json()["user"]["user_id"] == USER_ID
        assert response.json()["user"]["name"] == "Test User"
        assert await queued_job_names(arq_pool) == []

    async def test_the_status_endpoint_reports_the_user_as_onboarded(self, client: AsyncClient):
        await complete_submit(client)

        body = (await client.get(STATUS)).json()

        assert body["completed"] is True
        assert body["phase"] == OnboardingPhase.PERSONALIZATION_COMPLETE.value

    async def test_an_unknown_user_is_a_404_not_a_500(self, client: AsyncClient, users: _UserStore):
        users.docs.clear()

        response = await complete_submit(client)

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Connecting Gmail
# ---------------------------------------------------------------------------


class TestConnectingGmailEarnsThePersonalization:
    @pytest.fixture(autouse=True)
    async def _run(self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals):
        externals.inbox = [_gmail_message(i) for i in range(6)]
        externals.sent_emails = [_sent_email(i) for i in range(8)]
        await complete_submit(client)
        await connect_gmail()
        self.ran = await run_queued_jobs(arq_pool)

    async def test_connecting_gmail_is_what_runs_the_pipeline(self):
        """Exactly one personalization job, plus the memory ingestion the scan
        queues behind it. A second personalization job here would rebuild the
        card and re-announce it."""
        assert self.ran == [INTELLIGENCE_TASK, MEMORY_TASK]

    async def test_the_inbox_scan_reports_what_it_found(self, stages: _StageSink):
        assert stages.emitted(OnboardingStage.INBOX_SCANNING)
        assert stages.payload(OnboardingStage.TRIAGE_READY)["total_scanned"] == 6

    async def test_the_writing_style_the_user_sees_is_the_one_persisted(
        self, stages: _StageSink, users: _UserStore
    ):
        """The card is shown from the socket and re-read over HTTP. Two different
        answers is a card that changes under the user on a refresh."""
        emitted = stages.payload(OnboardingStage.WRITING_STYLE_READY)["style_summary"]

        assert emitted == STYLE_SUMMARY
        assert users.onboarding_of(USER_ID)["writing_style"]["summary"] == STYLE_SUMMARY

    async def test_the_triage_is_persisted_for_the_reveal(self, users: _UserStore):
        triage = users.onboarding_of(USER_ID)["triage_summary"]

        assert triage["summary"] == TRIAGE_SUMMARY
        assert triage["important_emails"][0]["sender"] == REAL_SENDER

    async def test_the_social_profiles_found_in_the_inbox_are_kept(self, users: _UserStore):
        assert users.onboarding_of(USER_ID)["social_profiles"] == [
            {"platform": "linkedin", "url": "https://li/x"}
        ]

    async def test_the_holo_card_is_generated_from_what_was_learned(
        self, users: _UserStore, externals: _Externals, stages: _StageSink
    ):
        """The card is the whole reward for connecting Gmail, and it is built
        from the inbox — a card generated without the triage and style in its
        prompt is the generic one every user would get for free."""
        onboarding = users.onboarding_of(USER_ID)

        assert onboarding["personality_phrase"] == HOLO_PHRASE
        assert onboarding["user_bio"] == HOLO_BIO
        assert stages.emitted(OnboardingStage.HOLO_READY)
        prompt = externals.llm_prompts["holo_card"]
        assert TRIAGE_SUMMARY in prompt
        assert STYLE_SUMMARY in prompt
        assert "close the Q3 deals" in prompt

    async def test_the_user_is_handed_the_card_in_a_seeded_conversation(
        self, externals: _Externals
    ):
        """Chat has no holo-card renderer, so the card travels as its public
        link. Losing the link leaves an announcement pointing at nothing."""
        assert [desc for _, desc in externals.seeded_conversations] == ["Your holo card is ready"]
        assert len(externals.seeded_messages) == 1
        assert holo_card_url(USER_ID) in externals.seeded_messages[0]

    async def test_the_notification_goes_out_too(self, externals: _Externals):
        assert externals.notifications == ["Check your memories — I just added a lot"]

    async def test_the_marker_and_the_conversation_id_are_persisted_together(
        self, users: _UserStore, externals: _Externals
    ):
        """The marker is what makes a reconnect a no-op, and the conversation id
        is what lets a reset tear the announcement back down."""
        onboarding = users.onboarding_of(USER_ID)
        seeded_id = externals.seeded_conversations[0][0]

        assert onboarding[GMAIL_PERSONALIZATION_MARKER]
        assert onboarding[HOLO_CONVERSATION_ID_FIELD] == seeded_id

    async def test_the_job_slot_is_released_when_the_pipeline_finishes(self, users: _UserStore):
        """A stale id makes the next reset try to abort a job that is long gone."""
        assert "intelligence_job_id" not in users.onboarding_of(USER_ID)

    async def test_the_personalization_endpoint_serves_what_the_pipeline_wrote(
        self, client: AsyncClient
    ):
        """The reveal screen refetches over HTTP when the socket drops. It must
        agree with the socket, or a reconnecting user sees a blank card."""
        body = (await client.get(PERSONALIZATION)).json()

        assert body["has_personalization"] is True
        assert body["personality_phrase"] == HOLO_PHRASE
        assert body["user_bio"] == HOLO_BIO
        assert body["writing_style"]["style_summary"] == STYLE_SUMMARY
        assert body["triage_summary"]["summary"] == TRIAGE_SUMMARY
        assert body["social_profiles"] == [{"platform": "linkedin", "url": "https://li/x"}]


class TestThePipelineRunsAtMostOnce:
    async def test_a_reconnect_queues_ingestion_instead_of_a_second_pipeline(
        self,
        client: AsyncClient,
        arq_pool: ArqRedis,
        externals: _Externals,
        users: _UserStore,
    ):
        """Reconnecting Gmail is routine — a re-auth, a scope change. Re-running
        the pipeline would rewrite the holo card and seed a second announcement,
        while skipping ingestion entirely would silently stop refreshing
        memories on every reconnect from here on."""
        externals.inbox = [_gmail_message(i) for i in range(4)]
        externals.sent_emails = [_sent_email(i) for i in range(8)]
        await complete_submit(client)
        await connect_gmail()
        await run_queued_jobs(arq_pool)
        seeded_after_first = list(externals.seeded_conversations)

        await connect_gmail()

        assert await queued_job_names(arq_pool) == [MEMORY_TASK]
        assert externals.seeded_conversations == seeded_after_first
        assert users.onboarding_of(USER_ID)[HOLO_CONVERSATION_ID_FIELD]

    async def test_a_legacy_user_who_already_has_a_card_is_not_re_run(
        self, client: AsyncClient, arq_pool: ArqRedis, users: _UserStore
    ):
        """Users who finished the pre-relocation onboarding carry `house` and no
        marker. Treating them as new hands them a second card."""
        await complete_submit(client)
        users.docs[USER_ID]["onboarding"][LEGACY_PERSONALIZATION_MARKER] = "explorer"

        await connect_gmail()

        assert await queued_job_names(arq_pool) == [MEMORY_TASK]

    async def test_a_queued_job_that_lost_the_race_does_nothing(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, users: _UserStore
    ):
        """A job can outlive a connect that already completed the pipeline. The
        run-time re-check is the only thing between that and a duplicate card."""
        externals.inbox = [_gmail_message(0)]
        await complete_submit(client)
        await connect_gmail()
        users.docs[USER_ID]["onboarding"][GMAIL_PERSONALIZATION_MARKER] = datetime.now(UTC)

        await run_queued_jobs(arq_pool)

        assert externals.seeded_conversations == []
        assert externals.notifications == []


class TestGmailIsNotActuallyConnected:
    async def test_the_pipeline_aborts_without_claiming_it_ran(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, users: _UserStore
    ):
        """Composio is the authority on the connection, not the callback. If the
        connection is gone by the time the job runs, marking it done would deny
        this user their personalization forever."""
        externals.has_gmail = False
        await complete_submit(client)
        await connect_gmail()

        # The connect handler enqueues optimistically; the job itself checks.
        await run_queued_jobs(arq_pool)

        onboarding = users.onboarding_of(USER_ID)
        assert GMAIL_PERSONALIZATION_MARKER not in onboarding
        assert externals.seeded_conversations == []


class TestThePipelineDegrades:
    async def test_a_style_model_outage_still_delivers_the_card(
        self,
        client: AsyncClient,
        arq_pool: ArqRedis,
        externals: _Externals,
        users: _UserStore,
        stages: _StageSink,
    ):
        """One node's model fails; the rest of the reward still has to arrive.
        The style card must resolve explicitly rather than spin forever."""
        externals.inbox = [_gmail_message(i) for i in range(4)]
        externals.sent_emails = [_sent_email(i) for i in range(8)]
        externals.llm_failures = {"onboarding_writing_style"}

        await complete_submit(client)
        await connect_gmail()
        await run_queued_jobs(arq_pool)

        assert stages.payload(OnboardingStage.WRITING_STYLE_READY)["style_summary"] is None
        assert "writing_style" not in users.onboarding_of(USER_ID)
        assert users.onboarding_of(USER_ID)["personality_phrase"] == HOLO_PHRASE
        assert len(externals.seeded_conversations) == 1

    async def test_an_empty_sent_folder_resolves_the_card_rather_than_spinning(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, stages: _StageSink
    ):
        """The frontend distinguishes "learned nothing" from "still learning",
        and only one of those ever stops spinning."""
        externals.inbox = [_gmail_message(i) for i in range(4)]
        externals.sent_emails = [_sent_email(0)]  # under the sampler's minimum

        await complete_submit(client)
        await connect_gmail()
        await run_queued_jobs(arq_pool)

        payload = stages.payload(OnboardingStage.WRITING_STYLE_READY)
        assert payload["style_summary"] is None
        assert payload["example"] is None
        assert stages.emitted(OnboardingStage.TRIAGE_READY)

    async def test_a_failed_seed_still_marks_the_pipeline_as_run(
        self, client: AsyncClient, arq_pool: ArqRedis, externals: _Externals, users: _UserStore
    ):
        """The announcement is a reward, not the work. Losing the marker because
        a conversation write failed would re-run the entire pipeline — and pay
        for the whole inbox scan again — on the user's next reconnect."""
        externals.inbox = [_gmail_message(0)]
        externals.seeding_fails = True

        await complete_submit(client)
        await connect_gmail()
        await run_queued_jobs(arq_pool)

        onboarding = users.onboarding_of(USER_ID)
        assert onboarding[GMAIL_PERSONALIZATION_MARKER]
        assert HOLO_CONVERSATION_ID_FIELD not in onboarding


# ---------------------------------------------------------------------------
# POST /onboarding/reset
# ---------------------------------------------------------------------------


@pytest.fixture
async def personalized(client: AsyncClient, arq_pool: ArqRedis, externals: _Externals) -> None:
    externals.integrations_connected = ["slack", "notion"]
    externals.memories_cleared = 7
    externals.todos_purged = 3
    externals.demo_conversations = 2
    externals.inbox = [_gmail_message(i) for i in range(4)]
    externals.sent_emails = [_sent_email(i) for i in range(8)]
    await complete_submit(client)
    await connect_gmail()
    await run_queued_jobs(arq_pool)


class TestResettingOnboarding:
    async def test_the_user_can_run_onboarding_again(
        self, client: AsyncClient, users: _UserStore, personalized: None
    ):
        """This is the only thing reset is for. If the subdoc survives, the next
        submit is treated as a replay and the user never gets back in."""
        await client.post(RESET)

        assert "onboarding" not in users.docs[USER_ID]
        again = await complete_submit(client)
        assert again.status_code == 200

    async def test_the_holo_card_conversation_is_torn_down(
        self, client: AsyncClient, externals: _Externals, personalized: None
    ):
        """Left behind, the user restarts onboarding still holding a chat that
        hands them a holo card built from the personalization they just wiped."""
        seeded_id = externals.seeded_conversations[0][0]

        body = (await client.post(RESET)).json()

        assert externals.conversations_deleted == [seeded_id]
        assert body["conversation_deleted"] == 1

    async def test_a_legacy_first_message_conversation_is_deleted_too(
        self, client: AsyncClient, externals: _Externals, users: _UserStore, personalized: None
    ):
        """Users from the pre-relocation flow carry both. Deleting only the new
        one leaves the old first-message chat orphaned forever — nothing else
        ever looks at that field again."""
        seeded_id = externals.seeded_conversations[0][0]
        users.docs[USER_ID]["onboarding"]["first_message_conversation_id"] = "conv-legacy"

        body = (await client.post(RESET)).json()

        assert externals.conversations_deleted == ["conv-legacy", seeded_id]
        assert body["conversation_deleted"] == 2

    async def test_everything_the_pipeline_created_is_counted_as_deleted(
        self, client: AsyncClient, personalized: None
    ):
        """The counts are what the reset screen shows back to the user."""
        body = (await client.post(RESET)).json()

        assert body["todos_deleted"] == 3
        assert body["demo_conversations_deleted"] == 2
        assert body["integrations_disconnected"] == 2
        assert body["memories_cleared"] == 7

    async def test_the_connected_integrations_are_disconnected(
        self, client: AsyncClient, externals: _Externals, personalized: None
    ):
        await client.post(RESET)

        assert externals.disconnected == ["slack", "notion"]

    async def test_a_live_pipeline_is_aborted_before_the_document_is_wiped(
        self, client: AsyncClient, arq_pool: ArqRedis, users: _UserStore
    ):
        """A job that survives the reset keeps writing stages onto the socket of
        a user who has already restarted, and re-marks a document that was
        supposed to be blank."""
        await complete_submit(client)
        await connect_gmail()
        job_id = users.onboarding_of(USER_ID)["intelligence_job_id"]

        await client.post(RESET)

        aborted = await arq_pool.zrange(abort_jobs_ss, 0, -1)
        assert [raw.decode() if isinstance(raw, bytes) else raw for raw in aborted] == [job_id]

    async def test_a_failed_abort_does_not_block_the_reset(
        self, client: AsyncClient, users: _UserStore, personalized: None
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
        assert body["conversation_deleted"] == 0
        assert externals.conversations_deleted == []


class TestTheRescueCronOnlyPicksUpTheGenuinelyStuck:
    """Only pre-relocation users can still be at personalization_pending, and
    the marker keeps the cron from re-running a pipeline that already ran."""

    async def test_a_user_whose_pipeline_already_ran_is_never_re_queued(
        self, client: AsyncClient, arq_pool: ArqRedis, users: _UserStore, personalized: None
    ):
        from app.workers.tasks.cleanup_tasks import cleanup_stuck_personalization

        stuck = await users.get(USER_ID)
        assert stuck is not None
        with patch(
            "app.workers.tasks.cleanup_tasks.user_repository.find_stuck_personalization",
            new_callable=AsyncMock,
            return_value=[stuck],
        ):
            result = await cleanup_stuck_personalization({}, max_age_minutes=30)

        assert "0 re-queued" in result
        assert await queued_job_names(arq_pool) == []
