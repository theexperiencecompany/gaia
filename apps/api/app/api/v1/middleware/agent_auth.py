from datetime import datetime, timedelta

from jose import JWTError, jwt

from app.config.settings import settings
from app.constants.auth import AGENT_TOKEN_EXPIRY_MINUTES, JWT_ALGORITHM

AGENT_SECRET = settings.AGENT_SECRET


def verify_agent_token(token: str):
    try:
        payload = jwt.decode(token, AGENT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("role") != "agent":
            return None
        return {
            "user_id": payload.get("sub"),
            "impersonated": True,
        }
    except JWTError:
        return None


def create_agent_token(user_id: str, expires_minutes: int = AGENT_TOKEN_EXPIRY_MINUTES):
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    payload = {
        "sub": user_id,
        "role": "agent",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, AGENT_SECRET, algorithm=JWT_ALGORITHM)
