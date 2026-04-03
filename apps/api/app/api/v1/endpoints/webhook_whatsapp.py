"""WhatsApp webhook proxy.

Receives Kapso webhook events on the public API, verifies the HMAC-SHA256
signature, then forwards the raw payload to the internal WhatsApp bot
container over the Docker network. This keeps port 3001 off the public
internet while still allowing Kapso to deliver events via a single TLS
endpoint (api.heygaia.io).

Kapso webhook URL to configure: https://api.heygaia.io/api/v1/webhook/whatsapp
"""

import aiohttp
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from shared.py.wide_events import log
from app.config.settings import settings
from app.utils.webhook_utils import verify_kapso_webhook_signature

router = APIRouter()

# Headers Kapso sets that the internal bot needs to process the event.
_FORWARDED_HEADERS = (
    "content-type",
    "x-webhook-event",
    "x-webhook-batch",
    "x-webhook-signature",
)

# Timeout for the internal proxy call to the WhatsApp bot (seconds).
_BOT_TIMEOUT = aiohttp.ClientTimeout(total=30)


@router.post("/webhook/whatsapp")
async def webhook_whatsapp(request: Request) -> JSONResponse:
    """Verify and proxy Kapso webhook events to the internal WhatsApp bot.

    Performs signature verification before forwarding so the bot container
    never receives unauthenticated payloads, even from within the network.
    """
    body = await verify_kapso_webhook_signature(request)

    event_type = request.headers.get("x-webhook-event", "unknown")
    log.set(webhook={"platform": "whatsapp", "event_type": event_type})

    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in _FORWARDED_HEADERS
    }

    bot_url = f"{settings.WHATSAPP_BOT_URL}/webhook"

    try:
        async with aiohttp.ClientSession(timeout=_BOT_TIMEOUT) as session:
            async with session.post(
                bot_url,
                data=body,
                headers=forward_headers,
            ) as resp:
                if resp.status >= 500:
                    response_text = await resp.text()
                    log.error(
                        "WhatsApp bot returned error",
                        status=resp.status,
                        body=response_text,
                    )
                    return JSONResponse(
                        content={"status": "error", "message": "Bot unavailable"},
                        status_code=502,
                    )
    except aiohttp.ClientConnectorError:
        log.error("WhatsApp bot unreachable", bot_url=bot_url)
        return JSONResponse(
            content={"status": "error", "message": "Bot unreachable"},
            status_code=502,
        )
    except TimeoutError:
        log.error("WhatsApp bot timed out", bot_url=bot_url)
        return JSONResponse(
            content={"status": "error", "message": "Bot timed out"},
            status_code=504,
        )

    log.set(operation="webhook_proxied", outcome="success")
    return JSONResponse(content={"status": "success"})
