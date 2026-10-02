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
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets
import shutil
import time
import uuid

from bson import ObjectId
import httpx
import pytest
from redis.asyncio import Redis

from app.agents.core.background.executor_queue import is_executor_busy
from app.config.feature_flags import FeatureFlag
from app.config.settings import settings
from app.constants.browser import BrowserEngine
from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX, SUBSCRIPTION_PLAN_CACHE_TTL
from app.constants.llm import LLMProviderName
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
from app.db.redis import _new_client, redis_cache
from app.db.repositories.subscriptions import subscription_repository
from app.models.payment_models import PlanType, SubscriptionDocument
from app.schemas.browser_job import BrowserJobState
from app.services.browser.handoff import get_handoff, get_pending_handoff_for_reply
from app.services.browser.jobs import get_job_state, get_latest_job
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

_TELEGRAM = "telegram"
_BOT_KEY = "browser-stack-bot-key-" + "x" * 16
_BOT_SESSION_SECRET = "browser-stack-session-" + "y" * 42  # pragma: allowlist secret
_FAKE_MODEL = "browser-stack-model"
_FAKE_KEY = "browser-stack-model-key"  # pragma: allowlist secret
_POLL_SECONDS = 0.2
#: How long a whole browser run may take in this stack before a scenario gives up on it.
RUN_SECONDS = 120.0


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

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.site = FixtureSite()
        self.models = FakeModels()
        self.redis_url = worker_redis_url(settings.REDIS_URL or "redis://localhost:6379/0")
        self.api_port = pick_free_port()
        #: One key for both hosts: the worker presents the same BROWSER_HOST_KEY to each.
        self.host_key = secrets.token_hex(16)
        self.observer = OutboundObserver(settings.RABBITMQ_URL)
        self.chrome: BrowserHost | None = None
        self.obscura: BrowserHost | None = None
        self.worker: BrowserWorker | None = None
        self.api: StackProcess | None = None
        self.redis: Redis | None = None
        self._patches: pytest.MonkeyPatch = pytest.MonkeyPatch()

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        await self.site.start()
        await self.models.start()
        self.chrome = browser_host(
            BrowserEngine.CHROMIUM,
            required_binary("CHROMIUM_BIN", "google-chrome"),
            self.host_key,
            self.site.origins,
            self.log_dir,
        )
        self.obscura = browser_host(
            BrowserEngine.OBSCURA,
            required_binary("OBSCURA_BIN"),
            self.host_key,
            self.site.origins,
            self.log_dir,
        )
        env = child_environment(self._app_environment())
        self.worker = BrowserWorker(env, self.log_dir)
        self.api = api_process(env, self.api_port, self.log_dir)
        for process in (self.chrome.process, self.obscura.process, self.api):
            process.start()
        await asyncio.gather(
            self.chrome.wait_ready(),
            self.obscura.wait_ready(),
            self.worker.start(),
            self.api.wait_for_line(API_READY_LINE),
        )
        self._read_the_stacks_redis()
        await self.observer.start()

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
        if self.redis is not None:
            await self.redis.flushdb()
            await self.redis.aclose()
        self._patches.undo()

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
        }

    def _read_the_stacks_redis(self) -> None:
        """Point this process's Redis helpers (job state, handoffs, the plan cache) at the stack's database."""
        self.redis = Redis.from_url(self.redis_url, decode_responses=True)
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
        async with httpx.AsyncClient(base_url=self.api_url, timeout=RUN_SECONDS) as client:
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

    async def finished(self, job_id: str, *, timeout: float = RUN_SECONDS) -> BrowserJobState:
        """Wait for a job's DONE state and return it."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = await get_job_state(job_id)
            if state is not None and state.result is not None:
                return state
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
            state = await get_job_state(job_id) if job_id else None
            running = state is not None and state.result is None
            idle = not running and not await is_executor_busy(conversation_id)
            quiet = quiet + 1 if idle and await self.observer.drained() else 0
            if quiet >= 2:
                return
            await asyncio.sleep(1.0)
        raise AssertionError(f"{conversation_id} never went quiet within {timeout}s\n{self.logs()}")

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

    async def decide_on_live_page(self, live_url: str, decision: str) -> int:
        """Press the live view page's Done ("continue") or Cancel, as its buttons do."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{live_url}/decision", json={"decision": decision})
        return response.status_code


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
