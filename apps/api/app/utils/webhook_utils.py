import base64
import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from app.config.settings import settings

# Reject webhook events whose signed timestamp is older than this many seconds.
# Without a freshness check, a captured valid request replays indefinitely.
_WEBHOOK_FRESHNESS_WINDOW_SECONDS = 300


async def verify_composio_webhook_signature(request: Request):
    """
    Verify the authenticity of a Composio webhook request.

    Args:
        request: The FastAPI request object

    Returns:
        tuple: (body bytes, webhook_id)

    Raises:
        HTTPException: If signature verification fails
    """
    # Get the raw body for signature verification
    body = await request.body()

    # Get the signature and timestamp from headers
    signature_header = request.headers.get("webhook-signature", "")
    timestamp = request.headers.get("webhook-timestamp", "")
    webhook_id = request.headers.get("webhook-id", "")

    # Fail closed: always require a signature header
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    # Freshness check: only meaningful if we actually verify the signed
    # timestamp is recent, otherwise any captured request replays forever.
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=401, detail="Missing or invalid webhook-timestamp header"
        ) from None
    if abs(time.time() - ts) > _WEBHOOK_FRESHNESS_WINDOW_SECONDS:
        raise HTTPException(status_code=401, detail="Webhook timestamp out of window")

    # Require webhook-id so dedup at the endpoint layer is always meaningful.
    if not webhook_id:
        raise HTTPException(status_code=400, detail="Missing webhook-id header")

    # Standard Webhooks supports multiple space-separated signatures so
    # senders can rotate keys without downtime. We split on whitespace,
    # then strip the algorithm prefix from each entry (e.g. ``v1,sig``).
    candidate_sigs: list[str] = []
    for entry in signature_header.split():
        if "," not in entry:
            continue
        _, sig = entry.split(",", 1)
        if sig:
            candidate_sigs.append(sig)
    if not candidate_sigs:
        raise HTTPException(status_code=401, detail="Invalid signature format")

    # Create the signed content (webhook_id.timestamp.body) as bytes
    # Avoid decoding 143KB body to string and re-encoding
    signed_content = webhook_id.encode() + b"." + timestamp.encode() + b"." + body

    # Generate expected signature
    expected_signature = hmac.new(
        settings.COMPOSIO_WEBHOOK_SECRET.encode(),
        signed_content,
        hashlib.sha256,
    ).digest()
    expected_signature_b64 = base64.b64encode(expected_signature).decode()

    # Constant-time compare for every candidate; accept on any match. We
    # walk the full list rather than short-circuiting so timing leaks are
    # bounded by the (small, fixed) candidate count.
    matched = False
    for candidate in candidate_sigs:
        if hmac.compare_digest(candidate, expected_signature_b64):
            matched = True
    if not matched:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    return body, webhook_id
