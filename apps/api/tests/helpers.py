"""Shared test utilities for GAIA API tests."""

import os
import re
import socket
from typing import Any

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, BaseMessage
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def pick_free_port() -> int:
    """Bind to port 0, read the OS-assigned port, then release it.

    For tests that need a real bound TCP port (a live uvicorn server an
    external process can actually dial into), not an in-process ASGI transport.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def worker_redis_url(base_url: str) -> str:
    """Return a Redis URL with a per-xdist-worker DB number.

    Offsets from the base DB configured in the URL so ``redis://.../8``
    becomes ``/8`` on gw0 and ``/9`` on gw1.  This preserves any DB
    isolation already configured by the caller while still giving each
    xdist worker its own logical database so ``flushdb()`` teardown
    cannot wipe another worker's in-flight keys.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    try:
        worker_num = int(worker.removeprefix("gw"))
    except ValueError:
        worker_num = 0
    match = re.search(r"/(\d+)$", base_url)
    base_db = int(match.group(1)) if match else 0
    db = (base_db + worker_num) % 16
    if match:
        return re.sub(r"/\d+$", f"/{db}", base_url)
    return base_url.rstrip("/") + f"/{db}"


class BindableToolsFakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel with bind_tools() support.

    The real agent (create_agent.py) calls llm.bind_tools(tools) before each
    invocation.  FakeMessagesListChatModel raises NotImplementedError for this.
    This subclass returns itself so the fake pre-programmed responses are
    preserved while production code that calls bind_tools() works correctly.
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "BindableToolsFakeModel":  # type: ignore[override]
        return self


def create_fake_llm(responses: list[str]) -> BindableToolsFakeModel:
    return BindableToolsFakeModel(responses=[AIMessage(content=r) for r in responses])


def create_fake_llm_with_tool_calls(
    tool_calls_then_response: list[dict[str, Any] | str],
) -> BindableToolsFakeModel:
    messages: list[BaseMessage] = []
    for item in tool_calls_then_response:
        if isinstance(item, dict):
            messages.append(AIMessage(content="", tool_calls=[item]))
        else:
            messages.append(AIMessage(content=item))
    return BindableToolsFakeModel(responses=messages)


def assert_tool_called(messages: list[BaseMessage], tool_name: str) -> None:
    tool_calls = extract_tool_calls(messages)
    names = [tc["name"] for tc in tool_calls]
    assert tool_name in names, f"Tool '{tool_name}' not found in tool calls. Found: {names}"


def extract_tool_calls(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            tool_calls.extend(msg.tool_calls)  # type: ignore[arg-type]
    return tool_calls


class MockAuthMiddleware(BaseHTTPMiddleware):
    """Injects a test user into request.state, standing in for WorkOSAuthMiddleware.

    WorkOS SSO can't be driven headlessly in a test, so every API-level test in
    this repo that needs "a signed-in user" swaps this in for the real auth
    middleware instead (see tests/integration/api/conftest.py and
    tests/service/conftest.py). It does not touch any of the business logic
    under test — only the login step no automated test can perform for real.
    """

    def __init__(self, app, user: dict):
        super().__init__(app)
        self._user = user

    async def dispatch(self, request: Request, call_next):
        request.state.authenticated = True
        request.state.user = self._user
        return await call_next(request)


class NoAuthMiddleware(BaseHTTPMiddleware):
    """Sets request.state to unauthenticated, for testing 401 responses."""

    async def dispatch(self, request: Request, call_next):
        request.state.authenticated = False
        request.state.user = None
        return await call_next(request)


class HeaderDrivenAuthMiddleware(BaseHTTPMiddleware):
    """Test-only stand-in for WorkOSAuthMiddleware that trusts an
    ``X-Test-User-Id`` header instead of a real WorkOS session.

    Unlike MockAuthMiddleware (one fixed user baked in at app-construction
    time), this lets a single live server be hit as several different
    signed-in users — simulating separate browsers/accounts — by varying a
    request header, which a plain httpx client pointed at a real bound port
    can do per-call.
    """

    async def dispatch(self, request: Request, call_next):
        user_id = request.headers.get("x-test-user-id")
        if user_id:
            request.state.authenticated = True
            request.state.user = {"user_id": user_id, "email": f"{user_id}@test.local"}
        else:
            request.state.authenticated = False
            request.state.user = None
        return await call_next(request)
