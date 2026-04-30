import json
import secrets as _secrets
import uuid
from typing import Optional

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
)
from app.api.v1.middleware.agent_auth import create_agent_token
from app.config.settings import settings
from fastapi import APIRouter, Depends, Header
from fastapi.exceptions import HTTPException
from livekit import api
from pydantic import BaseModel, Field
from shared.py.wide_events import log

router = APIRouter()


class _VoiceAgentTokenRequest(BaseModel):
    user_id: str = Field(..., description="User ID extracted from participant identity")
    room_name: str = Field(..., description="LiveKit room name for this session")


@router.get("/token")
def get_token(
    user: dict = Depends(get_current_user),
    conversationId: Optional[str] = None,
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
    # agentToken is intentionally omitted from metadata — it was visible to
    # all room participants (C7).  The voice agent worker fetches its JWT
    # separately via POST /voice/agent-token using the shared AGENT_SECRET.
    metadata: dict = {
        "identity": identity,
        "name": display_name,
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
        raise HTTPException(
            status_code=500, detail=f"Failed to generate voice token: {str(e)}"
        )

    log.set(outcome="success")
    return {
        "serverUrl": settings.LIVEKIT_URL,
        "roomName": room_name,
        "participantToken": at.to_jwt(),
        "participantIdentity": identity,
        "participantName": display_name,
        "conversation_id": conversationId,
    }


@router.post("/agent-token")
def get_voice_agent_token(
    body: _VoiceAgentTokenRequest,
    x_agent_secret: str = Header(..., alias="X-Agent-Secret"),
) -> dict:
    """Issue a short-lived agent JWT for the voice agent worker (C7).

    The worker calls this endpoint after joining the room, authenticating with
    the shared AGENT_SECRET.  The JWT is never placed in LiveKit room metadata
    where other participants could read it.
    """
    if not settings.AGENT_SECRET or not _secrets.compare_digest(
        x_agent_secret, settings.AGENT_SECRET
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    token = create_agent_token(body.user_id, room_id=body.room_name)
    return {"token": token}
