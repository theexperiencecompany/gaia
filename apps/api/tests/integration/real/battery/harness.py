"""Drive one real browser task the way a Telegram user does, and read what really happened.

Nothing here is faked: the message goes through the bot harness (the real bot
pipeline emulating Telegram) into the running API, the comms and executor
agents, the ARQ worker, the browser host and the engine, against real sites.
Assertions read the run's own artifacts: the job state in Redis, the task
history in Mongo, the handoff record, the saved logins, and the transcript of
what the bot delivered (text, photos).

Requires the native dev stack (see the driving-gaia skill and
~/.cache/gaia-browser/run/boot.sh) and GAIA_BROWSER_BATTERY=1.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass, field
import html
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Any, TypeVar, cast
from urllib.parse import urlsplit
import uuid

import httpx
import pymongo
from pymongo.database import Database
import redis

from app.constants.browser import (
    BROWSER_HANDOFF_CONV_KEY_PREFIX,
    BROWSER_HANDOFF_KEY_PREFIX,
    BROWSER_JOB_LOCK_PREFIX,
    BROWSER_JOB_STATE_PREFIX,
)
from app.constants.cache import EXECUTOR_BUSY_PREFIX, RATE_LIMIT_KEY_PREFIX
from app.core.provider_registration import register_lazy_providers
from app.db.repositories.browser_profiles import BrowserProfilesRepository
from app.memory.management import delete_all as forget_all_memories
from app.services.browser.host_client import get_session

T = TypeVar("T")

API_URL = os.environ.get("GAIA_BATTERY_API_URL", "http://localhost:8480")
#: The dev bot's own GAIA_API_URL: the bot fetches step-photo links on its own API
#: origin with its credentials, while any other origin hits the public-fetch guard,
#: which refuses the tailnet address the dev links resolve to.
BOT_API_URL = os.environ.get("GAIA_API_URL", API_URL)
LIVE_VIEW_BASE_URL = os.environ.get("BROWSER_LIVE_VIEW_BASE_URL", API_URL)
HOST_URL = os.environ.get("BROWSER_HOST_URL", "http://localhost:8930")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
# Never a person's account: seeding links the harness's synthetic platform id, replacing a real one.
BATTERY_USER = os.environ.get("GAIA_BATTERY_USER", "dev@gaia.local")
RABBITMQ_MANAGEMENT_URL = os.environ.get("RABBITMQ_MANAGEMENT_URL", "http://localhost:15672")
RABBITMQ_MANAGEMENT_AUTH = ("guest", "guest")
#: The queue the emulated Telegram bot consumes; any other consumer on it takes
#: a share of the replies, and the transcript then misses them at random.
OUTBOUND_QUEUE = "outbound.telegram"
REPO_ROOT = Path(__file__).resolve().parents[6]
HARNESS_DIR = REPO_ROOT / "apps" / "bots" / "harness"

#: One scenario end to end, sized for a slow link (2026-09-22 at ~70 KB/s: a page
#: load ran 30-90 s, a two-site task 13 min); the outcome reports the duration.
RUN_TIMEOUT_SECONDS = 1200.0
#: Comms voices the outcome after the job ends, so the sender's consumer outlives
#: the run; SIGTERM cuts the window short once done.
SENDER_WINDOW_SECONDS = RUN_TIMEOUT_SECONDS + 120.0
#: After the job ends the executor still voices the outcome; the reply is out
#: once the conversation's executor lock is released. Bounded by the chat
#: model's own invoke timeout (LLM_INVOKE_TIMEOUT_SECONDS), plus delivery.
OUTCOME_WAIT_SECONDS = 330.0
OUTCOME_DELIVERY_SECONDS = 15.0
#: One chat turn from the harness, bounded by the chat model's invoke timeout.
REPLY_TIMEOUT_SECONDS = 330.0
_POLL_SECONDS = 2.0
#: How gaia-sim's console reports a send it could not finish (apps/bots/harness/src/cli.ts).
_SENDER_FAILED = "gaia-sim failed:"
#: What a Telegram user types to answer a handoff (the prompt's own words).
_HANDOFF_REPLIES = {"continue": "done", "cancel": "stop"}


def battery_enabled() -> bool:
    return os.environ.get("GAIA_BROWSER_BATTERY") == "1"


def stack_answers() -> bool:
    try:
        return httpx.get(f"{API_URL}/api/v1/todos", timeout=5).status_code == 200 and (
            httpx.get(f"{HOST_URL}/healthz", timeout=5).json().get("chromium_up") is True
        )
    except Exception:
        return False


def outbound_consumers() -> int:
    """How many consumers already hold the bot's outbound queue (a real bot, an orphaned sender)."""
    response = httpx.get(
        f"{RABBITMQ_MANAGEMENT_URL}/api/queues/%2F/{OUTBOUND_QUEUE}",
        auth=RABBITMQ_MANAGEMENT_AUTH,
        timeout=5,
    )
    if response.status_code == 404:
        return 0
    response.raise_for_status()
    return int(response.json().get("consumers") or 0)


def drain_battery_leftovers(battery_user_id: str) -> int:
    """Purge the outbound queue of an earlier battery's undelivered replies; returns how many.

    The first sender would otherwise record them, and the ones sent to the
    user's DM are kept by every transcript. Refuses when any delivery is for
    anyone else: with the real bot stopped, those are a person's messages.
    """
    queue = f"{RABBITMQ_MANAGEMENT_URL}/api/queues/%2F/{OUTBOUND_QUEUE}"
    peeked = httpx.post(
        f"{queue}/get",
        json={"count": 10_000, "ackmode": "reject_requeue_true", "encoding": "auto"},
        auth=RABBITMQ_MANAGEMENT_AUTH,
        timeout=30,
    )
    if peeked.status_code == 404:
        return 0
    peeked.raise_for_status()
    destinations = {
        str(json.loads(message["payload"]).get("destination_id")) for message in peeked.json()
    }
    others = {
        d
        for d in destinations
        if d != f"dev-telegram-{battery_user_id}" and not d.startswith("battery-")
    }
    assert not others, (
        f"{OUTBOUND_QUEUE} holds deliveries for {sorted(others)}, not the battery's: "
        "deliver or inspect them before running the battery"
    )
    if destinations:
        httpx.delete(
            f"{queue}/contents", auth=RABBITMQ_MANAGEMENT_AUTH, timeout=30
        ).raise_for_status()
    return len(peeked.json())


class Sender(subprocess.Popen[str]):
    """A bot-harness sender process, with its transcript file, its console and the chat it posts to."""

    transcript_path: Path
    console_path: Path
    channel: str

    def failure(self) -> str | None:
        """Return why the sender gave up, as its console says, or None while it has not."""
        failed = [
            line
            for line in self.console_path.read_text(errors="replace").splitlines()
            if line.startswith(_SENDER_FAILED)
        ]
        return failed[-1] if failed else None


@dataclass
class Transcript:
    """What the bot delivered for one turn, from the harness's JSONL."""

    events: list[dict[str, Any]]

    @property
    def texts(self) -> list[str]:
        return [
            str(e.get("text", ""))
            for e in self.events
            if e.get("type") in ("send", "outbound-delivery") and e.get("text")
        ]

    @property
    def photos(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("type") in ("rich", "outbound-attachment")]

    def texts_matching(self, pattern: str) -> list[str]:
        return [t for t in self.texts if re.search(pattern, t, re.I | re.S)]


@dataclass
class RunOutcome:
    """One finished (or stopped) browser run, read back from the stack."""

    job_id: str
    state: dict[str, Any]
    task_record: dict[str, Any] | None
    transcript: Transcript
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    #: Message sent to job done, so a slow pass is visible next to a failure.
    seconds: float = 0.0

    @property
    def summary(self) -> str:
        return str(((self.state.get("result") or {}).get("summary")) or "")

    @property
    def status(self) -> str:
        return str((self.state.get("result") or {}).get("status", ""))

    @property
    def success(self) -> bool | None:
        result = self.state.get("result") or {}
        return result.get("success") if result else None

    @property
    def step_count(self) -> int:
        return int((self.task_record or {}).get("steps") or 0)


class Battery:
    """The stack, as one scenario sees it."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        bot_origin, links_origin = urlsplit(BOT_API_URL)[:2], urlsplit(LIVE_VIEW_BASE_URL)[:2]
        assert bot_origin == links_origin, (
            f"the bot's API ({BOT_API_URL}) is not the origin step photos link to "
            f"({LIVE_VIEW_BASE_URL}): the bot would refuse every photo"
        )
        consumers = outbound_consumers()
        assert consumers == 0, (
            f"{consumers} consumer(s) already hold {OUTBOUND_QUEUE}: stop the Telegram bot "
            "and any leftover harness sender before the battery, or replies go to them "
            "instead of the transcript"
        )
        self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        # An executor from an earlier, interrupted battery can still start a job
        # into this one; begin only once none is running.
        deadline = time.monotonic() + OUTCOME_WAIT_SECONDS
        while time.monotonic() < deadline and next(
            self.redis.scan_iter(f"{EXECUTOR_BUSY_PREFIX}*"), None
        ):
            time.sleep(_POLL_SECONDS)
        #: Every sender started, so none outlives the battery holding the queue.
        self.senders: list[Sender] = []
        self.mongo: Database[dict[str, Any]] = pymongo.MongoClient(MONGO_URL)["GAIA"]
        if self.mongo["users"].find_one({"email": BATTERY_USER}, {"_id": 1}):
            print(f"drained {drain_battery_leftovers(self.battery_user_id())} leftover replies")
        # The memory store is reached through the app's own providers, whose
        # clients belong to the loop that first used them: one loop for the battery.
        register_lazy_providers("main_app")
        self._loop = asyncio.new_event_loop()
        self.last_channel: str | None = None
        #: The replies sent into the current run's conversation ("stop", "done").
        self.replies: list[Sender] = []

    # -- sending -----------------------------------------------------------

    def send(
        self,
        message: str,
        *,
        settle_ms: int,
        channel: str | None = None,
        consume_outbound: bool = True,
    ) -> Sender:
        """Inject one Telegram message through the real bot pipeline; returns the live process.

        A fresh channel per scenario, since one conversation answers a repeat task
        from the earlier result; pass channel to continue one. consume_outbound=False
        while another sender consumes for the run: two consumers split deliveries.
        """
        run_id = uuid.uuid4().hex[:8]
        out = self.out_dir / f"{run_id}.jsonl"
        self.last_channel = channel or f"battery-{uuid.uuid4().hex[:10]}"
        cmd = [
            "infisical",
            "run",
            "--env=development",
            "--",
            "pnpm",
            "tsx",
            "src/cli.ts",
            "send",
            "--emulate",
            "telegram",
            "--user",
            BATTERY_USER,
            "--api",
            BOT_API_URL,
            "--channel",
            self.last_channel,
            "--settle",
            str(settle_ms),
            "--out",
            str(out),
            *([] if consume_outbound else ["--no-outbound"]),
            message,
        ]
        # Console to a file, never an unread pipe: a long run's logging filled it and
        # hung the sender. Own session, so killing it also kills children that would
        # otherwise keep consuming the outbound queue.
        console_path = self.out_dir / f"{run_id}.log"
        console = console_path.open("w")
        proc = Sender(
            cmd,
            cwd=HARNESS_DIR,
            stdout=console,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        proc.transcript_path = out
        proc.console_path = console_path
        proc.channel = self.last_channel
        self.senders.append(proc)
        return proc

    def close(self) -> None:
        """Kill any sender still running; a leftover keeps consuming the bot's queue."""
        for proc in self.senders:
            self.stop_sender(proc)
        self._loop.close()

    def run_async(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run one of the app's coroutines on the battery's own loop."""
        return self._loop.run_until_complete(coro)

    @staticmethod
    def stop_sender(proc: subprocess.Popen[str]) -> None:
        """End a sender and every process it started, transcript or not."""
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=10)

    @staticmethod
    def finish_sender(proc: subprocess.Popen[str]) -> None:
        """Tell a settling sender to write its transcript and exit now."""
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

    def transcript_of(self, proc: Sender, replies: Sequence[Sender] = ()) -> Transcript:
        """Everything the conversation showed its user: the sender's chat and the replies sent into it.

        The sim consumes the whole outbound queue, so other scenarios' chats are
        dropped (only this chat and the user's DM count). A reply's answer streams
        into that reply's sender, so senders are merged in wall-clock order.
        """
        channel = proc.channel
        events = []
        for sender in (proc, *replies):
            # A sender that died read as a run that said nothing ("no outcome reply").
            failure = sender.failure()
            assert failure is None, f"the harness sender failed, not the run: {failure}"
            path = sender.transcript_path
            assert path.exists(), f"the harness sender recorded nothing; see {sender.console_path}"
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                destination = str(event.get("destinationId") or "")
                if destination.startswith("battery-") and destination != channel:
                    continue
                events.append(event)
        return Transcript(sorted(events, key=lambda event: float(event["at"])))

    # -- the account's quota --------------------------------------------------

    def forget_memories(self) -> None:
        """Wipe what the battery account remembers, so no scenario is answered from an earlier one.

        The battery repeats the same tasks run after run; with their outcomes in
        memory, the executor once answered "log me in" from the last run's result
        instead of opening the browser.
        """
        self.run_async(forget_all_memories(self.battery_user_id()))

    def reset_browser_quota(self) -> None:
        """Clear the battery account's browser-task usage: a day of scenarios is more than any plan allows."""
        user_id = self.battery_user_id()
        for key in self.redis.scan_iter(f"{RATE_LIMIT_KEY_PREFIX}:{user_id}:browser_task:*"):
            self.redis.delete(key)

    # -- reading the run ----------------------------------------------------

    def job_ids(self) -> list[str]:
        return [
            k.removeprefix(BROWSER_JOB_STATE_PREFIX)
            for k in self.redis.scan_iter(f"{BROWSER_JOB_STATE_PREFIX}*")
            if ":" not in k.removeprefix(BROWSER_JOB_STATE_PREFIX)
        ]

    def stored(self, key: str) -> Any:
        """Return the JSON value the app's cache holds at key, or None (the client decodes to str)."""
        raw = cast(str | None, self.redis.get(key))
        return json.loads(raw) if raw else None

    def job_state(self, job_id: str) -> dict[str, Any]:
        return self.stored(f"{BROWSER_JOB_STATE_PREFIX}{job_id}") or {}

    def wait_for_job(self, *, timeout: float = 240.0, proc: Sender | None = None) -> str:
        """Return the browser job running in this scenario's own conversation.

        Read from the conversation's slot, never "the newest job": an executor
        left over from an earlier scenario can start a job at any moment.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            conversation = self.conversation_id_or_none()
            job_id = conversation and self.redis.get(f"{BROWSER_JOB_LOCK_PREFIX}{conversation}")
            if job_id:
                return str(job_id)
            if proc is not None and proc.poll() is not None:
                break
            time.sleep(_POLL_SECONDS / 4)
        said = self.transcript_of(proc).texts if proc is not None else []
        raise AssertionError(f"no browser job was enqueued for the message; the bot said {said}")

    def wait_for_status(self, job_id: str, statuses: set[str], *, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.job_state(job_id)
            if state.get("status") in statuses:
                return state
            time.sleep(_POLL_SECONDS)
        raise AssertionError(f"job {job_id} never reached {statuses}: {self.job_state(job_id)}")

    def task_record(self, session_id: str | None) -> dict[str, Any] | None:
        """Return the task-history row for this run's browser session (written when the run ends)."""
        if not session_id:
            return None
        return self.mongo["browser_tasks"].find_one({"session_id": session_id})

    def stop_run(self, job_id: str) -> None:
        """End a run the scenario gave up on, as its user would, before the next scenario starts.

        Left running, its progress lines (sent to the user's DM, which every
        scenario's transcript keeps) and its outcome land in the next scenario.
        """
        if self.job_state(job_id).get("status") == "done":
            return
        self.reply("stop")
        self.wait_for_status(job_id, {"done"}, timeout=RUN_TIMEOUT_SECONDS / 4)
        self.wait_for_outcome_voiced()

    def wait_for_outcome_voiced(self) -> None:
        """Wait until this conversation's executor has finished and so has sent its reply."""
        busy = f"{EXECUTOR_BUSY_PREFIX}{self.conversation_id()}"
        started = time.monotonic()
        deadline = started + OUTCOME_WAIT_SECONDS
        while time.monotonic() < deadline and self.redis.exists(busy):
            time.sleep(_POLL_SECONDS)
        print(f"outcome voiced {time.monotonic() - started:.0f}s after the job ended")
        time.sleep(OUTCOME_DELIVERY_SECONDS)

    # -- handoffs ----------------------------------------------------------

    def conversation_id_or_none(self) -> str | None:
        """Return the GAIA conversation the last sent channel maps to, once the bot has created it."""
        user = self.mongo["users"].find_one({"email": BATTERY_USER}, {"_id": 1})
        if not user or not self.last_channel:
            return None
        key = f"telegram:dev-telegram-{user['_id']}:{self.last_channel}"
        session = self.mongo["bot_sessions"].find_one({"session_key": key}, {"conversation_id": 1})
        return str(session["conversation_id"]) if session else None

    def conversation_id(self) -> str:
        conversation = self.conversation_id_or_none()
        assert conversation, f"no bot session for channel {self.last_channel}"
        return conversation

    def pending_handoff(self, conversation_id: str) -> tuple[str, dict[str, Any]] | None:
        # The app's cache stores the id JSON-encoded, quotes included.
        handoff_id = self.stored(f"{BROWSER_HANDOFF_CONV_KEY_PREFIX}{conversation_id}")
        if not handoff_id:
            return None
        record = self.stored(f"{BROWSER_HANDOFF_KEY_PREFIX}{handoff_id}") or {}
        return (str(handoff_id), record) if record.get("status") == "pending" else None

    def wait_for_handoff(
        self, job_id: str, *, timeout: float = 300.0
    ) -> tuple[str, dict[str, Any]]:
        """Return the handoff this scenario's run raises; fails as soon as the run ends without one."""
        conversation_id = self.conversation_id()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.pending_handoff(conversation_id)
            if found:
                return found
            state = self.job_state(job_id)
            if state.get("status") == "done":
                raise AssertionError(f"the run ended without a handoff: {state.get('result')}")
            time.sleep(_POLL_SECONDS)
        raise AssertionError(f"no handoff was raised for conversation {conversation_id}")

    def handoff_status(self, handoff_id: str) -> str:
        return str(
            (self.stored(f"{BROWSER_HANDOFF_KEY_PREFIX}{handoff_id}") or {}).get("status", "")
        )

    def wait_while_pending(self, handoff_id: str, *, timeout: float) -> str:
        """Return the handoff's status once it leaves pending, or "pending" at the timeout."""
        deadline = time.monotonic() + timeout
        status = self.handoff_status(handoff_id)
        while status == "pending" and time.monotonic() < deadline:
            time.sleep(_POLL_SECONDS / 2)
            status = self.handoff_status(handoff_id)
        return status

    def reply(self, message: str) -> None:
        """Send a message into this scenario's conversation mid-run, as the user does in Telegram.

        Its own reply streams into its own transcript; the run's deliveries stay
        with the scenario's sender, the only consumer on the queue.
        """
        proc = self.send(message, settle_ms=0, channel=self.last_channel, consume_outbound=False)
        self.replies.append(proc)
        try:
            proc.wait(timeout=REPLY_TIMEOUT_SECONDS)
        finally:
            self.stop_sender(proc)
        assert proc.returncode == 0, f"the reply {message!r} failed; see {proc.transcript_path}"

    def decide_handoff(self, handoff_id: str, decision: str) -> str:
        """Answer a pending handoff the way a Telegram user does: "done" or "stop" in the chat.

        The web card's decision endpoint belongs to the signed-in web user; the
        battery's user is a Telegram account, so it answers in the conversation.
        """
        self.reply(_HANDOFF_REPLIES[decision])
        return self.wait_while_pending(handoff_id, timeout=OUTCOME_DELIVERY_SECONDS)

    # -- saved logins ------------------------------------------------------

    # Read and cleared in the store: the API's dev auth bypass signs in as the
    # developer, whose own saved logins these calls once listed and deleted.

    def battery_user_id(self) -> str:
        user = self.mongo["users"].find_one({"email": BATTERY_USER}, {"_id": 1})
        assert user, f"no user for {BATTERY_USER}; a scenario has not seeded it yet"
        return str(user["_id"])

    def saved_login_domains(self) -> list[str]:
        rows = self.mongo[BrowserProfilesRepository.collection_name].find(
            {"user_id": self.battery_user_id()}
        )
        return [str(row.get("domain", "")) for row in rows]

    def forget_logins(self) -> None:
        self.mongo[BrowserProfilesRepository.collection_name].delete_many(
            {"user_id": self.battery_user_id()}
        )

    # -- the live browser during a handoff --------------------------------

    async def type_into_live_session(self, session_id: str, script: str) -> Any:
        """Run JS in the run's own page, the way a person acts in live view during a handoff."""
        from browser_use import Browser

        ws = HOST_URL.replace("http", "ws", 1) + f"/cdp/{session_id}"
        browser = Browser(cdp_url=ws)
        await browser.start()
        try:
            cdp = await browser.get_or_create_cdp_session(focus=False)
            result = await cdp.cdp_client.send.Runtime.evaluate(
                params={"expression": script, "awaitPromise": True, "returnByValue": True},
                session_id=cdp.session_id,
            )
            return result.get("result", {}).get("value")
        finally:
            await browser.stop()

    def wait_for_page(self, session_id: str, path: str, *, timeout: float = 30.0) -> str:
        """Return the run's page URL once it is on path, or the last URL seen at the timeout.

        Read from the host, not from the script that submitted: a navigation
        replaces the document the script ran in, so its own location is stale.
        """
        deadline = time.monotonic() + timeout
        url = ""
        while time.monotonic() < deadline:
            url = self.run_async(get_session(session_id, HOST_URL)).url or ""
            if urlsplit(url).path == path:
                break
            time.sleep(_POLL_SECONDS / 2)
        return url

    # -- one whole scenario -------------------------------------------------

    def run(self, message: str, *, on_running=None) -> RunOutcome:
        """Send a message, follow its run to the end, and return everything it produced.

        on_running(job_id, state, battery) is called once the run is RUNNING, for
        scenarios that act mid-run (a handoff to answer, a stop to send).
        """
        self.reset_browser_quota()
        self.forget_memories()
        #: What the user says into this run's conversation while it runs.
        self.replies = []
        started = time.monotonic()
        proc = self.send(message, settle_ms=int(SENDER_WINDOW_SECONDS * 1000))
        job_id = None
        try:
            job_id = self.wait_for_job(proc=proc)
            state = self.wait_for_status(job_id, {"running", "done"}, timeout=240.0)
            # The terminal state drops the session id; the history row is keyed on it.
            session_id = state.get("session_id")
            handoffs: list[dict[str, Any]] = []
            if on_running is not None and state.get("status") == "running":
                handoffs = on_running(job_id, state, self) or []
            state = self.wait_for_status(job_id, {"done"}, timeout=RUN_TIMEOUT_SECONDS)
            seconds = time.monotonic() - started
            print(f"run {job_id} done in {seconds:.0f}s")
            self.wait_for_outcome_voiced()
        except BaseException:
            if job_id is not None:
                self.stop_run(job_id)
            raise
        finally:
            self.finish_sender(proc)
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.stop_sender(proc)
        # The history row is written at the end of the run; give it a moment.
        record = None
        for _ in range(15):
            record = self.task_record(session_id)
            if record:
                break
            time.sleep(1)
        return RunOutcome(
            job_id, state, record, self.transcript_of(proc, self.replies), handoffs, seconds
        )


def fetch_text(url: str) -> str:
    """Ground truth from the site itself, fetched at test time."""
    return httpx.get(
        url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    ).text


def hn_front_page_titles() -> list[str]:
    page = fetch_text("https://news.ycombinator.com/")
    # Titles as a reader sees them: HN escapes the apostrophe in "Stripe's".
    return [
        html.unescape(re.sub(r"<[^>]+>", "", m))
        for m in re.findall(r'<span class="titleline"><a[^>]*>(.*?)</a>', page)
    ]
