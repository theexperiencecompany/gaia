"""Cross-replica distributed locking, backed by redis-py's token-checked ``Lock``.

``DistributedLock`` is the one canonical lock for the backend, so no subsystem
re-derives the lease/watchdog/safe-release dance. Construct it with a key and its
timing, then either take it directly with ``hold`` (deciding what a failed
acquire means) or run idempotent work under it with ``run_idempotent`` (which
serializes the herd but always runs the work).

Nothing here can freeze the system on a corrupted run:

- The Redis key carries a TTL (``lease_seconds``), so a holder whose process dies
  without releasing frees the key within one lease.
- While the holder's process is alive a watchdog extends the lease every
  ``renew_seconds``, so a lease shorter than the real critical section is safe.
- Renewal is capped at ``max_hold_seconds`` from acquisition. Past the cap the
  watchdog stops renewing and lets the lease expire, so a hung critical section
  (live process, stuck coroutine) is forcibly evicted instead of holding the
  lock forever. Set ``max_hold_seconds`` comfortably above the longest legitimate
  critical section — beyond it, a second holder may enter.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import contextlib

from redis.asyncio.lock import Lock
from redis.exceptions import RedisError

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import log


class DistributedLock:
    """A cross-replica mutex on a Redis key. See the module docstring for the
    expiry / max-hold guarantees."""

    def __init__(
        self,
        key: str,
        *,
        lease_seconds: float,
        acquire_timeout_seconds: float,
        renew_seconds: float,
        max_hold_seconds: float,
    ) -> None:
        if max_hold_seconds < lease_seconds:
            raise ValueError(
                "max_hold_seconds must be >= lease_seconds; a cap below one lease "
                "would evict every holder before its first renewal"
            )
        self._key = key
        self._lease_seconds = lease_seconds
        self._acquire_timeout_seconds = acquire_timeout_seconds
        self._renew_seconds = renew_seconds
        self._max_hold_seconds = max_hold_seconds

    @contextlib.asynccontextmanager
    async def hold(self) -> AsyncIterator[bool]:
        """Hold the lease for the duration of the block.

        Yields ``True`` if the lease was acquired (a watchdog extends it until the
        block exits or the max-hold cap is hit) and ``False`` if it could not be
        taken for any operational reason (acquire timed out, Redis unreachable, or
        Redis not configured), each logged with the reason. Never raises to signal
        a failed acquire; the caller decides what ``False`` means.
        """
        client = redis_cache.redis
        if client is None:
            log.warning(f"{LogTag.LOCK} Redis not configured; lease not taken", lock_key=self._key)
            yield False
            return

        # thread_local=False: the token is read from the watchdog task, and asyncio
        # tasks share a thread, so thread-local storage is the wrong scope.
        lock = client.lock(
            self._key,
            timeout=self._lease_seconds,
            blocking_timeout=self._acquire_timeout_seconds,
            thread_local=False,
        )
        try:
            acquired = await lock.acquire()
        except RedisError as e:
            log.warning(
                f"{LogTag.LOCK} Redis error acquiring lease; lease not taken",
                lock_key=self._key,
                error=str(e),
                error_type=type(e).__name__,
            )
            yield False
            return
        if not acquired:
            log.warning(
                f"{LogTag.LOCK} Timed out acquiring lease",
                lock_key=self._key,
                acquire_timeout_seconds=self._acquire_timeout_seconds,
            )
            yield False
            return

        watchdog = asyncio.get_running_loop().create_task(self._renew_until_cap(lock))
        try:
            yield True
        finally:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
            # Expired mid-flight (watchdog lost the race, or the max-hold cap let
            # the lease lapse) means another replica may already hold it; releasing
            # then would free someone else's lease. redis-py's token check turns
            # that into a LockError, a real event worth seeing — not a failure of
            # the work we just did.
            try:
                await lock.release()
            except RedisError as e:
                log.error(
                    f"{LogTag.LOCK} Lease lost before release",
                    lock_key=self._key,
                    error=str(e),
                    error_type=type(e).__name__,
                )

    async def _renew_until_cap(self, lock: Lock) -> None:
        """Extend the lease while the holder is alive, until cancelled or capped."""
        deadline = asyncio.get_running_loop().time() + self._max_hold_seconds
        while True:
            await asyncio.sleep(self._renew_seconds)
            if asyncio.get_running_loop().time() >= deadline:
                # A live-but-wedged holder would otherwise renew forever. Stop, and
                # let the lease expire so another replica can take over.
                log.error(
                    f"{LogTag.LOCK} Max hold exceeded; stopping renewal so the lease expires",
                    lock_key=self._key,
                    max_hold_seconds=self._max_hold_seconds,
                )
                return
            try:
                await lock.extend(self._lease_seconds, replace_ttl=True)
            except RedisError as e:
                # The lease is gone and cannot be reclaimed — another replica may be
                # inside the critical section. Stop renewing and make it visible.
                log.error(
                    f"{LogTag.LOCK} Lost lease while holding it",
                    lock_key=self._key,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return

    async def run_idempotent(self, work: Callable[[], Awaitable[None]]) -> None:
        """Run idempotent ``work`` serialized across replicas, but always run it.

        When many processes start at once only one runs ``work`` at a time; the
        others block, acquire in turn, and re-run it as the cheap no-op idempotence
        guarantees. ``work`` runs whether or not the lease was taken — a lease that
        cannot be acquired (contended past the window, or Redis down) degrades to
        an unsynchronized run, never a skip. Use ``hold`` directly when exclusivity
        is a correctness requirement and skipping/raising is correct.
        """
        async with self.hold() as held:
            if not held:
                log.warning(
                    f"{LogTag.LOCK} Lease not held; running work unsynchronized (idempotent)",
                    lock_key=self._key,
                )
            await work()
