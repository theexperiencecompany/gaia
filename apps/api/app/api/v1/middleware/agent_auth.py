from datetime import UTC, datetime, timedelta
from typing import cast

from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config.settings import settings
from app.constants.auth import AGENT_TOKEN_EXPIRY_MINUTES, JWT_ALGORITHM

AGENT_SECRET = settings.AGENT_SECRET


class AgentTokenClaims(BaseModel):
    """The claims ``create_agent_token`` writes — parsed once from the decoded JWT."""

    model_config = ConfigDict(extra="ignore")

    sub: str
    role: str


class AgentTokenInfo(BaseModel):
    """A verified agent token: whose session it impersonates."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    impersonated: bool = True


def verify_agent_token(token: str) -> AgentTokenInfo | None:
    try:
        claims = AgentTokenClaims.model_validate(
            jwt.decode(token, AGENT_SECRET, algorithms=[JWT_ALGORITHM])
        )
    except (JWTError, ValidationError):
        return None
    if claims.role != "agent":
        return None
    return AgentTokenInfo(user_id=claims.sub)


def create_agent_token(user_id: str, expires_minutes: int = AGENT_TOKEN_EXPIRY_MINUTES) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": user_id,
        "role": "agent",
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return cast(str, jwt.encode(payload, AGENT_SECRET, algorithm=JWT_ALGORITHM))
