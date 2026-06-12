"""Voice mode endpoints — LiveKit session tokens and voice selection."""

import json
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import HTTPException
from livekit import api

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
)
from app.api.v1.middleware.agent_auth import create_agent_token
from app.api.v1.middleware.tiered_rate_limiter import tiered_rate_limit
from app.config.settings import settings
from app.schemas.voice_schemas import (
    StarredVoicesResponse,
    StarVoiceRequest,
    UpdateVoiceRequest,
    VoiceListResponse,
    VoiceSelectionResponse,
    VoiceTokenResponse,
)
from app.services.voice_service import (
    get_user_voice,
    list_voices,
    set_user_voice,
    set_voice_star,
)
from shared.py.wide_events import log

router = APIRouter()

CurrentUser = Annotated[dict, Depends(get_current_user)]


@router.get(
    "/token",
    responses={
        401: {"description": "Invalid or missing user id"},
        500: {"description": "Token generation failed"},
    },
)
@tiered_rate_limit("voice_mode")
async def get_token(
    user: CurrentUser,
    conversation_id: Annotated[str | None, Query(alias="conversationId")] = None,
) -> VoiceTokenResponse:
    """Mint a LiveKit room token (and agent credentials) for a voice session."""
    user_id = user.get("user_id")
    user_email: str = user.get("email", "")
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Invalid or missing user_id")
    log.set(
        user={"id": user_id},
        operation="get_voice_token",
        has_conversation_id=bool(conversation_id),
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
    if conversation_id:
        metadata["conversationId"] = conversation_id
    # The agent reads the user's chosen voice from participant metadata —
    # no extra backend round trip from the worker.
    selected_voice = await get_user_voice(user_id)
    if selected_voice:
        metadata["voiceId"] = selected_voice
    # Multi-backend deployments (staging previews) run one shared agent —
    # tell it which API minted this session.
    if settings.VOICE_AGENT_BACKEND_URL:
        metadata["backendUrl"] = settings.VOICE_AGENT_BACKEND_URL
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
    return VoiceTokenResponse(
        serverUrl=settings.LIVEKIT_URL,
        roomName=room_name,
        participantToken=at.to_jwt(),
        participantIdentity=identity,
        participantName=display_name,
        conversation_id=conversation_id,
    )


@router.get("/voice/voices")
async def get_voices(user: CurrentUser) -> VoiceListResponse:
    """List the curated voice catalog with the user's current selection."""
    log.set(user={"id": user["user_id"]}, operation="list_voices")
    result = await list_voices(user["user_id"])
    log.set(voice_count=len(result.voices), selected_voice_id=result.selected_voice_id)
    return result


@router.put("/voice/voices/selected")
async def select_voice(
    payload: UpdateVoiceRequest,
    user: CurrentUser,
) -> VoiceSelectionResponse:
    """Set the user's voice for future voice-mode sessions."""
    log.set(user={"id": user["user_id"]}, operation="select_voice", voice_id=payload.voice_id)
    selected = await set_user_voice(user["user_id"], payload.voice_id)
    # May differ from the requested id when a library voice was added to the account.
    log.set(selected_voice_id=selected)
    return VoiceSelectionResponse(selected_voice_id=selected)


@router.put("/voice/voices/{voice_id}/star")
async def star_voice(
    voice_id: str,
    payload: StarVoiceRequest,
    user: CurrentUser,
) -> StarredVoicesResponse:
    """Star or unstar a voice; starred voices sort to the top of the picker."""
    log.set(
        user={"id": user["user_id"]},
        operation="star_voice",
        voice_id=voice_id,
        starred=payload.starred,
    )
    starred_ids = await set_voice_star(user["user_id"], voice_id, payload.starred)
    return StarredVoicesResponse(starred_voice_ids=starred_ids)
