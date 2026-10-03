"""One whole browser stack, and the handles a scenario drives it by.

The API runs in this process on a real port (the production app and
middleware, booted as boot.py says); the ARQ browser worker and two browser
hosts (Chrome, and Obscura behind it) are child processes; the models and the
two-origin fixture site are local servers; the outbound Telegram queue is read
as transcripts. A scenario talks to it the way the Telegram bot does: messages
to /api/v1/bot/chat-stream, /stop to /api/v1/bot/reset-session, and the live
view's own decision endpoint for a handoff's Done and Cancel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

from browser_use import Browser
from bson import ObjectId
from cryptography.fernet import Fernet
import httpx
import psutil
import pytest
from redis.asyncio import Redis

from app.agents.core.background.executor_queue import is_executor_busy
from app.config.feature_flags import FeatureFlag
from app.config.settings import settings
from app.constants.browser import BrowserEngine, JobEnding
from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX, SUBSCRIPTION_PLAN_CACHE_TTL
from app.constants.llm import LLMProviderName
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
from app.db.redis import _new_client, redis_cache
from app.db.repositories.subscriptions import subscription_repository
from app.models.payment_models import PlanType, SubscriptionDocument
from app.schemas.browser import BrowserResultSnapshot
from app.services.browser.handoff import get_handoff, get_pending_handoff_for_reply
from app.services.browser.job_events import JOB_TERMINAL_FRAME, read_job_events
from app.services.browser.jobs import done_state, get_latest_job
from app.services.browser.registry import get_session_entry
from app.services.dev_service import mint_dev_user, seed_dev_data
from app.services.feature_flags import set_user_flag
from tests.helpers import pick_free_port, worker_redis_url
from tests.integration.real.browser._stack.fake_models import FakeModels
from tests.integration.real.browser._stack.fixture_site import FixtureSite
from tests.integration.real.browser._stack.observe import OutboundObserver, Transcript
from tests.integration.real.browser._stack.processes import (
    API_READY_LINE,
    BrowserHost,
    BrowserWorker,
    StackProcess,
    api_process,
    browser_host,
    child_environment,
)
from tests.integration.real.browser._stack.progress import Progress
from tests.integration.real.browser._stack.tls import FixtureTls, issue

_TELEGRAM = "telegram"
_BOT_KEY = "browser-stack-bot-key-" + "x" * 16
_BOT_SESSION_SECRET = "browser-stack-session-" + "y" * 42  # pragma: allowlist secret
_FAKE_MODEL = "browser-stack-model"
_FAKE_KEY = "browser-stack-model-key"  # pragma: allowlist secret
_POLL_SECONDS = 0.2
#: The key a stack claims its Redis database by, and how long a claim lives unrefreshed.
_CLAIM_KEY = "browser-stack:owner"
_CLAIM_SECONDS = 60
#: How long acting in the run's own page (attach, then one script) may take.
_LIVE_PAGE_SECONDS = 30.0
#: How long a whole browser run may take in this stack before a scenario gives up on it.
RUN_SECONDS = 120.0
#: One scenario's cap, the stack's boot included for a module's first: the boot's own
#: deadlines (READY_SECONDS) plus a scenario's two longest waits, with room to say why.
SCENARIO_SECONDS = 480


def required_binary(variable: str, fallback: str | None = None) -> str:
    """Return the browser binary a host needs; a missing one fails the stack, never skips it."""
    found = os.environ.get(variable) or (shutil.which(fallback) if fallback else None)
    if not found:
        pytest.fail(f"the browser stack needs {variable} (the engine binary a host launches)")
    return found


@dataclass(frozen=True)
class BotUser:
    """A GAIA user linked to a Telegram account, as the bot addresses them."""

    user_id: str
    telegram_id: str


@dataclass(frozen=True)
class BotReply:
    """What one chat-stream turn answered: its text, and the conversation it ran in."""

    text: str
    conversation_id: str | None
    error: str | None


class BrowserStack:
    """The whole browser path, wired together and observable."""

    def __init__(self, log_dir: Path, progress: Progress) -> None:
        self.log_dir = log_dir
        self.progress = progress
        self.site = FixtureSite()
        self.models = FakeModels()
        self.redis_url = worker_redis_url(settings.REDIS_URL or "redis://localhost:6379/0")
        self.api_port = pick_free_port()
        #: One key for both hosts: the worker presents the same BROWSER_HOST_KEY to each.
        self.host_key = secrets.token_hex(16)
        #: Encrypts the logins a run saves, as production's key does.
        self.state_key = Fernet.generate_key().decode()
        self.observer = OutboundObserver(settings.RABBITMQ_URL, progress)
        self.tls: FixtureTls | None = None
        self.chrome: BrowserHost | None = None
        self.obscura: BrowserHost | None = None
        self.worker: BrowserWorker | None = None
        self.api: StackProcess | None = None
        self.redis: Redis | None = None
        self._patches: pytest.MonkeyPatch = pytest.MonkeyPatch()
        self._claim: asyncio.Task[None] | None = None

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        say = self.progress.say
        say(
            f"booting on Redis {self.redis_url}, RabbitMQ {_without_credentials(settings.RABBITMQ_URL)}"
        )
        await self._own_the_redis_database()
        tls = self.tls = issue(self.log_dir)
        await self.site.start(tls)
        await self.models.start()
        say(f"fixture site at {self.site.a} and {self.site.b}, models at {self.models.base_url}")
        self.chrome = browser_host(
            BrowserEngine.CHROMIUM,
            required_binary("CHROMIUM_BIN", "google-chrome"),
            self.host_key,
            (self.site.origins, tls.ca_file),
            self.log_dir,
        )
        self.obscura = browser_host(
            BrowserEngine.OBSCURA,
            required_binary("OBSCURA_BIN"),
            self.host_key,
            (self.site.origins, tls.ca_file),
            self.log_dir,
        )
        env = child_environment(self._app_environment())
        self.worker = BrowserWorker(env, self.log_dir)
        self.api = api_process(env, self.api_port, self.log_dir)
        for process in (self.chrome.process, self.obscura.process, self.api):
            process.start()
        say(f"processes started; logs in {self.log_dir}")
        await asyncio.gather(
            self._phase("Chrome host answers healthz", self.chrome.wait_ready()),
            self._phase("Obscura host answers healthz", self.obscura.wait_ready()),
            self._phase("browser worker serves its queue", self.worker.start()),
            self._phase("API serves", self.api.wait_for_line(API_READY_LINE)),
        )
        self._read_the_stacks_redis()
        await self.observer.start()
        say("ready")

    async def _phase(self, what: str, waiting: Awaitable[None]) -> None:
        await waiting
        self.progress.say(what)

    async def _own_the_redis_database(self) -> None:
        """Claim this stack's Redis database, then empty it: its ARQ queue and job keys are this stack's alone.

        Two stacks on one database steal each other's browser jobs, so a held claim
        fails the boot naming its holder rather than letting the scenarios race.
        """
        self.redis = Redis.from_url(self.redis_url, decode_responses=True)
        holder = f"{socket.gethostname()}:{os.getpid()}"
        if not await self.redis.set(_CLAIM_KEY, holder, nx=True, ex=_CLAIM_SECONDS):
            raise RuntimeError(
                f"Redis {self.redis_url} is already a browser stack's (held by "
                f"{await self.redis.get(_CLAIM_KEY)}); give this run its own database "
                "(REDIS_URL / GAIA_REDIS_DB_BASE)"
            )
        await self.redis.flushdb()
        await self.redis.set(_CLAIM_KEY, holder, ex=_CLAIM_SECONDS)
        self._claim = asyncio.create_task(self._keep_claim(holder))

    async def _keep_claim(self, holder: str) -> None:
        redis = self.redis
        if redis is None:
            raise RuntimeError("the claim is kept only after it is made")
        while True:
            await asyncio.sleep(_CLAIM_SECONDS / 3)
            await redis.set(_CLAIM_KEY, holder, ex=_CLAIM_SECONDS)

    async def stop(self) -> None:
        await self.observer.stop()
        processes = (
            self.api,
            self.worker.process if self.worker else None,
            self.chrome.process if self.chrome else None,
            self.obscura.process if self.obscura else None,
        )
        for process in processes:
            if process is not None:
                process.stop()
        await self.models.stop()
        await self.site.stop()
        if self._claim is not None:
            self._claim.cancel()
            await asyncio.gather(self._claim, return_exceptions=True)
        if self.redis is not None:
            await self.redis.flushdb()
            await self.redis.aclose()
        self._patches.undo()
        self.progress.say("stopped")

    def logs(self) -> str:
        """Every process's log tail, for a failing scenario's report."""
        processes = [
            self.api,
            self.worker.process if self.worker else None,
            self.chrome.process if self.chrome else None,
            self.obscura.process if self.obscura else None,
        ]
        return "\n".join(p.tail() for p in processes if p is not None)

    def _app_environment(self) -> dict[str, str]:
        """Return what the API and the worker need beyond the test process's own environment."""
        if self.chrome is None or self.obscura is None:
            raise RuntimeError("the hosts are built before the app processes")
        return {
            "ENV": "development",
            "REDIS_URL": self.redis_url,
            "MONGO_DB_NAME": MONGO_DATABASE_NAME,
            "RABBITMQ_URL": settings.RABBITMQ_URL,
            "DEV_DEFAULT_MODEL": LLMProviderName.CUSTOM.value,
            "DEV_LLM_BASE_URL": self.models.base_url,
            "DEV_LLM_API_KEY": _FAKE_KEY,
            "DEV_LLM_MODEL": _FAKE_MODEL,
            "DEV_LLM_API": "chat_completions",
            "OPENROUTER_BASE_URL": self.models.base_url,
            "OPENROUTER_API_KEY": _FAKE_KEY,
            "BROWSER_JEV_PROVIDER": "openrouter",
            "GOOGLE_GEMINI_BASE_URL": self.models.gemini_base_url,
            "BROWSER_HOST_URL": self.obscura.url,
            "BROWSER_HOST_KEY": self.host_key,
            "BROWSER_FALLBACK_HOST_URL": self.chrome.url,
            "HOST": self.api_url,
            "BROWSER_LIVE_VIEW_BASE_URL": self.api_url,
            "GAIA_BOT_API_KEY": _BOT_KEY,
            "BOT_SESSION_TOKEN_SECRET": _BOT_SESSION_SECRET,
            "BROWSER_STATE_ENCRYPTION_KEY": self.state_key,
        }

    def _read_the_stacks_redis(self) -> None:
        """Point this process's Redis helpers (job state, handoffs, the plan cache) at the stack's database."""
        self._patches.setattr(redis_cache, "redis", _new_client(self.redis_url))

    # --- users and chats ------------------------------------------------------

    async def new_user(self) -> BotUser:
        """Mint a user through the real signup path, link a Telegram account, and make them PRO."""
        email = f"browser-stack-{uuid.uuid4().hex[:10]}@gaia.test"
        user = await mint_dev_user(email)
        seeded = await seed_dev_data(email, todos=0, conversations=0, platform_links=[_TELEGRAM])
        await _make_pro(user.id)
        return BotUser(user_id=user.id, telegram_id=seeded.platform_user_ids[_TELEGRAM])

    async def watch(self, destination_id: str) -> Transcript:
        return await self.observer.watch(destination_id)

    async def say(self, user: BotUser, text: str, *, channel_id: str | None = None) -> BotReply:
        """Send one message as the Telegram bot would, and read the turn's reply."""
        body = {
            "message": text,
            "platform": _TELEGRAM,
            "platform_user_id": user.telegram_id,
            "channel_id": channel_id,
            "is_dm": channel_id is None,
        }
        chunks: list[str] = []
        conversation_id: str | None = None
        error: str | None = None
        # Keepalive frames reset a read timeout, so a turn that never ends is bounded as a whole.
        async with (
            asyncio.timeout(RUN_SECONDS),
            httpx.AsyncClient(base_url=self.api_url, timeout=RUN_SECONDS) as client,
        ):
            async with client.stream(
                "POST", "/api/v1/bot/chat-stream", json=body, headers=self._bot_headers(user)
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    raise AssertionError(
                        f"chat-stream answered {response.status_code}: {response.text}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    frame = json.loads(line.removeprefix("data:").strip())
                    if "text" in frame:
                        chunks.append(frame["text"])
                    if "error" in frame:
                        error = str(frame["error"])
                    if frame.get("done"):
                        conversation_id = frame.get("conversation_id")
        return BotReply(text="".join(chunks), conversation_id=conversation_id, error=error)

    async def stop_command(self, user: BotUser, *, channel_id: str | None = None) -> None:
        """Send /stop the way the bot does: a session reset for that chat."""
        async with httpx.AsyncClient(base_url=self.api_url, timeout=30) as client:
            response = await client.post(
                "/api/v1/bot/reset-session",
                json={
                    "platform": _TELEGRAM,
                    "platform_user_id": user.telegram_id,
                    "channel_id": channel_id,
                    "is_dm": channel_id is None,
                },
                headers=self._bot_headers(user),
            )
            if response.status_code != 200:
                raise AssertionError(
                    f"reset-session answered {response.status_code}: {response.text}"
                )

    def _bot_headers(self, user: BotUser) -> dict[str, str]:
        return {
            "X-Bot-API-Key": _BOT_KEY,
            "X-Bot-Platform": _TELEGRAM,
            "X-Bot-Platform-User-Id": user.telegram_id,
        }

    async def set_obscura(self, user: BotUser) -> None:
        """Opt the user into the fast engine through the settings toggle's own path."""
        await set_user_flag(user.user_id, FeatureFlag.BROWSER_OBSCURA.value, True)

    # --- the run --------------------------------------------------------------

    async def job_for(self, conversation_id: str, *, timeout: float = 30.0) -> str:
        """Return the job a conversation's turn started, once it is recorded."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job_id = await get_latest_job(conversation_id)
            if job_id is not None:
                return job_id
            await asyncio.sleep(_POLL_SECONDS)
        raise AssertionError(f"no browser job started in {conversation_id} within {timeout}s")

    async def finished(self, job_id: str, *, timeout: float = RUN_SECONDS) -> BrowserResultSnapshot:
        """Wait for a job to end, its feed closed, and return the result card it ended on."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frames = await _feed(job_id)
            if await done_state(job_id) is not None and JOB_TERMINAL_FRAME in frames:
                results = [
                    card
                    for frame in frames
                    for card in _cards_in(frame)
                    if card.get("kind") == "result"
                ]
                return BrowserResultSnapshot.model_validate(results[-1])
            if self.worker is not None:
                self.worker.process.assert_alive()
            await asyncio.sleep(_POLL_SECONDS)
        raise AssertionError(f"job {job_id} did not end within {timeout}s\n{self.logs()}")

    async def settled(self, conversation_id: str, *, timeout: float = RUN_SECONDS) -> None:
        """Wait until nothing more can be said in a conversation: no executor run, no job running, no message in flight.

        Holds twice in a row, a poll apart, so a run that a delivery just woke is seen.
        """
        deadline = time.monotonic() + timeout
        quiet = 0
        while time.monotonic() < deadline:
            job_id = await get_latest_job(conversation_id)
            running = job_id is not None and await done_state(job_id) is None
            idle = not running and not await is_executor_busy(conversation_id)
            quiet = quiet + 1 if idle and await self.observer.drained() else 0
            if quiet >= 2:
                return
            await asyncio.sleep(1.0)
        raise AssertionError(f"{conversation_id} never went quiet within {timeout}s\n{self.logs()}")

    async def handoff_waiting(self, user: BotUser) -> bool:
        """Whether a bot run of this user is waiting on the user right now."""
        handoff_id = await get_pending_handoff_for_reply(f"{_TELEGRAM}:{user.user_id}")
        return handoff_id is not None and await get_handoff(handoff_id) is not None

    async def pending_handoff(self, user: BotUser, *, timeout: float = RUN_SECONDS) -> str:
        """Return the handoff a bot run of this user is waiting on, once it is raised."""
        address = f"{_TELEGRAM}:{user.user_id}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            handoff_id = await get_pending_handoff_for_reply(address)
            if handoff_id is not None and await get_handoff(handoff_id) is not None:
                return handoff_id
            await asyncio.sleep(_POLL_SECONDS)
        raise AssertionError(f"no handoff was raised within {timeout}s\n{self.logs()}")

    async def ending(self, job_id: str) -> JobEnding | None:
        """Return how the job's ending was recorded: stopped or finished, None while it runs."""
        ended = await done_state(job_id)
        return ended.ending if ended is not None else None

    async def sessions_of(self, job_id: str) -> list[str]:
        """Return every browser session the run opened, in order: one, or two after a move to Chrome."""
        sessions = [
            str(card["session_id"])
            for frame in await _feed(job_id)
            for card in _cards_in(frame)
            if card.get("kind") == "session"
        ]
        return list(dict.fromkeys(sessions))

    async def in_live_page(self, job_id: str, script: str) -> object:
        """Run JS in the run's own page, the way a person acts in the live view during a handoff.

        Dialled with the session's own token, as the live view is: the host refuses a bare /cdp/<id>.
        """
        sessions = await self.sessions_of(job_id)
        if not sessions:
            raise AssertionError(f"job {job_id} has opened no browser session")
        session_id = sessions[-1]
        entry = await get_session_entry(session_id)
        if entry is None or not entry.live_ws:
            raise AssertionError(f"session {session_id} has no live view")
        live = urlsplit(entry.live_ws)
        cdp = live._replace(path=live.path.replace(f"/live/{session_id}", f"/cdp/{session_id}"))
        browser = Browser(cdp_url=cdp.geturl())
        async with asyncio.timeout(_LIVE_PAGE_SECONDS):
            await browser.start()
        try:
            session = await browser.get_or_create_cdp_session(focus=False)
            async with asyncio.timeout(_LIVE_PAGE_SECONDS):
                result = await session.cdp_client.send.Runtime.evaluate(
                    params={"expression": script, "awaitPromise": True, "returnByValue": True},
                    session_id=session.session_id,
                )
            return result.get("result", {}).get("value")
        finally:
            await browser.stop()

    async def page_reaches(self, job_id: str, path: str, *, timeout: float = 30.0) -> None:
        """Wait until the run's page is on path, read from the page itself."""
        deadline = time.monotonic() + timeout
        seen: object = None
        while time.monotonic() < deadline:
            seen = await self.in_live_page(job_id, "location.pathname")
            if seen == path:
                return
            await asyncio.sleep(_POLL_SECONDS)
        raise AssertionError(f"the run's page never reached {path} (last on {seen})")

    def kill_obscura_engine(self) -> None:
        """SIGKILL the Obscura engine under its host, as an engine crash would end it."""
        if self.obscura is None or self.obscura.process.proc is None:
            raise RuntimeError("the Obscura host is not running")
        engines = [
            child
            for child in psutil.Process(self.obscura.process.proc.pid).children(recursive=True)
            if "obscura" in child.name()
        ]
        if not engines:
            raise AssertionError("the Obscura host runs no engine to kill")
        for engine in engines:
            engine.kill()

    async def decide_on_live_page(self, live_url: str, decision: str) -> int:
        """Press the live view page's Done ("continue") or Cancel, as its buttons do.

        The link opens the web app's page; its buttons answer on this API's /live/{code}/decision.
        """
        code = urlsplit(live_url).path.rstrip("/").rsplit("/", 1)[-1]
        async with httpx.AsyncClient(base_url=self.api_url, timeout=30) as client:
            response = await client.post(f"/live/{code}/decision", json={"decision": decision})
        return response.status_code


async def _feed(job_id: str) -> list[dict[str, object]]:
    """Return every frame the job's feed holds now, its closing frame included."""
    return [payload for _, payload in await read_job_events(job_id, "0-0")]


def _without_credentials(url: str) -> str:
    parts = urlsplit(url)
    host = f"{parts.hostname or ''}{f':{parts.port}' if parts.port else ''}"
    return parts._replace(netloc=host).geturl()


def _cards_in(frame: Any) -> list[dict[str, Any]]:
    """Return every card a feed frame carries, however deep its envelope nests it."""
    if not isinstance(frame, dict):
        return []
    found = [frame] if "kind" in frame else []
    for value in frame.values():
        found.extend(_cards_in(value))
    return found


async def _make_pro(user_id: str) -> None:
    """Both halves of PRO state the paid gate reads: the subscription row and the plan cache."""
    now = datetime.now(UTC)
    await subscription_repository.create(
        SubscriptionDocument(
            dodo_subscription_id=f"sub_browser_stack_{ObjectId()}",
            user_id=user_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    await redis_cache.set(
        f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}",
        {"plan_type": PlanType.PRO.value},
        ttl=SUBSCRIPTION_PLAN_CACHE_TTL,
    )
