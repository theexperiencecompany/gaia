import base64
import hashlib
import hmac

from fastapi import HTTPException, Request

from app.config.settings import settings


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

    # Extract the signature (format: "v1,signature")
    if "," in signature_header:
        _, signature = signature_header.split(",", 1)
    else:
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

    # Encode to base64
    expected_signature_b64 = base64.b64encode(expected_signature).decode()

    # Compare signatures
    if not hmac.compare_digest(signature, expected_signature_b64):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    return body, webhook_id
