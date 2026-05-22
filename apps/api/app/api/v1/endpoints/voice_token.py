import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from livekit import api

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
)
from app.api.v1.middleware.agent_auth import create_agent_token
from app.config.settings import settings
from shared.py.wide_events import log

router = APIRouter()


@router.get("/token")
def get_token(
    user: dict = Depends(get_current_user),
    conversationId: str | None = None,
):
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
