"""Top-up packs — the storefront, Dodo checkout, and grant-on-purchase.

Packs are one-time Dodo products (created by ``scripts/credits_setup.py``). A
purchase fires the Dodo ``payment.succeeded`` webhook, which grants the pack's
credits to the user's wallet (see ``credit_wallet_service``).
"""

from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from app.config.settings import settings
from app.db.mongodb.collections import credit_packs_collection, users_collection
from app.services.credits import credit_wallet_service
from app.services.payments.payment_service import payment_service


async def list_packs() -> list[dict[str, Any]]:
    """Active top-up packs for the storefront."""
    return [
        {
            "key": p["key"],
            "credits": p["credits"],
            "price_cents": p["price_cents"],
            "name": p["name"],
        }
        async for p in credit_packs_collection.find({"is_active": True}).sort("price_cents", 1)
    ]


async def create_topup_checkout(user_id: str, pack_key: str) -> dict[str, Any]:
    """Create a Dodo checkout session to buy a top-up pack."""
    pack = await credit_packs_collection.find_one({"key": pack_key, "is_active": True})
    if not pack:
        raise HTTPException(status_code=404, detail="Credit pack not found")
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    checkout_session = payment_service.client.checkout_sessions.create(
        product_cart=[{"product_id": pack["dodo_product_id"], "quantity": 1}],
        customer={
            "email": user["email"],
            "name": user.get("first_name") or user.get("name") or "GAIA User",
        },
        return_url=f"{settings.FRONTEND_URL}/payment/success",
        metadata={
            "user_id": user_id,
            "credit_pack_key": pack_key,
            "credits": str(pack["credits"]),
        },
    )
    return {
        "session_id": checkout_session.session_id,
        "payment_link": checkout_session.checkout_url,
    }


async def grant_pack_from_payment(
    metadata: dict, dodo_payment_id: str, dodo_customer_id: str
) -> bool:
    """Grant a purchased pack's credits to the user's Dodo wallet (idempotent).

    Returns True if a pack grant was applied (i.e. this was a top-up payment).
    """
    user_id = metadata.get("user_id")
    pack_key = metadata.get("credit_pack_key")
    if not user_id or not pack_key or not dodo_customer_id:
        return False
    pack = await credit_packs_collection.find_one({"key": pack_key})
    if not pack:
        return False
    return await credit_wallet_service.grant(
        user_id,
        dodo_customer_id,
        int(pack["credits"]),
        reason=f"topup:{pack_key}:{dodo_payment_id}",
        dodo_payment_id=dodo_payment_id,
    )
