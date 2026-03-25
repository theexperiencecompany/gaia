"""Test data factories for GAIA API tests."""

from datetime import datetime, timezone
from uuid import uuid4

from app.agents.core.state import State


def make_user(**overrides) -> dict:
    defaults = {
        "user_id": str(uuid4()),
        "email": "test@example.com",
        "name": "Test User",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
        "plan": "free",
        "onboarding_completed": True,
    }
    defaults.update(overrides)
    return defaults


def make_conversation(user_id: str | None = None, **overrides) -> dict:
    defaults = {
        "conversation_id": str(uuid4()),
        "user_id": user_id or str(uuid4()),
        "description": "Test conversation",
        "messages": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    return defaults


def make_state(**overrides) -> State:
    defaults = {
        "query": "Hello, how are you?",
        "messages": [],
        "current_datetime": datetime.now(timezone.utc).isoformat(),
        "mem0_user_id": str(uuid4()),
        "memories": [],
        "memories_stored": False,
        "conversation_id": str(uuid4()),
    }
    defaults.update(overrides)
    return State(**defaults)  # type: ignore[arg-type]


def make_tool_call(name: str, args: dict | None = None, id: str | None = None) -> dict:
    return {
        "name": name,
        "args": args or {},
        "id": id or f"call_{uuid4().hex[:24]}",
        "type": "tool_call",
    }


def make_config(
    user_id: str | None = None,
    thread_id: str | None = None,
    **overrides,
) -> dict:
    configurable = {
        "user_id": user_id or str(uuid4()),
        "thread_id": thread_id or str(uuid4()),
    }
    configurable.update(overrides.pop("configurable", {}))
    config = {
        "configurable": configurable,
    }
    config.update(overrides)
    return config


def make_mcp_config(**overrides) -> dict:
    defaults = {
        "server_name": "test-mcp-server",
        "server_url": "http://localhost:8080",  # NOSONAR
        "transport": "sse",
        "enabled": True,
        "tools": [],
    }
    defaults.update(overrides)
    return defaults


def make_integration(provider: str, **overrides) -> dict:
    defaults = {
        "integration_id": str(uuid4()),
        "provider": provider,
        "user_id": str(uuid4()),
        "status": "active",
        "credentials": {
            "access_token": f"test_token_{uuid4().hex[:8]}",
            "refresh_token": f"test_refresh_{uuid4().hex[:8]}",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    return defaults
