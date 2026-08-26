"""Response models for the health/ping routes."""

from typing import Literal

from pydantic import BaseModel, Field

Environment = Literal["production", "development", "selfhost"]


class HealthResponse(BaseModel):
    """``GET /health`` (and its ping/root aliases) when the API is serving normally."""

    status: Literal["online"] = "online"
    message: str
    name: str
    version: str
    description: str
    environment: Environment
    event_loop_lag_ms: float = Field(description="Time to round-trip one event-loop tick")


class DegradedHealthResponse(BaseModel):
    """The 503 body returned when the event loop is lagged past the threshold."""

    status: Literal["degraded"] = "degraded"
    event_loop_lag_ms: float
    detail: str
