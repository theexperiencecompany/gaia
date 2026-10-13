"""The browser host's REST bodies, declared once for the host that sends them and the API that reads them."""

from __future__ import annotations

from playwright.sync_api import StorageState
from pydantic import BaseModel, ConfigDict

from app.constants.browser import BrowserEngine


class CreateSessionRequest(BaseModel):
    """Create-session payload: optional storage state to seed the new context."""

    storage_state: StorageState | None = None


class CreatedSession(BaseModel):
    """A session the host created: its CDP and live-view websocket URLs and the engine it runs on."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    cdp_ws: str
    live_ws: str
    engine: BrowserEngine


class StorageStateResponse(BaseModel):
    """A context's cookies and localStorage, read live or as it was disposed."""

    storage_state: StorageState


class SessionInfo(BaseModel):
    """Live status for a session: whether it serves, and its focused page's url and title."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    live: bool
    url: str | None = None
    title: str | None = None


class HealthResponse(BaseModel):
    """Host health probe: engine liveness plus a real CDP round-trip result."""

    ok: bool
    sessions: int
    engine_up: bool
    cdp_responsive: bool
