"""Voice mode endpoints — LiveKit session tokens and voice selection."""

import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from livekit import api

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
)
from app.api.v1.middleware.agent_auth import create_agent_token
from app.api.v1.middleware.tiered_rate_limiter import tiered_rate_limit
from app.config.settings import settings
from app.schemas.voice_schemas import (
    UpdateVoiceRequest,
    VoiceListResponse,
    VoiceSelectionResponse,
)
from app.services.voice_service import get_user_voice, list_voices, set_user_voice
from shared.py.wide_events import log

router = APIRouter()


@router.get("/token")
@tiered_rate_limit("voice_mode")
async def get_token(
    user: dict = Depends(get_current_user),
    conversationId: str | None = None,
):
    """Mint a LiveKit room token (and agent credentials) for a voice session."""
    user_id = user.get("user_id")
    user_email: str = user.get("email", "")
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Invalid or missing user_id")
    log.set(
        user={"id": user_id},
        operation="get_voice_token",
        has_conversation_id=bool(conversationId),
    )

    room_name = f"voice_session_{user_id}_{uuid.uuid4().hex}"

    identity = f"user_{user_id}"
    display_name = user_email
    agent_jwt = create_agent_token(user_id)
    metadata = {
        "identity": identity,
        "name": display_name,
        "agentToken": agent_jwt,
        "roomName": room_name,
    }
    if conversationId:
        metadata["conversationId"] = conversationId
    # The agent reads the user's chosen voice from participant metadata —
    # no extra backend round trip from the worker.
    selected_voice = await get_user_voice(user_id)
    if selected_voice:
        metadata["voiceId"] = selected_voice
    try:
        at = (
            api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_name(display_name)
            .with_metadata(json.dumps(metadata))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                    can_update_own_metadata=True,
                )
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate voice token: {e!s}")

    log.set(outcome="success")
    return {
        "serverUrl": settings.LIVEKIT_URL,
        "roomName": room_name,
        "participantToken": at.to_jwt(),
        "participantIdentity": identity,
        "participantName": display_name,
        "conversation_id": conversationId,
    }


@router.get("/voice/voices", response_model=VoiceListResponse)
async def get_voices(user: dict = Depends(get_current_user)) -> VoiceListResponse:
    """List the curated voice catalog with the user's current selection."""
    log.set(user={"id": user["user_id"]}, operation="list_voices")
    result = await list_voices(user["user_id"])
    log.set(voice_count=len(result.voices), selected_voice_id=result.selected_voice_id)
    return result


@router.put("/voice/voices/selected", response_model=VoiceSelectionResponse)
async def select_voice(
    payload: UpdateVoiceRequest,
    user: dict = Depends(get_current_user),
) -> VoiceSelectionResponse:
    """Set the user's voice for future voice-mode sessions."""
    log.set(user={"id": user["user_id"]}, operation="select_voice", voice_id=payload.voice_id)
    selected = await set_user_voice(user["user_id"], payload.voice_id)
    return VoiceSelectionResponse(selected_voice_id=selected)
