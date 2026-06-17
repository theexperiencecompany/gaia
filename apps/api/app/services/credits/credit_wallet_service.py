"""Top-up wallet (Pool 2) — a thin wrapper over Dodo Credit-Based Billing.

Dodo's **credit entitlement** (a custom "credits" unit) is the system of record
for purchased top-up credits: it owns the immutable ledger, per-customer balance,
and expiry. We never hand-build a ledger — we credit/debit the customer's balance
via Dodo's per-customer ledger-entries endpoint and read the balance on-demand.

Pool 2 is the rare path: plan allotment (Pool 1, Redis) covers almost all usage,
so these Dodo calls only happen once a paying user exhausts their allotment.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from bson import ObjectId
import httpx

from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.db.redis import redis_cache
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log

# Idempotency window for top-up grants (webhooks can be redelivered).
_GRANT_GUARD_TTL_SECONDS = 7 * 24 * 60 * 60
# Debit lock: long enough to cover the read-balance + ledger-entry round-trips.
_DEBIT_LOCK_TIMEOUT = 15
_DEBIT_LOCK_WAIT = 10


@asynccontextmanager
async def _debit_lock(user_id: str) -> AsyncIterator[None]:
    """Serialize a user's debits so balance is read fresh before each charge.

    Dodo's ledger has no idempotency/locking, so two concurrent overflow
    charges could both read the same balance and over-debit. Best-effort: if
    Redis is down or the lock can't be acquired, proceed rather than block a
    charge (a rare double-debit beats failing to bill).
    """
    client = redis_cache.redis
    if client is None:
        yield
        return
    lock = client.lock(
        f"credit_debit_lock:{user_id}",
        timeout=_DEBIT_LOCK_TIMEOUT,
        blocking_timeout=_DEBIT_LOCK_WAIT,
    )
    acquired = False
    try:
        acquired = await lock.acquire()
        if not acquired:
            log.warning("credit_debit_lock_timeout", user_id=user_id)
        yield
    finally:
        if acquired:
            try:
                await lock.release()
            except Exception:  # noqa: BLE001 - lock may have already expired
                log.debug("credit_debit_lock_release_failed", user_id=user_id)


def _entitlement_id() -> str:
    return settings.DODO_CREDIT_ENTITLEMENT_ID or ""


async def _dodo_request(
    method: str, path: str, *, json: dict[str, Any] | None = None
) -> httpx.Response | None:
    """Call the Dodo API. Returns the response, or None if credits aren't configured."""
    if not (settings.DODO_PAYMENTS_API_KEY and _entitlement_id()):
        return None
    base = str(payment_service.client.base_url).rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.DODO_PAYMENTS_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=20) as client:
        return await client.request(method, path, json=json)


async def _customer_id(user_id: str) -> str | None:
    """The user's linked Dodo customer id (set when they first purchase credits)."""
    user = await users_collection.find_one({"_id": ObjectId(user_id)}, {"dodo_customer_id": 1})
    return user.get("dodo_customer_id") if user else None


async def _ledger_entry(customer_id: str, amount: int, entry_type: str, reason: str) -> bool:
    """Create a credit/debit ledger entry on the customer's balance."""
    resp = await _dodo_request(
        "POST",
        f"/credit-entitlements/{_entitlement_id()}/balances/{customer_id}/ledger-entries",
        json={"amount": amount, "entry_type": entry_type, "description": reason},
    )
    return bool(resp and resp.status_code in (200, 201))


async def get_balance(user_id: str) -> int:
    """The user's remaining top-up credits (0 if they hold no Dodo wallet)."""
    customer_id = await _customer_id(user_id)
    if not customer_id:
        return 0
    resp = await _dodo_request(
        "GET", f"/credit-entitlements/{_entitlement_id()}/balances/{customer_id}"
    )
    if not resp or resp.status_code != 200:
        return 0
    return int(float(resp.json().get("balance", 0)))


async def debit(user_id: str, amount: int, *, reason: str) -> int:
    """Consume up to ``amount`` top-up credits. Returns the amount actually debited."""
    if amount <= 0:
        return 0
    customer_id = await _customer_id(user_id)
    if not customer_id:
        return 0
    async with _debit_lock(user_id):
        take = min(amount, await get_balance(user_id))
        if take <= 0:
            return 0
        return take if await _ledger_entry(customer_id, take, "debit", reason) else 0


async def credit_back(user_id: str, amount: int, *, reason: str) -> None:
    """Return previously-debited credits to the wallet (error refunds)."""
    if amount <= 0:
        return
    customer_id = await _customer_id(user_id)
    if customer_id:
        await _ledger_entry(customer_id, amount, "credit", reason)


async def grant(
    user_id: str,
    customer_id: str,
    amount: int,
    *,
    reason: str,
    dodo_payment_id: str,
) -> bool:
    """Add purchased top-up credits to the user's Dodo wallet (idempotent on payment id).

    Links the Dodo customer to the user on first purchase so later reads/debits
    resolve the right wallet.
    """
    if amount <= 0 or not customer_id:
        return False
    guard_key = f"topup_processed:{dodo_payment_id}"
    if redis_cache.redis and not await redis_cache.redis.set(
        guard_key, "1", nx=True, ex=_GRANT_GUARD_TTL_SECONDS
    ):
        return False  # already processed this payment

    await users_collection.update_one(
        {"_id": ObjectId(user_id)}, {"$set": {"dodo_customer_id": customer_id}}
    )
    granted = await _ledger_entry(customer_id, amount, "credit", reason)
    if not granted and redis_cache.redis:
        await redis_cache.redis.delete(guard_key)  # let a retry re-attempt
    if granted:
        log.info(
            "credit_topup_granted",
            credit_event="credit_topup_granted",
            user_id=user_id,
            credits=amount,
            dodo_payment_id=dodo_payment_id,
        )
    return granted
