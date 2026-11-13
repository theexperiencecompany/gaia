"""Telling the API the user is in a live call, so what GAIA tells them waits for, or is said in, the call."""

import asyncio

import aiohttp

from shared.py.voice_call import CALL_HEARTBEAT_SECONDS
from shared.py.wide_events import log
from src.constants import CALL_PRESENCE_REQUEST_TIMEOUT_S, CALL_TOKEN_WAIT_S, LogTag
from src.llm import CustomLLM

_HOLD_PATH = "/api/v1/voice/session"
_END_PATH = "/api/v1/voice/session/end"


async def _report(llm: CustomLLM, method: str, path: str, room_name: str) -> bool:
    """Send the call's state to the API; False when it could not be sent, with the reason logged."""
    if llm.agent_token is None:
        return False
    try:
        async with (
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=CALL_PRESENCE_REQUEST_TIMEOUT_S)
            ) as http,
            http.request(
                method,
                f"{llm.base_url}{path}",
                json={"room_name": room_name},
                headers={"Authorization": f"Bearer {llm.agent_token}"},
            ) as resp,
        ):
            resp.raise_for_status()
    except (aiohttp.ClientError, TimeoutError) as e:
        log.warning(
            f"{LogTag.AGENT} Call presence not reported",
            phase="call_presence_failed",
            method=method,
            room=room_name,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False
    return True


async def hold_call_presence(llm: CustomLLM, room_name: str) -> None:
    """Keep the API told the call is live until cancelled; a beat that fails is retried at the next one."""
    while True:
        reported = await _report(llm, "PUT", _HOLD_PATH, room_name)
        await asyncio.sleep(CALL_HEARTBEAT_SECONDS if reported else CALL_TOKEN_WAIT_S)


async def end_call_presence(llm: CustomLLM, room_name: str) -> None:
    """Tell the API the call is over; a call the API never hears ended stops being live when its heartbeat lapses."""
    await _report(llm, "POST", _END_PATH, room_name)
