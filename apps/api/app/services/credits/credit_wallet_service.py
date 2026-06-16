"""Top-up credit wallet (Pool 2) — an immutable grant ledger in MongoDB.

Each purchased top-up is a grant with a ``remaining`` balance and an expiry.
Balance is the sum of non-expired remainders; debits consume oldest grants
first (FIFO). Dodo handles the payment for a top-up; this ledger holds the
resulting credits.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.constants.credits import CREDIT_TOPUP_EXPIRY_DAYS
from app.db.mongodb.collections import credit_grants_collection


async def get_balance(user_id: str) -> int:
    """Sum of non-expired top-up credits the user holds."""
    now = datetime.now(UTC)
    pipeline = [
        {"$match": {"user_id": user_id, "remaining": {"$gt": 0}, "expires_at": {"$gt": now}}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining"}}},
    ]
    async for doc in credit_grants_collection.aggregate(pipeline):
        return int(doc.get("total", 0))
    return 0


async def debit(user_id: str, amount: int, *, reason: str) -> int:
    """Consume up to ``amount`` credits from oldest non-expired grants (FIFO).

    Returns the amount actually debited (may be less if the wallet is short).
    """
    if amount <= 0:
        return 0
    now = datetime.now(UTC)
    outstanding = amount
    debited = 0
    cursor = credit_grants_collection.find(
        {"user_id": user_id, "remaining": {"$gt": 0}, "expires_at": {"$gt": now}}
    ).sort("created_at", 1)
    async for grant_doc in cursor:
        if outstanding <= 0:
            break
        take = min(int(grant_doc["remaining"]), outstanding)
        await credit_grants_collection.update_one(
            {"_id": grant_doc["_id"]}, {"$inc": {"remaining": -take}}
        )
        outstanding -= take
        debited += take
    return debited


async def credit_back(user_id: str, amount: int, *, reason: str) -> None:
    """Return previously-debited credits to the wallet (error refunds)."""
    if amount <= 0:
        return
    now = datetime.now(UTC)
    await credit_grants_collection.insert_one(
        {
            "user_id": user_id,
            "amount": amount,
            "remaining": amount,
            "kind": "refund",
            "reason": reason,
            "created_at": now,
            "expires_at": now + timedelta(days=CREDIT_TOPUP_EXPIRY_DAYS),
        }
    )


async def grant(
    user_id: str,
    amount: int,
    *,
    reason: str,
    dodo_payment_id: str | None = None,
    expiry_days: int = CREDIT_TOPUP_EXPIRY_DAYS,
) -> bool:
    """Add purchased credits to the wallet. Idempotent on ``dodo_payment_id``."""
    if amount <= 0:
        return False
    if dodo_payment_id and await credit_grants_collection.find_one(
        {"dodo_payment_id": dodo_payment_id}
    ):
        return False
    now = datetime.now(UTC)
    await credit_grants_collection.insert_one(
        {
            "user_id": user_id,
            "amount": amount,
            "remaining": amount,
            "kind": "topup",
            "reason": reason,
            "dodo_payment_id": dodo_payment_id,
            "created_at": now,
            "expires_at": now + timedelta(days=expiry_days),
        }
    )
    return True


async def get_active_grants(user_id: str) -> list[dict[str, Any]]:
    """Non-expired grants with credits remaining, soonest-to-expire first."""
    now = datetime.now(UTC)
    cursor = credit_grants_collection.find(
        {"user_id": user_id, "remaining": {"$gt": 0}, "expires_at": {"$gt": now}}
    ).sort("expires_at", 1)
    return [
        {
            "amount": int(g["amount"]),
            "remaining": int(g["remaining"]),
            "kind": g.get("kind", "topup"),
            "created_at": g["created_at"],
            "expires_at": g["expires_at"],
        }
        async for g in cursor
    ]
