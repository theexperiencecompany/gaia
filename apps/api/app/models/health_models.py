"""Response models for the health/ping routes."""

from typing import Literal

from pydantic import BaseModel, Field

from app.config.deployment import DeploymentKind


class HealthResponse(BaseModel):
    """``GET /health`` (and its ping/root aliases) when the API is serving normally."""

    status: Literal["online"] = "online"
    message: str
    name: str
    version: str
    description: str
    environment: DeploymentKind
    commit: str = Field(description="Short sha the image was built from; 'local' outside one")
    event_loop_lag_ms: float = Field(description="Time to round-trip one event-loop tick")


class DegradedHealthResponse(BaseModel):
    """The 503 body returned when the event loop is lagged past the threshold."""

    status: Literal["degraded"] = "degraded"
    event_loop_lag_ms: float
    detail: str


class DependencyStatus(BaseModel):
    """One backing service's answer to a real round-trip, as /health/ready reports it."""

    name: str
    ok: bool
    latency_ms: float
    error_type: str | None = Field(
        default=None, description="Exception class name when the check failed; never its message"
    )


class ReadinessResponse(BaseModel):
    """``GET /health/ready``: whether every backing service answered a real request."""

    status: Literal["ready", "not_ready"]
    dependencies: list[DependencyStatus]
